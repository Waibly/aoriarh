"""Garde-fous du chemin streaming (/chat/stream).

Principe (Vanessa, 28/07/2026) : ne JAMAIS couper une réponse qui avance,
même lentement — mieux vaut long et complet que rapide et tronqué. On ne
coupe que ce qui est réellement mort, et on prévient l'utilisateur quand
c'est plus lent que d'habitude au lieu de laisser un écran figé.

- RAG_SLOW_NOTICE : message de patience (« plus de temps que d'habitude… »)
  quand rien n'avance, réponse jamais coupée pour autant ;
- Préparation : messages de patience sans coupure sur la durée totale ;
- RAG_TIMEOUT_STREAM_IDLE : inactivité du flux de génération, réarmée à
  chaque token. Un flux lent mais vivant va TOUJOURS au bout ; un flux mort
  est abandonné en conservant et annotant le déjà-émis, puis chat_done.
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from httpx import AsyncClient, Request
from openai import APITimeoutError
from sqlalchemy import select

from app.models.conversation import Message
from app.rag.agent import RagTrace
from app.rag.search import SearchResult
from app.services.conversation_orchestrator import PreparedConversation
from tests.conftest import auth_header
from tests.conftest import test_session_factory as session_factory


async def _make_conversation(client: AsyncClient, manager_user: dict) -> str:
    org_res = await client.post(
        "/api/v1/organisations/",
        headers=auth_header(manager_user["token"]),
        json={"name": "Org Timeout"},
    )
    assert org_res.status_code == 201, org_res.text
    conv_res = await client.post(
        "/api/v1/conversations/",
        headers=auth_header(manager_user["token"]),
        json={"organisation_id": org_res.json()["id"], "title": None},
    )
    assert conv_res.status_code == 201, conv_res.text
    return conv_res.json()["id"]


def _fake_result() -> SearchResult:
    return SearchResult(
        text="Art. L1234-1 — contenu.",
        doc_name="Code du travail",
        document_id="doc-1",
        source_type="code_travail",
        norme_niveau=2,
        norme_poids=1.0,
        chunk_index=0,
        score=0.9,
    )


async def _passthrough_intent(*args, **kwargs):
    from app.rag.intent_router import Intent, IntentResult

    return IntentResult(Intent.LEGAL_QUESTION, static_answer=None, via="test")


async def _fast_prepare_context(*args, **kwargs):
    return PreparedConversation(
        results=[_fake_result()],
        reformulated="question reformulée",
        trace=RagTrace(query_original="q", model="test-model"),
        documents=[],
        references=[],
    )


async def test_real_progress_is_forwarded_before_generation(client, manager_user, monkeypatch):
    conv_id = await _make_conversation(client, manager_user)

    async def prepare(*args, **kwargs):
        kwargs["on_progress"]("Consultation des documents…")
        await asyncio.sleep(0.01)
        kwargs["on_progress"]("Recherche des références utiles…")
        await asyncio.sleep(0.01)
        return await _fast_prepare_context()

    async def generate(*args, **kwargs):
        yield "  Réponse originale\n"

    monkeypatch.setattr("app.api.conversations.classify_intent", _passthrough_intent)
    monkeypatch.setattr("app.services.conversation_orchestrator.prepare_conversation_context", prepare)
    monkeypatch.setattr("app.rag.agent.RAGAgent.stream_generate", generate)
    res = await client.post(f"/api/v1/conversations/{conv_id}/chat/stream",
                            headers=auth_header(manager_user["token"]), json={"message": "Question"})
    assert res.text.index("Consultation des documents") < res.text.index("Recherche des références")
    assert res.text.index("Recherche des références") < res.text.index("event: chat_delta")
    assert "Traitement des éléments chiffrés" not in res.text
    assert "chat_done" in res.text


@pytest.mark.parametrize("raw", ["  sortie brute\n", "[HORS_SCOPE]"])
@pytest.mark.parametrize(
    "error",
    [
        "search_planner_error",
        "search_retrieval_error",
        "search_reranking_error",
        "search_context_error",
    ],
)
async def test_search_failure_emits_raw_details_before_technical_error(
    client: AsyncClient, manager_user: dict, monkeypatch, error: str, raw: str,
) -> None:
    conv_id = await _make_conversation(client, manager_user)

    async def failed_context(*args, **kwargs):
        return PreparedConversation(
            results=[],
            reformulated=raw,
            trace=RagTrace(
                query_original="question", model="test", error=error,
                search_plan={"planner_raw_response": raw},
            ),
            documents=[],
            references=[],
        )

    monkeypatch.setattr("app.api.conversations.classify_intent", _passthrough_intent)
    monkeypatch.setattr(
        "app.services.conversation_orchestrator.prepare_conversation_context",
        failed_context,
    )
    res = await client.post(
        f"/api/v1/conversations/{conv_id}/chat/stream",
        headers=auth_header(manager_user["token"]), json={"message": "Question"},
    )
    assert res.status_code == 200
    events = []
    for block in res.text.replace("\r\n", "\n").split("\n\n"):
        name = next((line[7:] for line in block.splitlines() if line.startswith("event: ")), None)
        data = next((line[6:] for line in block.splitlines() if line.startswith("data: ")), None)
        if name and data:
            events.append((name, json.loads(data)))
    details_index = next(i for i, (name, _) in enumerate(events) if name == "chat_search_details")
    error_index = next(i for i, (name, _) in enumerate(events) if name == "chat_error")
    assert details_index < error_index
    assert events[details_index][1]["raw_response"] == raw
    assert events[error_index][1]["error"] == error
    assert all(name != "chat_delta" for name, _ in events)
    async with session_factory() as db:
        messages = list(
            (
                await db.execute(
                    select(Message).where(Message.conversation_id == uuid.UUID(conv_id))
                )
            ).scalars()
        )
    assert [(message.role, message.content) for message in messages] == [("user", "Question")]


def _patch_timings(monkeypatch, *, slow=0.05, context=0.2, idle=0.3):
    monkeypatch.setattr("app.api.conversations.classify_intent", _passthrough_intent)
    monkeypatch.setattr("app.api.conversations.RAG_SLOW_NOTICE", slow)
    monkeypatch.setattr("app.api.conversations.RAG_TIMEOUT_STREAM_IDLE", idle)


@pytest.mark.parametrize("provider_timeout", [False, True])
async def test_context_timeout_yields_notice_then_clean_error(
    client: AsyncClient, manager_user: dict, monkeypatch,
    provider_timeout: bool,
) -> None:
    conv_id = await _make_conversation(client, manager_user)

    async def hanging_prepare_context(*args, **kwargs):
        if provider_timeout:
            await asyncio.sleep(0.08)
            raise APITimeoutError(request=Request("POST", "https://example.test"))
        await asyncio.sleep(0.08)
        raise TimeoutError("connection timed out")

    _patch_timings(monkeypatch)
    monkeypatch.setattr(
        "app.services.conversation_orchestrator.prepare_conversation_context",
        hanging_prepare_context,
    )

    res = await client.post(
        f"/api/v1/conversations/{conv_id}/chat/stream",
        headers=auth_header(manager_user["token"]),
        json={"message": "Quelle est la durée du préavis ?"},
    )
    assert res.status_code == 200
    body = res.text
    # D'abord le message de patience, puis l'erreur propre.
    assert "plus de temps que d'habitude" in body
    assert "chat_error" in body
    assert "timeout" in body
    assert "connexion à un service nécessaire a expiré" in body


async def test_dead_stream_keeps_partial_answer(
    client: AsyncClient, manager_user: dict, monkeypatch,
) -> None:
    conv_id = await _make_conversation(client, manager_user)

    async def dying_stream(self, *args, **kwargs):
        yield "Début de réponse."
        await asyncio.sleep(30)
        yield "jamais émis"

    _patch_timings(monkeypatch)
    monkeypatch.setattr(
        "app.services.conversation_orchestrator.prepare_conversation_context",
        _fast_prepare_context,
    )
    monkeypatch.setattr("app.rag.agent.RAGAgent.stream_generate", dying_stream)

    res = await client.post(
        f"/api/v1/conversations/{conv_id}/chat/stream",
        headers=auth_header(manager_user["token"]),
        json={"message": "Quelle est la durée du préavis ?"},
    )
    assert res.status_code == 200
    body = res.text
    # La partie déjà générée est servie…
    assert "Début de réponse." in body
    # …le message de patience a été émis pendant le silence…
    assert "plus de temps que d'habitude" in body
    # …le flux mort est annoté comme interrompu…
    assert "interrompue" in body
    # …et se termine proprement (messages persistés + ids renvoyés).
    assert "chat_done" in body
    assert "chat_error" not in body

    loaded = await client.get(
        f"/api/v1/conversations/{conv_id}", headers=auth_header(manager_user["token"])
    )
    answer = next(message for message in loaded.json()["messages"] if message["role"] == "assistant")
    assert answer["content"] == "Début de réponse."
    assert any("interrompue" in warning for warning in answer["search_details"]["warnings"])


async def test_slow_but_alive_stream_is_never_cut(
    client: AsyncClient, manager_user: dict, monkeypatch,
) -> None:
    """Un flux qui avance lentement mais régulièrement va au bout, sans coupure.

    Chaque token arrive après le seuil de patience (0,05 s) mais avant la
    limite d'inactivité (0,3 s) : un mur horaire global l'aurait coupé, la
    garde d'inactivité doit le laisser finir — avec un unique message de
    patience au passage.
    """
    conv_id = await _make_conversation(client, manager_user)

    async def slow_alive_stream(self, *args, **kwargs):
        for i in range(5):
            await asyncio.sleep(0.2)  # > patience (0,05) mais < inactivité (0,3)
            yield f"morceau-{i} "
        yield "FIN."

    _patch_timings(monkeypatch)
    monkeypatch.setattr(
        "app.services.conversation_orchestrator.prepare_conversation_context",
        _fast_prepare_context,
    )
    monkeypatch.setattr("app.rag.agent.RAGAgent.stream_generate", slow_alive_stream)

    res = await client.post(
        f"/api/v1/conversations/{conv_id}/chat/stream",
        headers=auth_header(manager_user["token"]),
        json={"message": "Quelle est la durée du préavis ?"},
    )
    assert res.status_code == 200
    body = res.text
    for i in range(5):
        assert f"morceau-{i}" in body
    assert "FIN." in body
    # Prévenu de la lenteur, mais jamais coupé.
    assert "plus de temps que d'habitude" in body
    assert "interrompue" not in body
    assert "chat_error" not in body
    assert "chat_done" in body


async def test_orchestrator_can_generate_without_forcing_a_document_search(
    client: AsyncClient, manager_user: dict, monkeypatch,
) -> None:
    conv_id = await _make_conversation(client, manager_user)

    async def generation_context(*args, **kwargs):
        # Longer than the former simulated global deadline (0.2 seconds).
        await asyncio.sleep(0.25)
        return PreparedConversation(
            results=[],
            reformulated="Rédiger à partir des faits fournis",
            trace=RagTrace(query_original="Rédige un mail", model="test-model"),
            documents=[],
            references=[],
            generate_without_sources=True,
        )

    async def generated(self, *args, **kwargs):
        yield "Mail rédigé à partir des faits fournis."

    _patch_timings(monkeypatch, slow=0.05, idle=10)
    monkeypatch.setattr(
        "app.services.conversation_orchestrator.prepare_conversation_context",
        generation_context,
    )
    monkeypatch.setattr("app.rag.agent.RAGAgent.stream_generate", generated)

    response = await client.post(
        f"/api/v1/conversations/{conv_id}/chat/stream",
        headers=auth_header(manager_user["token"]),
        json={"message": "Rédige un mail à partir de ces faits"},
    )

    assert "Mail rédigé à partir des faits fournis." in response.text
    assert "plus de temps que d'habitude" in response.text
    assert "chat_error" not in response.text
    assert "chat_done" in response.text
    assert "no_results" not in response.text


async def test_applied_case_delta_emits_case_file_update_event(
    client: AsyncClient, manager_user: dict, monkeypatch,
) -> None:
    conv_id = await _make_conversation(client, manager_user)
    case_file_id = str(uuid.uuid4())

    async def applied_context(*args, **kwargs):
        trace = RagTrace(query_original="Situation détaillée", model="test-model")
        trace.case_file_observation = {
            "mode": "applied",
            "case_file_id": case_file_id,
            "case_file_version": 2,
            "event_ids": [],
            "technical_errors": [],
            "application_result": {"applied": True, "version": 2},
        }
        return PreparedConversation(
            results=[],
            reformulated="Situation détaillée",
            trace=trace,
            documents=[],
            references=[],
            generate_without_sources=True,
        )

    async def generated(self, *args, **kwargs):
        yield "Réponse."

    _patch_timings(monkeypatch, slow=5, context=10, idle=10)
    monkeypatch.setattr(
        "app.services.conversation_orchestrator.prepare_conversation_context",
        applied_context,
    )
    monkeypatch.setattr("app.rag.agent.RAGAgent.stream_generate", generated)

    response = await client.post(
        f"/api/v1/conversations/{conv_id}/chat/stream",
        headers=auth_header(manager_user["token"]),
        json={"message": "Voici ma situation détaillée"},
    )

    assert "event: case_file_updated" in response.text
    assert f'"case_file_id": "{case_file_id}"' in response.text
    assert '"version": 2' in response.text


async def test_quota_incremented_even_if_trace_persist_fails(
    client: AsyncClient, manager_user: dict, monkeypatch,
) -> None:
    """Le décompte de quota ne doit pas dépendre de la persistance de la trace.

    Trace qualité et quota sont commités séparément : si RagTrace.to_dict()
    explose (best-effort), la question doit quand même être décomptée.
    """
    conv_id = await _make_conversation(client, manager_user)

    async def ok_stream(self, *args, **kwargs):
        yield "Réponse complète."

    def broken_to_dict(self):
        raise RuntimeError("trace corrompue (simulation)")

    _patch_timings(monkeypatch, slow=5, context=10, idle=10)
    monkeypatch.setattr(
        "app.services.conversation_orchestrator.prepare_conversation_context",
        _fast_prepare_context,
    )
    monkeypatch.setattr("app.rag.agent.RAGAgent.stream_generate", ok_stream)
    monkeypatch.setattr(RagTrace, "to_dict", broken_to_dict)

    before = await client.get(
        "/api/v1/billing/quota", headers=auth_header(manager_user["token"]),
    )
    assert before.status_code == 200

    res = await client.post(
        f"/api/v1/conversations/{conv_id}/chat/stream",
        headers=auth_header(manager_user["token"]),
        json={"message": "Quelle est la durée du préavis ?"},
    )
    assert res.status_code == 200
    assert "chat_done" in res.text  # la réponse est servie malgré la trace KO

    after = await client.get(
        "/api/v1/billing/quota", headers=auth_header(manager_user["token"]),
    )
    assert after.status_code == 200
    assert after.json()["used"] == before.json()["used"] + 1
