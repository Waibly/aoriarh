"""Apply a reviewed public-corpus scope manifest; preserve text and existing vectors.

Run inside the backend with CORPUS_SCOPE_MANIFEST pointing to JSON. Dry run by
 default; CORPUS_SCOPE_APPLY=1 applies after an immutable S3 backup. No embedding.
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import text

from app.core.database import async_session_factory
from app.rag.qdrant_store import COLLECTION_NAME, get_qdrant_client
from app.services.storage_service import StorageService


async def main():
    actions = json.loads(Path(os.environ['CORPUS_SCOPE_MANIFEST']).read_text())
    assert len({a['id'] for a in actions}) == len(actions)
    client = get_qdrant_client()
    backup, pending = [], []
    async with async_session_factory() as db:
        for action in actions:
            assert action['action'] in {'restore', 'retire'}
            doc = (await db.execute(text(
                'SELECT * FROM documents WHERE id=:id FOR UPDATE'
            ), {'id': uuid.UUID(action['id'])})).mappings().one()
            assert doc['organisation_id'] is None
            assert doc['private_dossier_id'] is None and doc['private_conversation_id'] is None
            assert doc['file_hash'] == action['file_hash']
            assert doc['indexation_status'] == 'indexed'
            f = Filter(must=[FieldCondition(key='document_id', match=MatchValue(value=action['id']))])
            points, offset = [], None
            while True:
                batch, offset = client.scroll(COLLECTION_NAME, scroll_filter=f,
                                              offset=offset, limit=256,
                                              with_payload=True, with_vectors=False)
                points.extend(batch)
                if offset is None:
                    break
            assert points, f"No vectors: {action['id']}"
            assert all(not p.payload.get('private') for p in points)
            scopes = {p.payload['organisation_id'] for p in points}
            already_done = scopes == {action['to_scope']} and (
                (doc['retired_at'] is None) == (action['action'] == 'restore'))
            if already_done:
                continue
            assert scopes == {action['from_scope']}, (action['id'], scopes)
            assert (doc['retired_at'] is not None) == (action['action'] == 'restore')
            backup.append({'action': action, 'document': dict(doc),
                           'points': [{'id': str(p.id), 'payload': p.payload} for p in points]})
            pending.append((action, f, len(points)))
        print(json.dumps({'pending_documents': len(pending),
                          'chunks': sum(n for _, _, n in pending),
                          'apply': os.environ.get('CORPUS_SCOPE_APPLY') == '1'}), flush=True)
        if os.environ.get('CORPUS_SCOPE_APPLY') != '1' or not pending:
            return
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
        key = f'common/audit/corpus-scope/{stamp}-{uuid.uuid4()}.json'
        raw = json.dumps(backup, ensure_ascii=False, default=str).encode()
        storage = StorageService()
        storage.put_file_bytes(key, raw, content_type='application/json')
        assert storage.get_file_bytes_bounded(key, len(raw) + 1) == raw
        print(json.dumps({'backup': key, 'bytes': len(raw)}), flush=True)
        changed = []
        try:
            for action, f, count in pending:
                # Add before call: a timeout may still have applied the mutation.
                changed.append(action)
                client.set_payload(COLLECTION_NAME,
                                   payload={'organisation_id': action['to_scope']},
                                   points=f, wait=True)
                scoped = Filter(must=[f, FieldCondition(key='organisation_id',
                                  match=MatchValue(value=action['to_scope']))])
                assert client.count(COLLECTION_NAME, count_filter=scoped, exact=True).count == count
                value = None if action['action'] == 'restore' else datetime.now(timezone.utc)
                await db.execute(text('UPDATE documents SET retired_at=:value WHERE id=:id'),
                                 {'id': uuid.UUID(action['id']), 'value': value})
            await db.commit()
        except Exception:
            await db.rollback()
            for action in changed:
                f = Filter(must=[FieldCondition(key='document_id', match=MatchValue(value=action['id']))])
                client.set_payload(COLLECTION_NAME,
                                   payload={'organisation_id': action['from_scope']}, points=f, wait=True)
            raise
        print(json.dumps({'applied_documents': len(pending),
                          'restored': sum(a['action'] == 'restore' for a, _, _ in pending),
                          'retired': sum(a['action'] == 'retire' for a, _, _ in pending),
                          'embedding_calls': 0, 'backup': key}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
