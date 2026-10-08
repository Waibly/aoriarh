"""Explicit private scope, checked before any document content is read."""

from fastapi import HTTPException

from app.models.conversation import Conversation
from app.models.document import Document


def company_document_conditions():
    return (
        Document.private_dossier_id.is_(None),
        Document.private_conversation_id.is_(None),
        Document.retired_at.is_(None),
    )


async def authorize_private_document(db, doc, user, *, dossier_id=None, conversation_id=None):
    if doc.retired_at is not None:
        raise HTTPException(404, "Document retiré ou non accessible")
    if doc.private_dossier_id is not None:
        from app.services.dossier_service import DossierService

        if dossier_id != doc.private_dossier_id:
            raise HTTPException(404, "Document non accessible dans ce contexte")
        dossier = await DossierService(db).get(dossier_id, user)
        if dossier.organisation_id != doc.organisation_id:
            raise HTTPException(404, "Document non accessible")
    elif doc.private_conversation_id is not None:
        if conversation_id != doc.private_conversation_id:
            raise HTTPException(404, "Document non accessible dans ce contexte")
        conversation = await db.get(Conversation, conversation_id)
        if (
            conversation is None
            or conversation.hidden_at is not None
            or conversation.organisation_id != doc.organisation_id
            or (conversation.user_id != user.id and user.role != "admin")
        ):
            raise HTTPException(404, "Document non accessible")
