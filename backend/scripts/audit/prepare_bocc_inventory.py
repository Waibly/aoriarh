"""Prepare a local BOCC inventory; never writes to DB/storage or queues jobs.

From backend: .venv/bin/python -m scripts.audit.prepare_bocc_inventory \
  --manifest ../docs/recherche/lot-documentaire-2026-10-08/bocc-a-rattraper.json \
  --output /tmp/bocc-inventory.json --idcc 0413 1486 1408 2216 2247 7001

Add --download to fetch and parse PDFs locally. No embeddings are generated.
Unmatched PDFs remain explicitly listed; KALI deduplication is a later step.
"""
import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.services.bocc_service import DILA_BASE_URL, BoccService


async def prepare(manifest, idccs, download=False):
    service = BoccService()
    rows = []
    async with httpx.AsyncClient(timeout=120) as client:
        for entry in manifest:
            year, number = map(int, entry['numero'].split('-'))
            allowed = {
                f'{DILA_BASE_URL}/{directory}/CCO{year}{number:04d}.complet.taz'
                for directory in (str(year), 'FluxAnneeCourante')
            }
            if entry['url'] not in allowed:
                raise ValueError(f"Unexpected archive URL: {entry['numero']}")
            row = {
                'numero': entry['numero'], 'url': entry['url'],
                'status': 'not_downloaded', 'documents': [], 'unparsed_pdfs': [],
                'documents_to_import': None, 'kali_comparison': 'not_performed',
            }
            rows.append(row)
            if not download:
                continue
            try:
                response = await client.get(entry['url'])
                response.raise_for_status()
                row['archive_sha256'] = hashlib.sha256(response.content).hexdigest()
                pdfs = service._extract_individual_pdfs(response.content)
                if not pdfs:
                    raise ValueError('No individual PDF extracted')
                for name, data in pdfs:
                    try:
                        document = service._parse_avenant_pdf(data)
                        if document is None:
                            row['unparsed_pdfs'].append({
                                'name': name, 'error': 'metadata_unrecognized',
                            })
                            continue
                        row['documents'].append({
                            'pdf': name, 'sha256': hashlib.sha256(data).hexdigest(),
                            'nor': document['nor'], 'idcc': document['idcc'],
                            'title': document['titre'],
                            'configured_branch': document['idcc'] in idccs,
                            'characters': len(document['content']),
                            'admission': 'review_required',
                        })
                    except Exception as exc:
                        row['unparsed_pdfs'].append({'name': name, 'error': str(exc)[:300]})
                row['status'] = 'partial' if row['unparsed_pdfs'] else 'inventoried'
            except Exception as exc:
                row['status'] = 'error'
                row['error'] = str(exc)[:500]
    return {
        'captured_at': datetime.now(UTC).isoformat(),
        'configured_idccs': sorted(idccs), 'production_mutations': 0,
        'embedding_calls': 0, 'archives': rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--idcc', nargs='+', required=True)
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    result = asyncio.run(prepare(
        json.loads(args.manifest.read_text()), set(args.idcc), args.download,
    ))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(f"{len(result['archives'])} archives; no production mutations or embeddings")
    if any(r['status'] in {'error', 'partial'} for r in result['archives']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
