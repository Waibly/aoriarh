"""Additional falsification cases defined after C, before running either A or C."""
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'backend'))
from scripts.experiments import dossier_evidence_probe as base
from scripts.experiments.dossier_evidence_followup import EvidenceCapture, EVIDENCE_PROMPT, SCHEMA


async def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT/'backend/.env',override=True)
    from openai import AsyncOpenAI
    from app.core.config import settings
    from app.services.cost_tracker import cost_tracker
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--previous-c',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    protocol=json.loads((args.baseline/'protocol.json').read_text())
    initial=protocol['cases'][0]
    mail=protocol['cases'][3]
    cases=[dict(mail,id='mail_dossier_long',mode='dossier',documents=initial['documents'],passages=initial['passages'],
                criteria=['Rédiger le mail sans utiliser la politique mobilité hors sujet.',
                          'Mesurer si le simple dossier long provoque un appel IA superflu.']),
           dict(initial,id='recherche_sans_clause',passages=[],
                criteria=['Chercher dans la pièce active, mais ne pas inventer la clause si aucun passage ne revient.',
                          'Distinguer consultation sans résultat et absence démontrée de règle.'])]
    args.output.mkdir(parents=True,exist_ok=False)
    protocol.update(cases=cases,variants=['A','C'],repeats=2,holdout=True,
                    evidence_prompt=EVIDENCE_PROMPT,evidence_schema=SCHEMA,
                    note='Additional cases fixed before any holdout call; C remains unchanged.')
    base.dump(args.output/'protocol.json',protocol)
    if not args.run:
        return
    budget=dict(max_usd=5,reserved=json.loads((args.previous_c/'summary.json').read_text())['budget']['reserved'])
    original=base.Capture
    original_log=cost_tracker.log_bg
    class WithFixture(EvidenceCapture):
        def __init__(self,*a,**kw):
            super().__init__(*a,**kw)
            self.record['_fixture']=next(c for c in cases if c['id']==self.record['case'])
    cost_tracker.log_bg=lambda **kw:None
    logging.disable(logging.CRITICAL)
    records=[]
    try:
        async with AsyncOpenAI(api_key=settings.openai_api_key,max_retries=0,timeout=120) as client:
            for repeat in [1,2]:
                for i,case in enumerate(cases):
                    for variant in (['A','C'] if (i+repeat)%2 else ['C','A']):
                        base.Capture=WithFixture if variant=='C' else original
                        record=await base.run_case(case,variant,repeat,client,budget,args.output,protocol['generation_model'])
                        record.pop('_fixture',None)
                        base.dump(args.output/f"{case['id']}-{repeat}-{variant}.json",record)
                        records.append({k:v for k,v in record.items() if k not in {'calls','raw_text','plans','tool_results','evidence_results'}})
                        base.dump(args.output/'summary.json',dict(records=records,budget=budget))
                        if record.get('error'):
                            raise RuntimeError('Stop on error; no automatic retry')
    finally:
        base.Capture=original
        cost_tracker.log_bg=original_log


if __name__=='__main__':
    asyncio.run(main())
