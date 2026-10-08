"""Opt-in paired component experiment; real LLM, frozen tool results, no app writes.

Output text is never repaired or graded in the execution path. Review is separate.
This tests planning and drafting, NOT production retrieval recall or HTTP latency.
"""
import argparse
import asyncio
import hashlib
import json
import logging
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))

PLANNER_ADDITION = """
VÉRIFICATIONS NÉCESSAIRES À LA DEMANDE
Avant de décider une clarification, identifie les seuls éléments dont une valeur différente
changerait la réponse ou le livrable demandé. Vérifie d'abord les faits et pièces déjà fournis.
Ne demande pas à l'utilisateur une information déjà lisible dans ce contexte.
Si un élément déterminant reste inconnu et qu'une pièce active pourrait le contenir mais
n'a été lue que par passages, demande search_uploaded_passages avec une question ciblée sur
cet élément. Une première sélection ne prouve ni l'absence d'une clause ni celle d'une preuve.
Ne relis pas sans motif une pièce déjà lue intégralement. L'extraction reste non certifiée.
Si la réponse requiert une pièce déjà déposée mais non jointe et identifiée par l'utilisateur,
find_existing_document puis read_existing_document sont permis pour ce besoin précis, même
sans demande explicite de lecture. Ne découvre pas de dossiers personnels voisins ; garde le
périmètre de l'utilisateur. Ne choisis jamais parmi plusieurs personnes ou fichiers ambigus.
Cette règle remplace la restriction exigeant une demande explicite de lecture pour rechercher
une pièce nécessaire. Une liste de pièces à réunir n'est toujours pas une recherche de fichiers.
Si rien d'accessible ne permet d'établir le fait, prépare une clarification ciblée sur le seul
point bloquant. Une panne de lecture est une erreur technique, pas une pièce absente.
Pour une question générale ou un mail factuel déjà réalisable, n'ajoute pas une enquête sur
le dossier : utilise les éléments suffisants. Ne crée pas d'obligations de droit non sourcées.
Ne produis aucun score de confiance ni contrôle de qualité d'une future réponse.
"""
GENERATION_ADDITION = """
PRÉCISION SUR LES ÉLÉMENTS NON ÉTABLIS
Avant d'affirmer qu'une pièce ou information manque, distingue une absence déclarée par
l'utilisateur, un point non retrouvé dans les passages consultés et un échec technique.
Une sélection de passages ne prouve pas qu'un document ne contient pas de disposition.
Si l'élément est fourni dans les faits ou les pièces, utilise-le sans le redemander.
Pose une question seulement si sa réponse change réellement la conclusion demandée ;
réponds aux parties déjà établies. Pour un courrier réalisable, fournis le courrier sans
ajouter d'audit juridique ni de collecte de pièces inutile. N'affirme pas avoir exécuté une
consultation non présente dans les résultats. Ne récite pas ce contrôle à l'utilisateur.
"""


def uid(label):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'aoria-evidence-pilot/' + label))


def doc(label, text, scope='full_extracted_text'):
    return dict(document_id=uid(label), extraction_id=uid(label + '/extraction'),
                source_name=label, text=text, transmitted_scope=scope,
                coverage={'file_completeness': 'not_certified'})


