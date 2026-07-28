"""Garde-fous du chemin streaming (/chat/stream).

Principe (Vanessa, 28/07/2026) : ne JAMAIS couper une réponse qui avance,
même lentement — mieux vaut long et complet que rapide et tronqué. On ne
coupe que ce qui est réellement mort, et on prévient l'utilisateur quand
c'est plus lent que d'habitude au lieu de laisser un écran figé.

- RAG_SLOW_NOTICE : message de patience (« plus de temps que d'habitude… »)
  quand rien n'avance, réponse jamais coupée pour autant ;
- RAG_TIMEOUT_CONTEXT : borne globale de la préparation → chat_error propre ;
- RAG_TIMEOUT_STREAM_IDLE : inactivité du flux de génération, réarmée à
  chaque token. Un flux lent mais vivant va TOUJOURS au bout ; un flux mort
  est abandonné en conservant et annotant le déjà-émis, puis chat_done.
"""
from __future__ import annotations

import asyncio

from httpx import AsyncClient

from app.rag.agent import RagTrace
from app.rag.search import SearchResult
from tests.conftest import auth_header


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


async def _fast_prepare_context(self, *args, **kwargs):
    return [_fake_result()], "question reformulée", RagTrace(
        query_original="q", model="test-model",
    )


def _patch_timings(monkeypatch, *, slow=0.05, context=0.2, idle=0.3):
    monkeypatch.setattr("app.api.conversations.classify_intent", _passthrough_intent)
    monkeypatch.setattr("app.api.conversations.RAG_SLOW_NOTICE", slow)
    monkeypatch.setattr("app.api.conversations.RAG_TIMEOUT_CONTEXT", context)
    monkeypatch.setattr("app.api.conversations.RAG_TIMEOUT_STREAM_IDLE", idle)


async def test_context_timeout_yields_notice_then_clean_error(
    client: AsyncClient, manager_user: dict, monkeypatch,
) -> None:
    conv_id = await _make_conversation(client, manager_user)

    async def hanging_prepare_context(self, *args, **kwargs):
        await asyncio.sleep(30)

    _patch_timings(monkeypatch)
    monkeypatch.setattr(
        "app.rag.agent.RAGAgent.prepare_context", hanging_prepare_context,
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
    assert "trop de temps" in body


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
        "app.rag.agent.RAGAgent.prepare_context", _fast_prepare_context,
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
        "app.rag.agent.RAGAgent.prepare_context", _fast_prepare_context,
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
        "app.rag.agent.RAGAgent.prepare_context", _fast_prepare_context,
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
