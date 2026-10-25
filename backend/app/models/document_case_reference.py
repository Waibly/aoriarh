from datetime import date
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DocumentCaseReference(Base):
    __tablename__ = "document_case_references"
    __table_args__ = (Index("ix_document_case_references_lookup", "decision_date", "number"),)

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    number: Mapped[str] = mapped_column(String(100), primary_key=True)
    decision_date: Mapped[date] = mapped_column(Date, nullable=False)