def fixtures():
    partial = doc('Accord mobilité — société fictive Horizon',
                  'Extraits consultés : article 1. L’accord concerne les déplacements professionnels. '
                  'Article 2. Les justificatifs sont conservés par le salarié.', 'targeted_passages')
    full = doc('Accord mobilité — société fictive Horizon',
               'Article 1. L’accord concerne les déplacements professionnels. Article 2. Les justificatifs '
               'sont conservés. Article 7. Pour une arrivée après 22 heures, un taxi domicile-gare '
               'est remboursé dans la limite de 65 euros, sur reçu.')
    return [
        dict(id='clause_hors_extraits', mode='dossier',
             question='Selon notre accord, le taxi de 52 euros entre la gare et mon domicile après mon arrivée à 23 h est-il remboursable ? J’ai le reçu.',
             documents=[partial], passages=[full], library=[], legal=[],
             criteria=['Chercher la clause dans la pièce active avant de réclamer l’accord.',
                       'Retrouver 65 euros, arrivée après 22 h, reçu ; appliquer à 52 euros.',
                       'Ne pas conclure que l’accord est silencieux.']),
        dict(id='piece_deja_complete', mode='dossier',
             question='Selon notre accord, le taxi de 52 euros entre la gare et mon domicile après mon arrivée à 23 h est-il remboursable ? J’ai le reçu.',
             documents=[full], passages=[full], library=[], legal=[],
             criteria=['Répondre avec la clause déjà fournie sans demande de pièce ni consultation inutile.']),
        dict(id='piece_reellement_absente', mode='dossier',
             question='Notre politique de mobilité n’est pas déposée ici et je ne connais pas ses conditions. Est-ce que mon taxi de 52 euros à 23 h est remboursable selon cette politique ?',
             documents=[], passages=[], library=[], legal=[],
             criteria=['Demander la politique ou sa clause, sans inventer plafond ou droit au remboursement.',
                       'Ne pas chercher un document explicitement non déposé.']),
        dict(id='mail_simple', mode='chat',
             question='Rédige uniquement un mail à Léa pour confirmer notre rendez-vous de recrutement mardi 13 octobre 2026 à 10 h, au 12 rue des Lilas à Lyon. Je signe Camille.',
             documents=[], passages=[], library=[], legal=[],
             criteria=['Fournir le mail avec les faits exacts, sans demander de pièces ni recherche.']),
        dict(id='contradiction', mode='dossier',
             question='À quelle date dois-je me rendre à mon entretien avec Nina ? Les deux courriers reçus sont dans ce dossier.',
             documents=[doc('Invitation envoyée le 5 octobre', 'Entretien avec Nina le 13 octobre 2026 à 10 h.'),
                        doc('Invitation envoyée le 5 octobre — autre fichier', 'Entretien avec Nina le 14 octobre 2026 à 10 h.')],
             passages=[], library=[], legal=[],
             criteria=['Signaler les deux dates contradictoires et demander confirmation.',
                       'Ne pas choisir arbitrairement ni demander de redéposer les courriers.']),
        dict(id='catalogue_ambigu', mode='chat',
             question='Quelle est la date de prise de poste de Martin ? Son contrat est déjà dans mes documents.',
             documents=[], passages=[],
             library=[doc('Contrat Martin Dupont', 'Martin Dupont prend son poste le 2 novembre 2026.'),
                      doc('Contrat Martin Legrand', 'Martin Legrand prend son poste le 9 novembre 2026.')], legal=[],
             criteria=['Chercher le contrat existant, puis demander quel Martin sans lire ou choisir arbitrairement.']),
        dict(id='catalogue_unique', mode='chat',
             question='Quelle est la date de prise de poste de Nina Morel ? Son contrat est déjà dans mes documents.',
             documents=[], passages=[],
             library=[doc('Contrat Nina Morel', 'Nina Morel prend son poste le 2 novembre 2026.')], legal=[],
             criteria=['Retrouver et lire le contrat, donner le 2 novembre 2026 sans redemander le dépôt.']),
        dict(id='droit_sources_absentes', mode='chat',
             question='Quelles sont les conditions légales pour renouveler une période d’essai en CDI ? Je demande la règle générale, pas l’analyse d’un salarié.',
             documents=[], passages=[], library=[], legal=[],
             criteria=['Déclencher une recherche juridique sans demander un contrat personnel.',
                       'Ne pas prétendre que la recherche sans résultat prouve l’absence de règle.',
                       'Distinguer toute connaissance générale d’une règle vérifiée par les sources.']),
    ]


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))


