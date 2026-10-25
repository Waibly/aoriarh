"""Exact reference identity shared by bulk and incremental social imports."""

import hashlib

from sqlalchemy import select, text

from app.models.document import Document
from app.models.document_case_reference import DocumentCaseReference
from app.services.dila_cass_service import number_aliases


class ExistingSocialDecisionError(ValueError):
    pass


def aliases(numbers):
    result = sorted({alias for number in numbers for alias in number_aliases(number)})
    if any(len(alias) > 100 for alias in result):
        raise ValueError("Source case reference exceeds the identity storage contract")
    return result


async def lock_case_references(session, day, numbers):
    if session.get_bind().dialect.name != "postgresql":
        return
    for number in aliases(numbers):
        digest = hashlib.sha256(f"social:{day}:{number}".encode()).digest()
        key = int.from_bytes(digest[:8], signed=True)
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


async def find_existing_social_case(session, day, numbers):
    keys = set(aliases(numbers))
    scope = (
        Document.organisation_id.is_(None), Document.private_dossier_id.is_(None),
        Document.private_conversation_id.is_(None), Document.retired_at.is_(None),
        Document.source_type == "arret_cour_cassation", Document.chambre == "Chambre sociale",
        Document.date_decision == day,
    )
    by_alias = (await session.execute(
        select(Document.id).join(DocumentCaseReference).where(
            *scope, DocumentCaseReference.number.in_(keys)
        )
    )).scalars().all()
    found = set(by_alias)
    legacy = (await session.execute(select(Document).where(*scope))).scalars().all()
    for doc in legacy:
        if keys & number_aliases(doc.numero_pourvoi or ""):
            found.add(doc.id)
    return found


async def store_case_references(session, doc, numbers):
    if doc.organisation_id or doc.private_dossier_id or doc.private_conversation_id:
        raise ValueError("Social reference registry only accepts public decisions")
    if (
        not doc.date_decision or doc.source_type != "arret_cour_cassation"
        or doc.chambre != "Chambre sociale"
    ):
        raise ValueError("Invalid social reference owner")
    values = [
        {"document_id": doc.id, "number": number, "decision_date": doc.date_decision}
        for number in aliases(numbers)
    ]
    if not values:
        return
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise ValueError("Unsupported reference registry database")
    for offset in range(0, len(values), 200):
        statement = insert(DocumentCaseReference).values(values[offset:offset + 200])
        await session.execute(statement.on_conflict_do_nothing())
