"""Opt-in local HTTP/PG/MinIO/Qdrant/LLM smoke test with temporary fictional files.
Only local ports 8001/5544 are used. Original SSE and traces are saved; no output repair.
"""
import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path

import asyncpg
import httpx

API = 'http://127.0.0.1:8001/api/v1'
ORG = '9ccf7c74-09c6-4d0c-a22a-f4b21fbdd1f6'


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not args.run:
        raise SystemExit('Use --run for up to four paid local chat requests and file indexing.')
    args.output.mkdir(parents=True,exist_ok=False)
    dossier_id=None
    async with httpx.AsyncClient(timeout=300) as client:
        login=await client.post(API+'/auth/login',json={'email':'dossiers-local@example.com','password':'Local-Dossiers-2026!'})
        login.raise_for_status()
        headers={'Authorization':'Bearer '+login.json()['access_token']}
        async def request(method,path,**kw):
            result=await client.request(method,API+path,headers=headers,**kw)
            result.raise_for_status()
            return result.json() if result.content else None
        try:
            dossier=await request('POST','/dossiers/',json={'name':'Recette temporaire — consultation ciblée','organisation_id':ORG,'creation_key':str(uuid.uuid4())})
            dossier_id=dossier['id']
            filler='\n\n'.join(f'Section {i} — Organisation des missions. '+
                ('Les équipes préparent les déplacements et classent les comptes rendus. Les demandes de prise en charge administrative sont transmises au secrétariat. Le dossier contient les coordonnées de mission, la liste des participants et les modalités de réservation des salles. Aucun montant de transport n’est fixé dans cette section. ' * 4)
                for i in range(110))
            text='Règlement mobilité — société fictive Horizon.\n'+filler+'\n\nArticle 117 — Retour tardif de mission. Pour une arrivée à la gare après 22 heures, un taxi entre la gare et le domicile est remboursé sur reçu dans la limite de 65 euros. Le reçu doit être transmis sous 30 jours.\n'
            note='Note de frais fictive : Nina est revenue d’une mission professionnelle à 23 h à la gare. Elle a pris un taxi jusqu’à son domicile pour 52 euros. Elle dispose du reçu.\n'
            save(args.output/'fixtures.json',dict(dossier_id=dossier_id,documents={'reglement-mobilite.txt':text,'note-de-frais.txt':note}))
            for name,content in [('reglement-mobilite.txt',text),('note-de-frais.txt',note)]:
                dossier=await request('POST',f'/dossiers/{dossier_id}/documents',files={'file':(name,content.encode(),'text/plain')})
                print('Uploaded',name,len(content.encode()),flush=True)
            for _ in range(150):
                dossier=await request('GET',f'/dossiers/{dossier_id}')
                if all(d['status']=='ready' for d in dossier['documents']):
                    break
                await asyncio.sleep(1)
            else:
                save(args.output/'readiness-error.json',dossier)
                raise RuntimeError('Local index not ready; no generation attempted')
            cases=[
                ('mail_dossier','Rédige uniquement un mail à Léa pour confirmer notre rendez-vous de recrutement mardi 13 octobre 2026 à 10 h, au 12 rue des Lilas à Lyon. Je signe Camille.'),
                ('depense','D’après les documents de ce dossier, ma dépense est-elle prise en charge ?'),
                ('delai','Quel délai de dépôt du reçu prévoit le règlement mobilité fourni ?')]
            for label,question in cases:
                conv=await request('POST','/conversations/',json={'organisation_id':ORG,'dossier_id':dossier_id,'title':'Recette '+label})
                record=dict(question=question,conversation_id=conv['id'],events=[],raw_text='')
                start=time.perf_counter()
                async with client.stream('POST',API+f"/conversations/{conv['id']}/chat/stream",headers=headers,json={'message':question}) as response:
                    response.raise_for_status()
                    event=''
                    async for line in response.aiter_lines():
                        if line.startswith('event: '):event=line[7:]
                        elif line.startswith('data: '):
                            data=json.loads(line[6:]);record['events'].append(dict(event=event,data=data))
                            if event=='chat_delta':
                                record.setdefault('first_text_s',time.perf_counter()-start)
                                record['raw_text']+=data['content']
                record['seconds']=time.perf_counter()-start
                db=await asyncpg.connect(host='127.0.0.1',port=5544,database='aoriarh',user='aoriarh',password='aoria-local-only')
                try:
                    row=await db.fetchrow("SELECT rag_trace, question_id FROM messages WHERE conversation_id=$1 AND role='assistant' ORDER BY created_at DESC LIMIT 1",uuid.UUID(conv['id']))
                    if row:
                        record['trace']=json.loads(row['rag_trace']) if isinstance(row['rag_trace'],str) else row['rag_trace']
                        usage=await db.fetch('SELECT provider,model,operation_type,tokens_input,tokens_output,cost_usd FROM api_usage_logs WHERE context_id=$1',row['question_id'])
                        record['usage']=[dict(x) for x in usage]
                finally:
                    await db.close()
                save(args.output/(label+'.json'),record)
                print(label,round(record['seconds'],2),'seconds',flush=True)
                if any(e['event']=='chat_error' for e in record['events']):
                    raise RuntimeError('Technical chat error; original stream retained, no retry')
        finally:
            if dossier_id:
                latest=await request('GET',f'/dossiers/{dossier_id}')
                await request('DELETE',f'/dossiers/{dossier_id}?expected_version={latest["version"]}')
                print('Temporary dossier and private files deleted',flush=True)


if __name__=='__main__':
    asyncio.run(main())
