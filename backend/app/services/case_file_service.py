"""Persistence, access control and versioning for conversation case files."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.case_file import (
    CaseDocumentLink,
    CaseEntry,
    CaseEvent,
    CaseFile,
    CaseTask,
)
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.services.organisation_context_service import load_organisation_context

CASE_FILE_LOAD_OPTIONS = (
    selectinload(CaseFile.entries),
    selectinload(CaseFile.tasks),
    selectinload(CaseFile.document_links),
    selectinload(CaseFile.events),
)


class CaseFileApplyError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _case_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        # Calendar dates have no timezone. PostgreSQL timestamptz bindings need
        # an aware value; this is a storage convention, not a inferred fact.
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    except ValueError as exc:
        raise CaseFileApplyError("invalid_case_datetime") from exc


class CaseFileService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def import_history(
        self,
        conversation_id: uuid.UUID,
        user: User,
        message_ids: list[uuid.UUID],
        expected_version: int,
    ) -> None:
        case_file, _ = await self.get_case_file(conversation_id, user)
        messages = (
            (
                await self.db.execute(
                    select(Message)
                    .where(
                        Message.conversation_id == conversation_id,
                        Message.role == "user",
                        Message.id.in_(message_ids),
                    )
                    .order_by(Message.created_at)
                )
            )
            .scalars()
            .all()
        )
        if {m.id for m in messages} != set(message_ids):
            raise HTTPException(404, "Message utilisateur non trouvé dans cette conversation")
        if sum(len(m.content) for m in messages) > 100_000:
            raise HTTPException(413, "Sélection trop volumineuse : choisissez moins de messages")
        changed = await self.db.execute(
            update(CaseFile)
            .where(
                CaseFile.id == case_file.id,
                CaseFile.version == expected_version,
            )
            .values(version=CaseFile.version + 1, updated_at=datetime.now(UTC))
        )
        if changed.rowcount != 1:
            await self.db.rollback()
            raise HTTPException(409, "Le dossier a été modifié. Rechargez-le.")
        existing_message_ids = set(
            (
                await self.db.execute(
                    select(CaseEntry.source_message_id).where(
                        CaseEntry.case_file_id == case_file.id,
                        CaseEntry.label == "Message historique sélectionné par l’utilisateur",
                    )
                )
            ).scalars()
        )
        for message in messages:
            if message.id in existing_message_ids:
                continue
            self.db.add(
                CaseEntry(
                    case_file_id=case_file.id,
                    entry_type="party_statement",
                    label="Message historique sélectionné par l’utilisateur",
                    value_text=message.content,
                    status="active",
                    source_kind="user_message",
                    source_message_id=message.id,
                    created_by_user_id=user.id,
                )
            )
        self.db.add(
            CaseEvent(
                case_file_id=case_file.id,
                case_version=expected_version + 1,
                event_type="history_imported",
                actor_type="user",
                structured_delta={"message_ids": [str(m.id) for m in messages]},
            )
        )
        await self.db.commit()

    async def create_for_conversation(
        self,
        conversation: Conversation,
        *,
        actor_type: str = "system",
    ) -> CaseFile:
        """Create the empty dossier and retain the context seen at creation."""
        existing = (
            await self.db.execute(
                select(CaseFile).where(CaseFile.conversation_id == conversation.id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        inherited_context = await load_organisation_context(self.db, conversation.organisation_id)
        try:
            # A savepoint makes lazy backfill safe when two first reads race.
            async with self.db.begin_nested():
                case_file = CaseFile(conversation_id=conversation.id)
                self.db.add(case_file)
                await self.db.flush()
                self.db.add(
                    CaseEvent(
                        case_file_id=case_file.id,
                        case_version=1,
                        event_type="created",
                        actor_type=actor_type,
                        organisation_context_snapshot=inherited_context,
                        structured_delta={"entries": [], "tasks": [], "documents": []},
                    )
                )
                await self.db.flush()
            return case_file
        except IntegrityError:
            concurrent = (
                await self.db.execute(
                    select(CaseFile).where(CaseFile.conversation_id == conversation.id)
                )
            ).scalar_one_or_none()
            if concurrent is None:
                raise
            return concurrent

    async def get_case_file(
        self, conversation_id: uuid.UUID, user: User
    ) -> tuple[CaseFile, dict[str, str | bool | None] | None]:
        """Load a dossier after applying the conversation's existing ACL."""
        from app.services.conversation_service import ConversationService

        conversation = await ConversationService(self.db).get_conversation(
            conversation_id, user, include_messages=False
        )
        case_file = await self._load_for_conversation(conversation_id)
        if case_file is None:
            await self.create_for_conversation(conversation, actor_type="system_backfill")
            await self.db.commit()
            case_file = await self._load_for_conversation(conversation_id)
        if case_file is None:  # Defensive: creation must always make it queryable.
            raise RuntimeError("Le dossier conversationnel n'a pas pu être initialisé")

        inherited_context = await load_organisation_context(self.db, conversation.organisation_id)
        return case_file, inherited_context

    async def _load_for_conversation(self, conversation_id: uuid.UUID) -> CaseFile | None:
        result = await self.db.execute(
            select(CaseFile)
            .options(*CASE_FILE_LOAD_OPTIONS[:3])
            .where(CaseFile.conversation_id == conversation_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def observation_context(
        self, conversation: Conversation
    ) -> tuple[CaseFile, dict[str, Any]]:
        """Return the current dossier state without changing its active content."""
        case_file = (
            await self.db.execute(
                select(CaseFile).where(CaseFile.conversation_id == conversation.id)
            )
        ).scalar_one_or_none()
        if case_file is None:
            case_file = await self.create_for_conversation(
                conversation, actor_type="system_backfill"
            )
            await self.db.flush()

        entries = list(
            (
                await self.db.execute(
                    select(CaseEntry)
                    .where(
                        CaseEntry.case_file_id == case_file.id,
                        CaseEntry.status.in_(["active", "confirmed", "contested"]),
                    )
                    .order_by(CaseEntry.created_at)
                )
            ).scalars()
        )
        tasks = list(
            (
                await self.db.execute(
                    select(CaseTask)
                    .where(
                        CaseTask.case_file_id == case_file.id,
                        CaseTask.status.in_(
                            [
                                "pending",
                                "blocked",
                                "in_progress",
                                "technical_error",
                                "ready_for_generation",
                            ]
                        ),
                    )
                    .order_by(CaseTask.created_at)
                )
            ).scalars()
        )
        document_links = list(
            (
                await self.db.execute(
                    select(CaseDocumentLink).where(CaseDocumentLink.case_file_id == case_file.id)
                )
            ).scalars()
        )
        return case_file, {
            "version": case_file.version,
            "status": case_file.status,
            "entries": [
                {
                    "id": str(item.id),
                    "entry_type": item.entry_type,
                    "key": item.key,
                    "label": item.label,
                    "value_text": item.value_text,
                    "value_json": item.value_json,
                    "status": item.status,
                    "valid_from": item.valid_from.isoformat() if item.valid_from else None,
                    "valid_to": item.valid_to.isoformat() if item.valid_to else None,
                    "source_kind": item.source_kind,
                    "source_message_id": str(item.source_message_id)
                    if item.source_message_id
                    else None,
                    "source_excerpt": item.source_excerpt,
                    "source_document_id": str(item.source_document_id)
                    if item.source_document_id
                    else None,
                    "source_extraction_id": str(item.source_extraction_id)
                    if item.source_extraction_id
                    else None,
                }
                for item in entries
            ],
            "tasks": [
                {
                    "id": str(item.id),
                    "task_type": item.task_type,
                    "question": item.question,
                    "status": item.status,
                    "depends_on": item.depends_on,
                    "relevant_entry_ids": item.relevant_entry_ids,
                    "required_document_ids": item.required_document_ids,
                }
                for item in tasks
            ],
            "documents": [
                {
                    "document_id": str(link.document_id) if link.document_id else None,
                    "extraction_id": str(link.extraction_id) if link.extraction_id else None,
                    "name": link.document_name,
                    "reading_scope": link.reading_scope,
                    "source_sha256": link.source_sha256,
                }
                for link in document_links
            ],
        }

    async def record_planner_observation(
        self,
        *,
        case_file: CaseFile,
        raw_planner_output: str | None,
        structured_delta: dict | None,
        technical_error: str | None,
        organisation_context_snapshot: dict | None,
        source_message_id: uuid.UUID | None = None,
    ) -> CaseEvent:
        """Persist one planner output verbatim without applying its proposals."""
        event = CaseEvent(
            case_file_id=case_file.id,
            case_version=case_file.version,
            event_type="planner_observation",
            source_message_id=source_message_id,
            actor_type="llm_observer",
            organisation_context_snapshot=organisation_context_snapshot,
            raw_planner_output=raw_planner_output,
            structured_delta=structured_delta,
            technical_error=technical_error,
        )
        self.db.add(event)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def apply_planner_delta(
        self,
        *,
        case_file: CaseFile,
        expected_version: int,
        case_delta: dict,
        case_tasks: list[dict],
        documents: list[dict],
        source_message_id: uuid.UUID,
        user_id: uuid.UUID,
        observation_event_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Apply one technically valid planner delta as a single new version."""
        proposals = list(case_delta.get("entries") or [])
        target_ids = {
            uuid.UUID(str(item["target_entry_id"]))
            for item in proposals
            if item.get("target_entry_id")
        }
        targets: dict[uuid.UUID, CaseEntry] = {}
        if target_ids:
            targets = {
                item.id: item
                for item in (
                    await self.db.execute(
                        select(CaseEntry).where(
                            CaseEntry.case_file_id == case_file.id,
                            CaseEntry.id.in_(target_ids),
                        )
                    )
                ).scalars()
            }
            if set(targets) != target_ids:
                raise CaseFileApplyError("case_entry_target_not_found")

        existing_links = {
            (str(document_id), str(extraction_id))
            for document_id, extraction_id in (
                await self.db.execute(
                    select(CaseDocumentLink.document_id, CaseDocumentLink.extraction_id).where(
                        CaseDocumentLink.case_file_id == case_file.id
                    )
                )
            ).all()
        }
        new_documents = [
            item
            for item in documents
            if (str(item["document_id"]), str(item["extraction_id"])) not in existing_links
        ]
        has_changes = bool(proposals or case_tasks or documents)
        if not has_changes:
            return {
                "applied": False,
                "version": expected_version,
                "entries_created": 0,
                "entries_changed": 0,
                "tasks_created": 0,
                "documents_linked": 0,
            }

        version_update = await self.db.execute(
            update(CaseFile)
            .where(CaseFile.id == case_file.id, CaseFile.version == expected_version)
            .values(version=CaseFile.version + 1, updated_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
        if version_update.rowcount != 1:
            raise CaseFileApplyError("case_version_conflict")
        next_version = expected_version + 1

        active_entries = list(
            (
                await self.db.execute(
                    select(CaseEntry).where(
                        CaseEntry.case_file_id == case_file.id,
                        CaseEntry.status.in_(["active", "confirmed", "contested"]),
                    )
                )
            ).scalars()
        )
        key_to_entry_ids: dict[str, list[str]] = {}
        for entry in active_entries:
            if entry.key:
                key_to_entry_ids.setdefault(entry.key, []).append(str(entry.id))

        created_entry_ids: list[str] = []
        changed_entry_ids: list[str] = []
        await self.invalidate_calculations(case_file.id, {str(item) for item in target_ids})
        for proposal in proposals:
            operation = proposal["operation"]
            target = (
                targets.get(uuid.UUID(str(proposal["target_entry_id"])))
                if proposal.get("target_entry_id")
                else None
            )
            if operation in {"revise", "contest", "archive"}:
                if target is None or target.status not in {"active", "confirmed", "contested"}:
                    raise CaseFileApplyError("case_entry_target_not_active")
                target.status = {
                    "revise": "superseded",
                    "contest": "contested",
                    "archive": "archived",
                }[operation]
                changed_entry_ids.append(str(target.id))
            if operation == "archive":
                continue

            entry = CaseEntry(
                case_file_id=case_file.id,
                entry_type=proposal["entry_type"],
                key=proposal.get("key"),
                label=proposal["label"],
                value_text=proposal.get("value_text"),
                value_json=proposal.get("numeric_value"),
                status="contested" if operation == "contest" else "active",
                valid_from=_case_datetime(proposal.get("valid_from")),
                valid_to=_case_datetime(proposal.get("valid_to")),
                source_kind=proposal["source_kind"],
                source_message_id=source_message_id,
                source_document_id=(
                    uuid.UUID(str(proposal["source_document_id"]))
                    if proposal.get("source_document_id")
                    else None
                ),
                source_extraction_id=(
                    uuid.UUID(str(proposal["source_extraction_id"]))
                    if proposal.get("source_extraction_id")
                    else None
                ),
                source_excerpt=proposal.get("source_excerpt"),
                supersedes_entry_id=target.id if operation == "revise" and target else None,
                created_by_user_id=user_id,
            )
            self.db.add(entry)
            if operation == "contest" and target is not None:
                entry.value_json = {
                    **(entry.value_json or {}),
                    "contradicts_entry_id": str(target.id),
                }
            await self.db.flush()
            created_entry_ids.append(str(entry.id))
            if entry.key:
                if operation == "revise" and target and target.key == entry.key:
                    key_to_entry_ids[entry.key] = [
                        value
                        for value in key_to_entry_ids.get(entry.key, [])
                        if value != str(target.id)
                    ]
                key_to_entry_ids.setdefault(entry.key, []).append(str(entry.id))

        task_ids: dict[str, str] = {}
        created_task_ids: list[str] = []
        for proposal in case_tasks:
            if proposal.get("replaces_task_id"):
                previous = await self.db.get(CaseTask, uuid.UUID(str(proposal["replaces_task_id"])))
                if previous is None or previous.case_file_id != case_file.id:
                    raise CaseFileApplyError("case_task_target_not_found")
                if previous.status not in {
                    "pending",
                    "blocked",
                    "in_progress",
                    "technical_error",
                    "ready_for_generation",
                }:
                    raise CaseFileApplyError("case_task_target_not_open")
                previous.status = "superseded"
            relevant_entry_ids = [
                entry_id
                for key in proposal["relevant_entry_keys"]
                for entry_id in key_to_entry_ids.get(key, [])
            ]
            task = CaseTask(
                case_file_id=case_file.id,
                task_type=proposal["task_type"],
                question=proposal["question"],
                status="pending",
                depends_on=[task_ids[item] for item in proposal["depends_on"]],
                relevant_entry_ids=relevant_entry_ids,
                required_document_ids=[str(item) for item in proposal["required_document_ids"]],
                created_from_message_id=source_message_id,
            )
            self.db.add(task)
            await self.db.flush()
            task_ids[proposal["id"]] = str(task.id)
            created_task_ids.append(str(task.id))

        created_document_link_ids: list[str] = []
        for document in documents:
            await self.db.execute(
                update(CaseDocumentLink)
                .where(
                    CaseDocumentLink.case_file_id == case_file.id,
                    CaseDocumentLink.document_id == uuid.UUID(str(document["document_id"])),
                    CaseDocumentLink.extraction_id == uuid.UUID(str(document["extraction_id"])),
                )
                .values(reading_scope=document.get("transmitted_scope", "full_extracted_text"))
            )
        for document in new_documents:
            link = CaseDocumentLink(
                case_file_id=case_file.id,
                document_id=uuid.UUID(str(document["document_id"])),
                extraction_id=uuid.UUID(str(document["extraction_id"])),
                role="conversation_evidence",
                document_name=document["source_name"],
                source_sha256=document.get("source_sha256"),
                reading_scope=document.get("transmitted_scope", "full_extracted_text"),
                added_from_message_id=source_message_id,
            )
            self.db.add(link)
            await self.db.flush()
            created_document_link_ids.append(str(link.id))

        result = {
            "applied": True,
            "version": next_version,
            "entries_created": len(created_entry_ids),
            "entries_changed": len(changed_entry_ids),
            "tasks_created": len(created_task_ids),
            "documents_linked": len(created_document_link_ids),
            "created_entry_ids": created_entry_ids,
            "changed_entry_ids": changed_entry_ids,
            "created_task_ids": created_task_ids,
            "created_document_link_ids": created_document_link_ids,
        }
        self.db.add(
            CaseEvent(
                case_file_id=case_file.id,
                case_version=next_version,
                event_type="delta_applied",
                source_message_id=source_message_id,
                actor_type="llm_planner",
                structured_delta={
                    "observation_event_id": str(observation_event_id),
                    "case_delta": case_delta,
                    "case_tasks": case_tasks,
                    "document_reads": [
                        {
                            "document_id": str(d["document_id"]),
                            "extraction_id": str(d["extraction_id"]),
                            "reading_scope": d.get("transmitted_scope", "full_extracted_text"),
                            "source_sha256": d.get("source_sha256"),
                        }
                        for d in documents
                    ],
                    "application_result": result,
                },
            )
        )
        await self.db.commit()
        case_file.version = next_version
        return result

    async def record_delta_application_error(
        self,
        *,
        case_file: CaseFile,
        source_message_id: uuid.UUID,
        observation_event_id: uuid.UUID,
        technical_error: str,
    ) -> CaseEvent:
        current_version = (
            await self.db.execute(select(CaseFile.version).where(CaseFile.id == case_file.id))
        ).scalar_one()
        event = CaseEvent(
            case_file_id=case_file.id,
            case_version=current_version,
            event_type="delta_application_error",
            source_message_id=source_message_id,
            actor_type="application",
            structured_delta={"observation_event_id": str(observation_event_id)},
            technical_error=technical_error,
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def record_task_execution(
        self,
        *,
        case_file: CaseFile,
        source_message_id: uuid.UUID,
        task_ids: list[str],
        task_results: list[dict],
        snapshot: dict,
    ) -> None:
        """Store arithmetic and execution state, never assess generated prose."""
        updated = await self.db.execute(
            update(CaseFile)
            .where(CaseFile.id == case_file.id, CaseFile.version == snapshot["version"])
            .values(version=CaseFile.version + 1, updated_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
        if updated.rowcount != 1:
            await self.db.rollback()
            raise CaseFileApplyError("case_version_conflict")
        task_inputs: dict[str, set[str]] = {}
        for task_id, result in zip(task_ids, task_results, strict=True):
            task = await self.db.get(CaseTask, uuid.UUID(task_id))
            if task is None or task.case_file_id != case_file.id:
                raise CaseFileApplyError("case_task_target_not_found")
            task.status = result["status"]
            dependency_entries = set(task.relevant_entry_ids) | set(
                result.get("bound_entry_ids", [])
            )
            for dependency in task.depends_on:
                dependency_entries.update(task_inputs.get(dependency, set()))
            if result.get("specification"):
                spec = result["specification"]
                keys = {v["entry_key"] for v in spec["variables"] if v["entry_key"]}
                dependency_entries.update(e["id"] for e in snapshot["entries"] if e["key"] in keys)
                entry_ids = sorted(dependency_entries)
                self.db.add(
                    CaseEntry(
                        case_file_id=case_file.id,
                        entry_type="calculation",
                        label=spec["scenario"],
                        value_text=result.get("result"),
                        value_json={
                            **result,
                            "case_version": snapshot["version"],
                            "relevant_entry_ids": entry_ids,
                            "task_id": task_id,
                        },
                        status="active" if result["status"] == "executed" else "blocked",
                        source_kind="calculation",
                        source_message_id=source_message_id,
                    )
                )
            task_inputs[task_id] = dependency_entries
        self.db.add(
            CaseEvent(
                case_file_id=case_file.id,
                case_version=snapshot["version"] + 1,
                event_type="tasks_executed",
                actor_type="application",
                source_message_id=source_message_id,
                structured_delta={"tasks": task_results},
            )
        )
        await self.db.commit()
        await self.db.refresh(case_file)

    async def link_task_answer(
        self,
        conversation_id: uuid.UUID,
        source_message_id: uuid.UUID,
        answer_id: uuid.UUID,
        expected_version: int | None = None,
        used_version: int | None = None,
    ) -> int | None:
        case_id = select(CaseFile.id).where(CaseFile.conversation_id == conversation_id)
        task_ids = list(
            (
                await self.db.execute(
                    select(CaseTask.id).where(
                        CaseTask.case_file_id.in_(case_id),
                        CaseTask.created_from_message_id == source_message_id,
                        CaseTask.status.in_(["ready_for_generation", "executed"]),
                        CaseTask.result_message_id.is_(None),
                    )
                )
            ).scalars()
        )
        if not task_ids:
            return None
        version = (
            await self.db.execute(
                update(CaseFile)
                .where(CaseFile.conversation_id == conversation_id)
                .where(
                    CaseFile.version == expected_version if expected_version is not None else True
                )
                .values(version=CaseFile.version + 1, updated_at=datetime.now(UTC))
                .returning(CaseFile.version)
            )
        ).scalar_one_or_none()
        if version is None:
            await self.db.rollback()
            raise CaseFileApplyError("case_version_conflict")
        await self.db.execute(
            update(CaseTask)
            .where(CaseTask.id.in_(task_ids))
            .values(result_message_id=answer_id, status="executed")
        )
        case_file_id = (await self.db.execute(case_id)).scalar_one()
        legal_tasks = list(
            (
                await self.db.execute(
                    select(CaseTask).where(
                        CaseTask.case_file_id == case_file_id,
                        CaseTask.result_message_id == answer_id,
                        CaseTask.task_type == "legal_question",
                    )
                )
            ).scalars()
        )
        if legal_tasks:
            answer = await self.db.get(Message, answer_id)
            self.db.add(
                CaseEntry(
                    case_file_id=case_file_id,
                    entry_type="legal_finding",
                    label="Analyse juridique — réponse originale",
                    value_json={
                        "answer_id": str(answer_id),
                        "case_version": used_version if used_version is not None else version - 1,
                        "task_ids": [str(task.id) for task in legal_tasks],
                        "sources": [
                            {
                                key: value
                                for key, value in source.items()
                                if key in {"document_id", "extraction_id", "chunk_index", "title"}
                            }
                            for source in (answer.sources or [])
                        ]
                        if answer
                        else [],
                    },
                    status="active",
                    source_kind="assistant_message",
                    source_message_id=answer_id,
                )
            )
        self.db.add(
            CaseEvent(
                case_file_id=case_file_id,
                case_version=version,
                event_type="tasks_finalized",
                actor_type="application",
                source_message_id=source_message_id,
                structured_delta={"answer_id": str(answer_id), "used_case_version": used_version},
            )
        )
        await self.db.commit()
        return version

    async def invalidate_calculations(self, case_file_id: uuid.UUID, entry_ids: set[str]) -> None:
        entries = (
            (
                await self.db.execute(
                    select(CaseEntry).where(
                        CaseEntry.case_file_id == case_file_id,
                        CaseEntry.entry_type == "calculation",
                        CaseEntry.status == "active",
                    )
                )
            )
            .scalars()
            .all()
        )
        for entry in entries:
            if entry_ids.intersection((entry.value_json or {}).get("relevant_entry_ids", [])):
                entry.status = "stale"
                task_id = (entry.value_json or {}).get("task_id")
                if task_id:
                    await self.db.execute(
                        update(CaseTask)
                        .where(
                            CaseTask.case_file_id == case_file_id,
                            CaseTask.id == uuid.UUID(task_id),
                        )
                        .values(status="blocked")
                    )

    async def revise_entry(
        self,
        *,
        conversation_id: uuid.UUID,
        entry_id: uuid.UUID,
        expected_version: int,
        user: User,
        value_text: str | None,
        value_json: dict | list | None,
        label: str | None = None,
    ) -> CaseEntry:
        """Compatibility wrapper for an append-only user correction."""
        return await self.apply_user_entry_action(
            conversation_id=conversation_id,
            entry_id=entry_id,
            expected_version=expected_version,
            user=user,
            operation="correct",
            value_text=value_text,
            value_json=value_json,
            label=label,
        )

    async def apply_user_entry_action(
        self,
        *,
        conversation_id: uuid.UUID,
        entry_id: uuid.UUID,
        expected_version: int,
        user: User,
        operation: str,
        value_text: str | None = None,
        value_json: dict | list | None = None,
        label: str | None = None,
        comment: str | None = None,
    ) -> CaseEntry:
        """Apply an explicit user decision with optimistic version control."""
        if operation not in {"confirm", "correct", "contest", "archive"}:
            raise HTTPException(status_code=422, detail="Action de dossier non reconnue")
        case_file, _ = await self.get_case_file(conversation_id, user)
        original = (
            await self.db.execute(
                select(CaseEntry).where(
                    CaseEntry.id == entry_id,
                    CaseEntry.case_file_id == case_file.id,
                )
            )
        ).scalar_one_or_none()
        if original is None:
            raise HTTPException(status_code=404, detail="Élément du dossier non trouvé")
        if original.entry_type == "calculation":
            raise HTTPException(
                status_code=422,
                detail=(
                    "Un résultat calculé ne se modifie pas directement. Corrigez ses données "
                    "sources et demandez un nouveau calcul."
                ),
            )
        if original.status not in {"active", "confirmed", "contested"}:
            raise HTTPException(status_code=409, detail="Cet élément n’est plus actif")
        if operation == "confirm" and original.status == "confirmed":
            raise HTTPException(status_code=409, detail="Cet élément est déjà confirmé")
        if operation == "contest" and original.status == "contested":
            raise HTTPException(status_code=409, detail="Cet élément est déjà contesté")
        if operation == "correct" and value_text is None and value_json is None:
            raise HTTPException(status_code=422, detail="La valeur corrigée est obligatoire")

        result = await self.db.execute(
            update(CaseFile)
            .where(CaseFile.id == case_file.id, CaseFile.version == expected_version)
            .values(version=CaseFile.version + 1, updated_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Le dossier a été modifié. Rechargez-le avant de corriger cet élément.",
            )

        next_version = expected_version + 1
        affected_entry = original
        replacement = None
        previous_status = original.status
        if operation in {"correct", "contest", "archive"}:
            await self.invalidate_calculations(case_file.id, {str(original.id)})
        if operation == "correct":
            original.status = "superseded"
            replacement = CaseEntry(
                case_file_id=case_file.id,
                entry_type=original.entry_type,
                key=original.key,
                label=label if label is not None else original.label,
                value_text=value_text,
                value_json=value_json,
                status="confirmed",
                valid_from=original.valid_from,
                valid_to=original.valid_to,
                source_kind="user_correction",
                source_excerpt=comment,
                supersedes_entry_id=original.id,
                created_by_user_id=user.id,
            )
            self.db.add(replacement)
            await self.db.flush()
            affected_entry = replacement
        else:
            original.status = {
                "confirm": "confirmed",
                "contest": "contested",
                "archive": "archived",
            }[operation]
        self.db.add(
            CaseEvent(
                case_file_id=case_file.id,
                case_version=next_version,
                event_type={
                    "confirm": "entry_confirmed",
                    "correct": "entry_revised",
                    "contest": "entry_contested",
                    "archive": "entry_archived",
                }[operation],
                actor_type="user",
                structured_delta={
                    "operation": operation,
                    "entry_id": str(original.id),
                    "previous_status": previous_status,
                    "resulting_status": affected_entry.status,
                    "replacement_entry_id": str(replacement.id) if replacement else None,
                    "comment": comment,
                },
            )
        )
        await self.db.commit()
        case_file.version = next_version
        await self.db.refresh(affected_entry)
        return affected_entry

    @staticmethod
    def public_payload(
        case_file: CaseFile,
        inherited_context: dict[str, str | bool | None] | None,
    ) -> dict[str, Any]:
        return {
            "id": case_file.id,
            "conversation_id": case_file.conversation_id,
            "version": case_file.version,
            "status": case_file.status,
            "inherited_context": inherited_context,
            "entries": case_file.entries,
            "tasks": case_file.tasks,
            "documents": case_file.document_links,
            "created_at": case_file.created_at,
            "updated_at": case_file.updated_at,
        }

    @staticmethod
    def export_payload(case_file: CaseFile) -> dict[str, Any]:
        """Return all dossier data, including its technical/audit history."""

        def timestamp(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        return {
            "id": str(case_file.id),
            "version": case_file.version,
            "status": case_file.status,
            "created_at": timestamp(case_file.created_at),
            "updated_at": timestamp(case_file.updated_at),
            "entries": [
                {
                    "id": str(item.id),
                    "entry_type": item.entry_type,
                    "key": item.key,
                    "label": item.label,
                    "value_text": item.value_text,
                    "value_json": item.value_json,
                    "status": item.status,
                    "valid_from": timestamp(item.valid_from),
                    "valid_to": timestamp(item.valid_to),
                    "source_kind": item.source_kind,
                    "source_message_id": str(item.source_message_id)
                    if item.source_message_id
                    else None,
                    "source_document_id": str(item.source_document_id)
                    if item.source_document_id
                    else None,
                    "source_extraction_id": str(item.source_extraction_id)
                    if item.source_extraction_id
                    else None,
                    "source_excerpt": item.source_excerpt,
                    "supersedes_entry_id": str(item.supersedes_entry_id)
                    if item.supersedes_entry_id
                    else None,
                    "created_at": timestamp(item.created_at),
                }
                for item in case_file.entries
            ],
            "tasks": [
                {
                    "id": str(item.id),
                    "task_type": item.task_type,
                    "question": item.question,
                    "status": item.status,
                    "depends_on": item.depends_on,
                    "relevant_entry_ids": item.relevant_entry_ids,
                    "required_document_ids": item.required_document_ids,
                    "created_from_message_id": str(item.created_from_message_id)
                    if item.created_from_message_id
                    else None,
                    "result_message_id": str(item.result_message_id)
                    if item.result_message_id
                    else None,
                    "created_at": timestamp(item.created_at),
                }
                for item in case_file.tasks
            ],
            "documents": [
                {
                    "id": str(item.id),
                    "document_id": str(item.document_id) if item.document_id else None,
                    "extraction_id": str(item.extraction_id) if item.extraction_id else None,
                    "role": item.role,
                    "document_name": item.document_name,
                    "source_sha256": item.source_sha256,
                    "reading_scope": item.reading_scope,
                    "added_from_message_id": str(item.added_from_message_id)
                    if item.added_from_message_id
                    else None,
                    "created_at": timestamp(item.created_at),
                }
                for item in case_file.document_links
            ],
            "events": [
                {
                    "id": str(item.id),
                    "case_version": item.case_version,
                    "event_type": item.event_type,
                    "source_message_id": str(item.source_message_id)
                    if item.source_message_id
                    else None,
                    "actor_type": item.actor_type,
                    "organisation_context_snapshot": item.organisation_context_snapshot,
                    "raw_planner_output": item.raw_planner_output,
                    "structured_delta": item.structured_delta,
                    "technical_error": item.technical_error,
                    "created_at": timestamp(item.created_at),
                }
                for item in case_file.events
            ],
        }


async def delete_case_files_for_conversations(
    db: AsyncSession, conversation_ids: list[uuid.UUID]
) -> int:
    """Explicitly erase dossiers for bulk-deletion paths and SQLite tests."""
    if not conversation_ids:
        return 0
    ids = list(
        (
            await db.execute(
                select(CaseFile.id).where(CaseFile.conversation_id.in_(conversation_ids))
            )
        ).scalars()
    )
    if not ids:
        return 0
    await db.execute(delete(CaseDocumentLink).where(CaseDocumentLink.case_file_id.in_(ids)))
    await db.execute(delete(CaseTask).where(CaseTask.case_file_id.in_(ids)))
    await db.execute(delete(CaseEntry).where(CaseEntry.case_file_id.in_(ids)))
    await db.execute(delete(CaseEvent).where(CaseEvent.case_file_id.in_(ids)))
    await db.execute(delete(CaseFile).where(CaseFile.id.in_(ids)))
    return len(ids)
