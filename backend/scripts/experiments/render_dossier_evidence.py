"""Render original pilot outputs and separately authored assessments, without LLM calls."""
import argparse
import html
import json
import statistics
from pathlib import Path


def esc(value):
    return html.escape(str(value))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--followup', type=Path)
    args = parser.parse_args()
    protocol = json.loads((args.folder / 'protocol.json').read_text())
    records = []
    for path in [p for folder in [args.folder, args.followup] if folder for p in folder.glob('*-*-?.json')]:
        record = json.loads(path.read_text())
        if 'seconds' in record:
            records.append(record)
    assessments_path = args.folder / 'assessments.json'
    assessments = json.loads(assessments_path.read_text()) if assessments_path.exists() else {}
    metrics = {}
    for variant in protocol.get('variants', ['A', 'B', 'C'] if args.followup else ['A', 'B']):
        selected = [r for r in records if r['variant'] == variant]
        if not selected:
            continue
        input_tokens = sum(c.get('usage', {}).get('prompt_tokens', 0) for r in selected for c in r['calls'])
        cached = sum((c.get('usage', {}).get('prompt_tokens_details') or {}).get('cached_tokens', 0) for r in selected for c in r['calls'])
        metrics[variant] = dict(n=len(selected), errors=sum(bool(r.get('error')) for r in selected),
            calls=sum(len(r['calls']) for r in selected), tools=sum(len(r['tool_results'])+len(r.get('evidence_results',[])) for r in selected),
            median_seconds=statistics.median(r['seconds'] for r in selected),
            mean_seconds=statistics.mean(r['seconds'] for r in selected),
            median_first_answer_seconds=statistics.median(r['first_answer_s'] for r in selected if r.get('first_answer_s') is not None),
            estimated_usd=sum(r['estimated_usd'] for r in selected),
            input_tokens=input_tokens, cached_input_tokens=cached,
            output_tokens=sum(c.get('usage', {}).get('completion_tokens', 0) for r in selected for c in r['calls']))
    (args.folder / 'metrics.json').write_text(json.dumps(metrics, indent=2))
    rows = ''.join('<tr><th>'+esc(label)+'</th>'+''.join('<td>'+esc(f'{metrics[v][key]:.4f}' if isinstance(metrics[v][key],float) else metrics[v][key])+'</td>' for v in metrics)+'</tr>' for key,label in [
        ('n','Réponses'),('errors','Erreurs techniques'),('calls','Appels IA'),('tools','Consultations simulées'),
        ('median_seconds','Durée médiane (s)'),('mean_seconds','Durée moyenne (s)'),
        ('median_first_answer_seconds','Premier texte, médiane (s)'),('estimated_usd','Coût total estimé (USD)'),
        ('input_tokens','Tokens entrants'),('cached_input_tokens','Tokens entrants en cache'),('output_tokens','Tokens sortants')])
    sections=[]
    for case in protocol['cases']:
        parts=['<section><h2>'+esc(case['id'])+'</h2><p>'+esc(case['question'])+'</p><p><b>Critères définis avant exécution :</b> '+esc(' '.join(case['criteria']))+'</p>']
        for repeat in range(1,protocol['repeats']+1):
            parts.append('<h3>Passage '+str(repeat)+'</h3><div class="pair">')
            for variant in metrics:
                record=next((r for r in records if r['case']==case['id'] and r['repeat']==repeat and r['variant']==variant),None)
                if not record:
                    continue
                actions=' → '.join(o['action']+' ('+o['status']+')' for o in [*record['tool_results'],*record.get('evidence_results',[])]) or 'Aucune consultation'
                parts.append('<article><h4>'+variant+'</h4><p>'+esc(f"{record['seconds']:.2f} s · ${record['estimated_usd']:.5f} estimés · {len(record['calls'])} appels IA")+'</p><p>'+esc(actions)+'</p><pre>'+esc(record['raw_text'])+'</pre></article>')
            parts.append('</div>')
        if case['id'] in assessments:
            parts.append('<aside><b>Évaluation séparée :</b> '+esc(assessments[case['id']])+'</aside>')
        parts.append('</section>')
        sections.append(''.join(parts))
    review = assessments.get('_conclusion', 'Évaluation séparée en attente.')
    page='''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AORIA RH — pilote de vérification documentaire</title>
<style>body{font:16px/1.6 system-ui;background:#f7f7fb;color:#242033;max-width:1240px;margin:40px auto;padding:0 24px}h1,h2{color:#5b2d92}table{border-collapse:collapse;background:white;width:100%}td,th{padding:10px;border:1px solid #ddd;text-align:left}section{margin-top:32px;padding:24px;background:white;border-radius:12px}.pair{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px}article{min-width:0;border:1px solid #ddd;padding:16px;border-radius:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}aside{padding:16px;background:#f0e8fa;margin-top:20px}@media(max-width:800px){.pair{grid-template-columns:1fr}}</style>
<h1>Vérifier avant de demander une pièce</h1><p><a href="protocol.json">Protocole et cas figés</a> · <a href="metrics.json">Mesures</a> · <a href="assessments.json">Appréciations séparées</a></p><p>Comparaison de composants — 8 octobre 2026. A : consignes actuelles. B : consignes de vérification ciblée dans les appels existants. C : consignes initiales, avec au plus un appel supplémentaire de planification des consultations si une pièce est partiellement lue ou trouvée sans être lue.</p>
<p><b>Périmètre :</b> vrais appels de planification et de rédaction, composants et modèles du projet, situations fictives. Résultats d’outils figés identiques entre variantes. La recherche sémantique, la base juridique, les écritures de dossier et le parcours HTTP ne sont pas mesurés. Ce pilote n’est pas une validation juridique ni un benchmark de production.</p>
<p>Deux passages indépendants par situation, ordre A/B alterné. C est une exploration réalisée après avoir observé A/B, sur les mêmes cas ; ce n’est pas un jeu de validation indépendant. Aucun remplacement de réponse, aucune relance éditoriale. Les textes ci-dessous sont intégraux, échappés pour l’affichage. Les appréciations sont séparées et réalisées par l’assistant, pas par un juriste indépendant.</p>
<p>Coûts estimés avec le barème local : cache non déduit, tarifs non vérifiés sur une facture. Les temps incluent les appels IA mais excluent les véritables recherches, leur indexation, leur classement et le réseau HTTP applicatif. Un éventuel surcoût des consultations supplémentaires reste à mesurer.</p>
<p>Méthode : <a href="https://developers.openai.com/api/docs/guides/evaluation-best-practices">documentation officielle OpenAI</a> — critères préalables, cas comparables, examen séparé des sorties.</p>
'''+ '<aside>'+esc(review)+'</aside><h2>Mesures du pilote</h2><table><tr><th>Mesure</th>'+''.join('<th>'+v+' — '+{'A':'actuel','B':'consignes','C':'consultation ciblée'}[v]+'</th>' for v in metrics)+'</tr>'+rows+'</table>'+''.join(sections)+'</html>'
    if args.followup:
        page=page.replace('</html>', '<section><h2>Contre-exemples supplémentaires</h2><p><a href="../dossier-evidence-holdout-2026-10-08/rapport.html">Mail dans un dossier partiellement lu et recherche sans résultat</a></p></section></html>')
    (args.folder/'rapport.html').write_text(page)
    print(json.dumps(metrics,indent=2))


if __name__=='__main__':
    main()