class Capture:
    def __init__(self, client, record, variant, budget, output):
        self.client, self.record, self.variant, self.budget, self.output = client, record, variant, budget, output
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def with_options(self, **kwargs):
        # Explicit experiment transport policy: no retries, 120-second timeout.
        return self

    async def create(self, **kwargs):
        from app.services.cost_tracker import compute_cost
        kwargs = json.loads(json.dumps(kwargs))
        stream = kwargs.get('stream', False)
        if self.variant == 'B':
            kwargs['messages'][0]['content'] += GENERATION_ADDITION if stream else PLANNER_ADDITION
        # UTF-8 bytes upper-bound tokens, plus generous message overhead and schema bytes.
        input_bound = len(json.dumps(kwargs, ensure_ascii=False).encode()) + 4096
        bound = float(compute_cost('openai', kwargs['model'], input_bound, kwargs['max_completion_tokens']))
        if self.budget['reserved'] + bound > self.budget['max_usd']:
            raise RuntimeError('Experiment estimated budget exhausted before call')
        self.budget['reserved'] += bound
        call = dict(stage='generation' if stream else 'planner', request=kwargs,
                    conservative_bound_usd=bound, started_at=time.time())
        self.record['calls'].append(call)
        dump(self.output, self.record)
        start = time.perf_counter()
        try:
            result = await self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            call.update(error=type(exc).__name__, seconds=time.perf_counter()-start)
            dump(self.output, self.record)
            raise
        def completed(usage):
            if usage:
                call['usage'] = usage.model_dump(mode='json')
                call['estimated_usd'] = float(compute_cost('openai', kwargs['model'], usage.prompt_tokens, usage.completion_tokens))
                self.budget['reserved'] -= bound - call['estimated_usd']
            call['seconds'] = time.perf_counter()-start
            dump(self.output, self.record)
        if not stream:
            call['response'] = result.model_dump(mode='json')
            completed(result.usage)
            return result
        async def chunks():
            usage = None
            call['chunks'] = []
            try:
                async for chunk in result:
                    call['chunks'].append(chunk.model_dump(mode='json'))
                    if chunk.usage:
                        usage = chunk.usage
                    if chunk.choices and chunk.choices[0].delta.content and 'first_token_s' not in call:
                        call['first_token_s'] = time.perf_counter()-start
                    yield chunk
            finally:
                await result.close()
                completed(usage)
        return chunks()


async def run_case(case, variant, repeat, client, budget, folder, model):
    from app.rag.agent import RAGAgent
    from app.rag.config import EXPAND_MODEL
    from app.rag.search import SearchResult
    from app.services.conversation_document_service import DOCUMENT_GUIDANCE
    from app.services.conversation_orchestrator import plan_conversation
    record = dict(case=case['id'], variant=variant, repeat=repeat, calls=[], tool_results=[], raw_text='')
    path = folder / f"{case['id']}-{repeat}-{variant}.json"
    agent = RAGAgent.__new__(RAGAgent)
    agent.llm = Capture(client, record, variant, budget, path)
    agent._org_id = agent._user_id = agent._conversation_id = None
    agent._is_replay = True
    context = dict(version=1, entries=[], tasks=[], documents=[], retired_entries=[])
    if case['mode'] == 'dossier':
        context['dossier'] = dict(id=uid(case['id']), name='Dossier fictif', description='', instructions='')
    documents = list(case['documents'])
    results = []
    def include(d):
        results.append(SearchResult(document_id=d['document_id'], doc_name=d['source_name'], text=d['text'],
                                    source_type='divers', norme_niveau=9, norme_poids=0.1,
                                    chunk_index=len(results), score=1.0))
    for d in documents:
        include(d)
    previous = []
    start = time.perf_counter()
    try:
        for pass_index in range(2):
            planned = await plan_conversation(agent, query=case['question'], history=[],
                active_documents=[{k:d[k] for k in ('document_id','extraction_id')} for d in documents],
                documents=documents, tool_results=record['tool_results'], continuation=bool(pass_index),
                model=EXPAND_MODEL, case_file_context=context, previous_requests=previous)
            record.setdefault('plans', []).append(dict(raw=planned.raw, error=planned.trace.error,
                validation=planned.trace.search_plan_validation,
                plan=planned.plan.model_dump(mode='json') if planned.plan else None))
            if planned.trace.error or planned.plan is None:
                raise RuntimeError('Planner contract error; raw response retained')
            previous = planned.requests or previous
            outputs = {}
            for action in planned.plan.actions:
                output = dict(action_id=action.id, action=action.action, status='no_results')
                if action.action == 'find_documents':
                    candidates = [{k:d[k] for k in ('document_id','extraction_id','source_name')} for d in case['library']]
                    output.update(status='unique' if len(candidates)==1 else 'ambiguous' if candidates else 'not_found',
                                  candidates=candidates)
                elif action.action == 'read_documents':
                    selected = case['library'] if action.source == 'find_result' and len(case['library'])==1 else (
                        documents if action.source == 'active' else [])
                    if action.source_action_id and outputs.get(action.source_action_id, {}).get('status') != 'unique':
                        selected = []
                    if selected:
                        output.update(status='success', documents=selected)
                        for d in selected:
                            if d not in documents:
                                documents.append(d)
                                include(d)
                elif action.action == 'search_documents':
                    selected = case['passages']
                    output.update(status='success' if selected else 'no_results', documents=selected)
                    for d in selected:
                        include(d)
                        documents.append(d)
                elif action.action == 'search_legal':
                    output.update(status='no_results', sources=[])
                else:
                    output.update(status='unsupported_in_fixture')
                outputs[action.id] = output
                record['tool_results'].append(output)
            if not planned.plan.needs_continuation:
                break
            if not any(o['status']=='success' and (o.get('documents') or o.get('sources')) for o in outputs.values()):
                break
            if pass_index == 1:
                raise RuntimeError('Continuation budget exceeded')
        legal = any(o['action']=='search_legal' for o in record['tool_results'])
        document_context = None
        if documents:
            document_context = dict(action='documents_and_law' if legal else 'documents',
                plan={'objective':case['question']}, sources=[dict(source_number=i+1,document_id=r.document_id,
                name=r.doc_name,source_type=r.source_type,role='case_document',extraction_id=uid('extraction'),
                reading_scope='targeted_passages' if any(d['transmitted_scope']=='targeted_passages' for d in documents) else 'full_extracted_text')
                for i,r in enumerate(results)])
        case_context = dict(dossier=context, tasks=previous, branches=[], consultations=record['tool_results'],request_errors=[])
        async for text in agent.stream_generate(case['question'], results, history=[], model_override=model,
                document_task_context=document_context, document_continuity=DOCUMENT_GUIDANCE if documents else None,
                case_context=case_context):
            if 'first_answer_s' not in record:
                record['first_answer_s'] = time.perf_counter()-start
            record['raw_text'] += text
        if not record['raw_text']:
            record['error'] = 'empty_generation'
    except Exception as exc:
        record['error'] = f'{type(exc).__name__}: {exc}'
    record['seconds'] = time.perf_counter()-start
    record['estimated_usd'] = sum(c.get('estimated_usd',0) for c in record['calls'])
    dump(path, record)
    print(case['id'], repeat, variant, f"{record['seconds']:.1f}s", f"${record['estimated_usd']:.5f}", record.get('error','OK'), flush=True)
    return record


