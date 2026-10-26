"""Report historical public sources by default; --apply stores and queues verified sources."""

import argparse
import asyncio
import json
import uuid

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.document import Document
from app.services.judilibre_source_maintenance import refresh_judilibre_source


async def run(args):
    if not 1 <= args.limit <= 1000:
        raise ValueError("invalid_maintenance_budget")
    async with async_session_factory() as db:
        statement = select(Document.id).where(
            Document.organisation_id.is_(None), Document.private_dossier_id.is_(None),
            Document.private_conversation_id.is_(None), Document.retired_at.is_(None),
            Document.source_type == "arret_cour_cassation",
            Document.storage_path.startswith("common/judilibre/"),
        ).order_by(Document.id).limit(args.limit)
        if args.after_id:
            statement = statement.where(Document.id > args.after_id)
        ids = list(await db.scalars(statement))
        for doc_id in ids:
            try:
                result = await refresh_judilibre_source(db, doc_id, apply=args.apply)
            except ValueError as exc:
                await db.rollback()
                result = {"document_id": str(doc_id), "error": str(exc)}
            print(json.dumps(result), flush=True)
        print(json.dumps({"next_after_id": str(ids[-1]) if ids else None}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--after-id", type=uuid.UUID)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
