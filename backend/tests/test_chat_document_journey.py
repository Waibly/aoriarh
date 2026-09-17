"""HTTP upload-to-chat journey; paid streaming probe requires explicit opt-in.

Only technical contracts are asserted. Generated answers are reviewed separately.
"""
# ruff: noqa: F811 — shared pytest fixture import.

import json
import os
import time
import uuid
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.main import app
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.membership import Membership
from app.rag.agent import RAGAgent
from tests.test_conversation_documents import planner, task_payload
from tests.test_document_extraction_service import dossier as dossier


@pytest.fixture
async def journey(dossier, client, monkeypatch):
    conv = Conversation(
        id=uuid.uuid4(),
        organisation_id=dossier.org.id,
        user_id=dossier.user.id,
        messages=[],
        title="Journey",
    )
    dossier.db.add(conv)
    await dossier.db.commit()
    monkeypatch.setattr(settings, "document_extraction_enabled", True)
    app.dependency_overrides[get_current_user] = lambda: dossier.user
    monkeypatch.setattr("app.services.document_service.storage", dossier.storage)
    monkeypatch.setattr(
        "app.services.document_extraction_service.StorageService", lambda: dossier.storage
    )

    async def upload(file, path):
        dossier.storage.objects[path] = await file.read()

    monkeypatch.setattr(dossier.storage, "upload_file", upload, raising=False)
    monkeypatch.setattr("app.rag.tasks.enqueue_ingestion", AsyncMock())
    monkeypatch.setattr(
        "app.api.conversations.BillingService",
        lambda db: SimpleNamespace(
            get_account_for_organisation=AsyncMock(return_value=SimpleNamespace()),
            check_question_quota=AsyncMock(),
            increment_question_count=AsyncMock(),
            ensure_plan_active=MagicMock(),
            check_document_limit=AsyncMock(),
        ),
    )

    async def attach(name="note.txt", data=b"Salaire indique : 2400 euros bruts mensuels"):
        response = await client.post(
            f"/api/v1/conversations/{conv.id}/documents", files={"file": (name, data)}
        )
        assert response.status_code == 201, response.text
        ref = response.json()
        return {key: ref[key] for key in ("document_id", "extraction_id")}

    return SimpleNamespace(conv=conv, attach=attach, url=f"/api/v1/conversations/{conv.id}")


@pytest.mark.parametrize(
    "fault,expected",
    [
        ("missing_document", 404),
        ("foreign_document", 404),
        ("revoked", 404),
        ("replacement", 409),
        ("missing_extraction", 503),
    ],
)
async def test_uploaded_document_unavailable_never_reaches_llm(
    journey,
    dossier,
    client,
    monkeypatch,
    fault,
    expected,
):
    ref = await journey.attach()
    doc = await dossier.db.get(Document, uuid.UUID(ref["document_id"]))
    if fault == "missing_document":
        await dossier.db.delete(doc)
    elif fault == "foreign_document":
        doc.organisation_id = dossier.other_org.id
    elif fault == "revoked":
        await dossier.db.execute(delete(Membership).where(Membership.user_id == dossier.user.id))
    elif fault == "replacement":
        doc.storage_path += ".new"
    else:
        del dossier.storage.objects[dossier.storage.puts[-1]]
    await dossier.db.commit()
    agent_factory = MagicMock(side_effect=AssertionError("No LLM for unreadable attachment"))
    monkeypatch.setattr("app.api.conversations.RAGAgent", agent_factory)
    response = await client.post(
        journey.url + "/chat/stream",
        json={"message": "Lis cette pièce", "document_references": [ref]},
    )
    assert response.status_code == expected, response.text
    agent_factory.assert_not_called()


async def test_uploaded_attachment_inherits_then_rechecks_revoked_access(
    journey,
    dossier,
    client,
    monkeypatch,
):
    ref = await journey.attach()
    agent = planner(json.dumps(task_payload("documents")))
    seen = []

    async def generate(query, results, **kwargs):
        seen.append(results)
        yield "  Original conservé\n"

    agent.stream_generate = generate
    monkeypatch.setattr("app.api.conversations.RAGAgent", lambda: agent)
    response = await client.post(
        journey.url + "/chat/stream",
        json={
            "message": "Lis cette pièce",
            "document_references": [ref],
        },
    )
    assert "chat_done" in response.text, response.text
    await dossier.db.execute(delete(Membership).where(Membership.user_id == dossier.user.id))
    await dossier.db.commit()
    response = await client.post(journey.url + "/chat/stream", json={"message": "Et le montant ?"})
    assert response.status_code == 404, response.text
    assert len(seen) == 1


