import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import verify_org_membership
from app.models.conversation import Conversation, Message
from app.models.user import User


class ConversationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_conversation(
        self,
        organisation_id: uuid.UUID,
        user: User,
        title: str | None = None,
    ) -> Conversation:
        """Create a new conversation scoped to an organisation."""
        await self._check_membership(organisation_id, user)

        conversation = Conversation(
            organisation_id=organisation_id,
            user_id=user.id,
            title=title,
        )
        self.db.add(conversation)
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation

    async def list_conversations(
        self,
        organisation_id: uuid.UUID,
        user: User,
    ) -> list[Conversation]:
        """List conversations for the current user in an organisation, newest first."""
        await self._check_membership(organisation_id, user)

        query = (
            select(Conversation)
            .where(
                Conversation.organisation_id == organisation_id,
                Conversation.user_id == user.id,
            )
            .order_by(Conversation.updated_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_conversation(
        self,
        conversation_id: uuid.UUID,
        user: User,
    ) -> Conversation:
        """Get a conversation with its messages. Checks ownership."""
        result = await self.db.execute(
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .where(Conversation.id == conversation_id)
        )
        conversation = result.scalar_one_or_none()

        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation non trouvée",
            )

        if conversation.user_id != user.id and user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès non autorisé à cette conversation",
            )

        return conversation

    async def delete_conversation(
        self,
        conversation_id: uuid.UUID,
        user: User,
    ) -> None:
        """Delete a conversation and all its messages."""
        conversation = await self.get_conversation(conversation_id, user)

        # Delete messages first
        messages_result = await self.db.execute(
            select(Message).where(Message.conversation_id == conversation.id)
        )
        for message in messages_result.scalars().all():
            await self.db.delete(message)

        await self.db.delete(conversation)
        await self.db.commit()

    async def add_message(
        self,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        sources: list[dict] | None = None,
    ) -> Message:
        """Add a message to an existing conversation."""
        result = await self.db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation non trouvée",
            )

        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            sources=sources,
        )
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def update_title(
        self,
        conversation_id: uuid.UUID,
        title: str,
    ) -> None:
        """Set the conversation title (e.g. auto-generated from first message)."""
        result = await self.db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            return

        conversation.title = title
        await self.db.commit()

    async def update_message_feedback(
        self,
        message_id: uuid.UUID,
        user: User,
        feedback: str | None,
    ) -> Message:
        """Update feedback on an assistant message."""
        result = await self.db.execute(
            select(Message)
            .options(selectinload(Message.conversation))
            .where(Message.id == message_id)
        )
        message = result.scalar_one_or_none()

        if message is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message non trouvé",
            )

        if message.conversation.user_id != user.id and user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès non autorisé",
            )

        if message.role != "assistant":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Le feedback ne peut être donné que sur les réponses de l'assistant",
            )

        message.feedback = feedback
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def _check_membership(
        self,
        organisation_id: uuid.UUID,
        user: User,
    ) -> None:
        """Verify that the user is a member of the organisation."""
        if user.role == "admin":
            return
        membership = await verify_org_membership(organisation_id, user, self.db)
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Vous n'êtes pas membre de cette organisation",
            )