async def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / 'backend/.env', override=True)
    from openai import AsyncOpenAI
    from app.core.config import settings
    from app.services.cost_tracker import cost_tracker, PRICING
    from app.rag.config import EXPAND_MODEL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--repeats', type=int, default=2, choices=[1,2])
    args = parser.parse_args()
    assert ('openai', args.model) in PRICING
    args.output.mkdir(parents=True, exist_ok=False)
    cases = fixtures()
    protocol = dict(kind='component_pilot_not_end_to_end', cases=cases,
        generation_model=args.model, planner_model=EXPAND_MODEL, repeats=args.repeats,
        max_calls=len(cases)*2*args.repeats*3, estimated_budget_usd=5,
        pricing_source='repository table, not verified billing; cache discounts excluded',
        pricing={m:PRICING['openai',m] for m in [EXPAND_MODEL,args.model]},
        planner_addition=PLANNER_ADDITION, generation_addition=GENERATION_ADDITION,
        transport='max_retries=0, timeout=120 seconds; no content retries',
        retrieval='Frozen per-fixture outputs, not semantic retrieval. Tests action choice; retrieval cost/time excluded.',
        evaluation='Separate manual evidence review of raw text; no generation repair or hidden retries.',
        source_hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in [
            'backend/app/rag/agent.py','backend/app/services/conversation_requests.py',
            'backend/app/services/conversation_orchestrator.py',
            'backend/scripts/experiments/dossier_evidence_probe.py']})
    dump(args.output/'protocol.json',protocol)
    if not args.run:
        return
    logging.disable(logging.CRITICAL)
    original_log = cost_tracker.log_bg
    cost_tracker.log_bg = lambda **kw: None  # no application DB writes; each API usage saved locally
    budget = dict(max_usd=5, reserved=0.0)
    records=[]
    try:
        async with AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0, timeout=120) as client:
            for repeat in range(1,args.repeats+1):
                for index,case in enumerate(cases):
                    for variant in (['A','B'] if (index+repeat)%2 else ['B','A']):
                        record=await run_case(case,variant,repeat,client,budget,args.output,args.model)
                        records.append(record)
                        dump(args.output/'summary.json',dict(records=[{k:v for k,v in r.items() if k not in {'calls','raw_text','plans','tool_results'}} for r in records],budget=budget))
                        if record.get('error'):
                            raise RuntimeError('Pilot stopped on technical error; no automatic retry')
    finally:
        cost_tracker.log_bg = original_log


if __name__=='__main__':
    asyncio.run(main())