@pytest.mark.skipif(os.environ.get("AORIA_PAID_JOURNEY") != "1", reason="Explicit paid opt-in only")
async def test_paid_two_uploads_three_turns_raw_stream(journey, dossier, client, monkeypatch):
    import httpx
    from docx import Document as Docx
    from openai import AsyncOpenAI

    from app.services.cost_tracker import PRICING, compute_cost, cost_tracker

    out = Path(os.environ["AORIA_JOURNEY_OUTPUT"])
    out.mkdir(parents=True, exist_ok=False)
    records, requests, usage = [], [], []
    reserved = 0.0

    async def guard(request):
        nonlocal reserved
        payload = json.loads(request.content)
        model, size = payload["model"], len(request.content)
        assert ("openai", model) in PRICING
        upper = float(compute_cost("openai", model, size, payload.get("max_completion_tokens", 0)))
        assert len(requests) < 6 and size < 100000 and reserved + upper < 3
        reserved += upper
        requests.append(payload)

    http = httpx.AsyncClient(event_hooks={"request": [guard]})
    llm = AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0, timeout=120, http_client=http)
    monkeypatch.setattr(cost_tracker, "log_bg", lambda **kw: usage.append(kw))
    # No remote search or production Qdrant: these are explicitly factual tasks.
    legal = AsyncMock(side_effect=RuntimeError("Legal corpus outside this HTTP probe"))
    monkeypatch.setattr("app.api.conversations.prepare_rag_context", legal)

    def agent_factory():
        agent = RAGAgent.__new__(RAGAgent)
        agent.llm = llm
        agent._is_replay = True
        return agent

    monkeypatch.setattr("app.api.conversations.RAGAgent", agent_factory)
    questions = [
        "Prépare un court mail de clarification du salaire à partir des deux documents. "
        "Pas d'argumentation juridique : signale simplement les montants contradictoires.",
        "Je corrige : le montant convenu serait 2450 euros. Reprends le mail en distinguant "
        "ce que je viens d'indiquer et ce qui est écrit dans les documents.",
        "Laisse le mail. Relève seulement le montant écrit dans le contrat signé, "
        "pas ma correction orale.",
    ]
    (out / "protocol.json").write_text(
        json.dumps(
            dict(
                questions=questions,
                max_calls=6,
                max_reserved_usd=3,
                expected="Mail 2500/2400, correction 2450 attribuée à l'utilisateur, "
                "dernière lecture du contrat 2400 ; aucun droit inventé.",
                isolation="SQLite + memory object storage; real TXT/DOCX extraction, "
                "HTTP/SSE and LLM. "
                "Billing, auth identity, ingestion queue mocked. No browser or legal corpus.",
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    try:
        docx = Docx()
        docx.add_paragraph("Contrat signé — salaire brut mensuel : 2400 euros.")
        docx.add_paragraph("Aucune autre précision salariale dans cet extrait.")
        buffer = BytesIO()
        docx.save(buffer)
        refs = [
            await journey.attach(
                "proposition.txt",
                ("Proposition de recrutement — salaire brut mensuel : 2500 euros.").encode(),
            ),
            await journey.attach("contrat.docx", buffer.getvalue()),
        ]
        for number, question in enumerate(questions):
            body = {"message": question}
            if number == 0:
                body["document_references"] = refs
            start = time.perf_counter()
            response = await client.post(journey.url + "/chat/stream", json=body)
            records.append(
                dict(
                    request=body,
                    status=response.status_code,
                    raw_sse=response.text,
                    seconds=time.perf_counter() - start,
                )
            )
            assert "chat_done" in response.text, response.text
        messages = (
            (
                await dossier.db.execute(
                    select(Message)
                    .where(Message.conversation_id == journey.conv.id)
                    .order_by(Message.created_at)
                )
            )
            .scalars()
            .all()
        )
        # Persistence and SSE integrity, not an editorial check on the answer.
        answers = [m.content for m in messages if m.role == "assistant"]
        for record, answer in zip(records, answers, strict=True):
            events = [
                json.loads(line[6:])
                for line in record["raw_sse"].splitlines()
                if line.startswith("data: ")
            ]
            record["persisted_answer"] = answer
            record["events"] = events
            deltas = [json.loads(line[6:])["content"]
                      for block in record["raw_sse"].split("\n\n")
                      if block.startswith("event: chat_delta\n")
                      for line in block.splitlines() if line.startswith("data: ")]
            assert "".join(deltas) == answer
        assert all(len(m.document_references) == 2 for m in messages if m.role == "user")
        (out / "messages.json").write_text(
            json.dumps(
                [
                    dict(role=m.role, content=m.content, document_references=m.document_references)
                    for m in messages
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        for item in usage:
            item["cost_usd"] = float(
                compute_cost(
                    item["provider"],
                    item["model"],
                    item["tokens_input"],
                    item.get("tokens_output", 0),
                )
            )
        (out / "results.json").write_text(
            json.dumps(
                dict(
                    records=records,
                    requests=requests,
                    usage=usage,
                    total_cost_usd=sum(x["cost_usd"] for x in usage),
                    legal_calls=legal.await_count,
                ),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        await llm.close()
