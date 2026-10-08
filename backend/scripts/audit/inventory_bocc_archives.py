"""Inventory downloaded BOCC archives locally; no database or queue access.

Example, from backend:
.venv/bin/python -m scripts.audit.inventory_bocc_archives \
 --manifest ../docs/recherche/lot-documentaire-2026-10-08/bocc-a-rattraper.json \
 --archives /tmp/aoria-bocc-2026 --output /tmp/bocc-inventory

All individual PDFs are listed, including unknown headers and agreements
without an IDCC. Metadata extraction never decides admission to the corpus.
"""
import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path

import pymupdf

from app.services.bocc_metadata import extract_metadata


def inventory(manifest, archives, output):
    output.mkdir(parents=True, exist_ok=True)
    texts = output / 'texts'
    texts.mkdir(exist_ok=True)
    documents, errors, counts = [], [], []
    for entry in manifest:
        number = entry['numero']
        if not re.fullmatch(r'\d{4}-\d{2}', number):
            raise ValueError('Invalid BOCC number')
        path = archives / f'{number}.taz'
        try:
            raw_archive = path.read_bytes()
            result = subprocess.run(['gzip', '-dc', str(path)], check=True,
                                    capture_output=True, timeout=120)
            count = 0
            with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
                for member in archive:
                    if not (member.isfile() and member.name.endswith('.pdf')
                            and '_0000_' in member.name):
                        continue
                    count += 1
                    row = {'archive': number, 'archive_url': entry['url'], 'pdf': member.name}
                    try:
                        data = archive.extractfile(member).read()
                        with pymupdf.open(stream=data, filetype='pdf') as pdf:
                            raw = '\n'.join(page.get_text() for page in pdf)
                            row['pages'] = len(pdf)
                        name = f'{number}_{Path(member.name).name}.txt'
                        (texts / name).write_text(raw)
                        row.update(extract_metadata(raw))
                        row.update(sha256=hashlib.sha256(data).hexdigest(),
                                   characters=len(raw), text_file=name)
                    except Exception as exc:
                        row['error'] = str(exc)[:500]
                    documents.append(row)
            if not count:
                raise ValueError('No individual PDFs found')
            counts.append({'numero': number, 'individual_pdfs': count,
                           'sha256': hashlib.sha256(raw_archive).hexdigest()})
        except Exception as exc:
            errors.append({'archive': number, 'error': str(exc)[:500]})
    result = {'archives': counts, 'documents': documents, 'errors': errors,
              'production_mutations': 0, 'embedding_calls': 0}
    (output / 'inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--archives', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = inventory(json.loads(args.manifest.read_text()), args.archives, args.output)
    print(f"{len(result['documents'])} PDFs; {len(result['errors'])} archive errors")
    if result['errors'] or any('error' in row for row in result['documents']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
