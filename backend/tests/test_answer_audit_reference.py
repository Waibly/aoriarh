"""Full HTTP reference capture with isolated stores and simulated transports.

These tests assert technical contracts only. The separate review matrix is not
an answer validator. Set AORIARH_AUDIT_OUTPUT through scripts.audit_answers to
retain all requests, responses, events and database evidence privately.
"""

import base64
import copy
import json
import os
import socket
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    SparseVectorParams,
    VectorParams,
)
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.main import app
from app.models.account import Account
from app.models.case_file import CaseEntry, CaseEvent, CaseFile, CaseTask
from app.models.conversation import Message
from app.models.document import Document
from app.models.membership import Membership
from app.models.organisation import Organisation
from app.models.user import User
from app.rag import agent as agent_module
from app.rag.config import (
    EXPAND_MODEL,
    LLM_MODEL,
    LLM_REASONING_EFFORT,
    RERANK_MODEL,
)
from app.rag.qdrant_store import COLLECTION_NAME
from app.rag.reranker import VoyageReranker
from app.rag.search import HybridSearch
from app.services.conversation_service import ConversationService
from scripts.audit_answers import PROTOCOL, digest, parse_sse, write_json
from tests.conftest import test_session_factory as _session_factory

PROTOCOL_DATA = json.loads(PROTOCOL.read_text(encoding="utf-8"))
SCENARIOS = PROTOCOL_DATA["technical_scenarios"]
RAW_CHUNKS = ["  Sortie simulée originale\n", "<script>non exécuté</script>  \n"]


def identifier(name):
    return uuid.uuid5(uuid.NAMESPACE_URL, "aoriarh-offline-reference/" + name)


def row(value):
    return {column.name: getattr(value, column.name) for column in value.__table__.columns}


def json_value(value):
    def encode(item):
        if hasattr(item, "model_dump"):
            return item.model_dump(mode="json")
        if hasattr(item, "as_dict"):
            return item.as_dict()
        if isinstance(item, (date, uuid.UUID)):
            return str(item)
        raise TypeError(f"Unsupported archive value: {type(item).__name__}")

    return json.loads(json.dumps(value, default=encode, ensure_ascii=False))


def request(kind, name, question, **kwargs):
    return {
        "id": name,
        "kind": kind,
        "question": question,
        "depends_on": [],
        "fact_keys": [],
        "replaces_task_id": None,
        **kwargs,
    }


def planner_fixture(scenario, case):
    """Scripted model output for transport checks, never an expected legal answer."""
    if scenario["planner"] == "invalid":
        return "  {JSON inexécutable\n"
    entries = []
    requests = []
    if scenario["planner"] in {"legal", "two_legal"}:
        for index in range(2 if scenario["planner"] == "two_legal" else 1):
            requests.append(
                request(
                    "legal",
                    f"law_{index}",
                    case["question"],
                    use_organisation_convention=True,
                    search={
                        "needs_history": False,
                        "legal_topics": [],
                        "search_queries": [f"Recherche technique simulée {index}"],
                        "hypothesized_articles": [],
                        "source_hints": ["legislation"],
                        "jurisprudence": "optional",
                        "answer_intent": "factual_rule",
                        "missing_facts": [],
                        "chronology": None,
                    },
                )
            )
    else:
        requests.append(
            request(
                "answer",
                "answer",
                case["question"],
                task_type="drafting",
            )
        )
    if scenario["planner"] == "fact_revision":
        entries.append(
            {
                "operation": "revise",
                "target_entry_id": str(identifier("salary")),
                "entry_type": "fact",
                "key": "salary",
                "label": "Salaire mensuel brut",
                "value_text": "3 450 €",
                "valid_from": None,
                "valid_to": None,
                "source_kind": "user_message",
                "source_excerpt": "3 450 €",
                "source_document_id": None,
                "source_extraction_id": None,
                "numeric_value": {"number": "3450", "unit": "EUR/month"},
            }
        )
    return json.dumps(
        {
            "case_delta": {"entries": entries},
            "document_checks": [],
            "requests": requests,
        },
        ensure_ascii=False,
    )


class FixtureLLM:
    def __init__(self, raw, record, fault):
        self.raw, self.record, self.fault = raw, record, fault
        self.chat = SimpleNamespace(completions=self)
        self.options = {}

    def with_options(self, **kwargs):
        # The real planner disables transport retries; record its options too.
        child = copy.copy(self)
        child.options = json_value(kwargs)
        child.chat = SimpleNamespace(completions=child)
        return child

    async def create(self, **kwargs):
        call = {"request": copy.deepcopy(kwargs), "client_options": self.options}
        self.record["model_calls"].append(call)
        if not kwargs.get("stream"):
            call["raw_response"] = self.raw
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=self.raw, refusal=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            )

        async def stream():
            call["raw_chunks"] = []
            for text in RAW_CHUNKS:
                call["raw_chunks"].append(text)
                yield SimpleNamespace(
                    usage=None,
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=text))],
                )
            if self.fault == "stream":
                call["error"] = "simulated_stream_interruption"
                raise RuntimeError(call["error"])

        return stream()


@pytest.fixture
async def reference_environment(client, monkeypatch):
    """No application server startup, external database, API, email or storage."""

    def forbidden_network(*args, **kwargs):
        raise AssertionError("External network is forbidden in an offline reference")

    monkeypatch.setattr(socket.socket, "connect", forbidden_network)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden_network)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden_network)
    original_connect = Engine.connect

    def sqlite_only(engine, *args, **kwargs):
        if engine.dialect.name != "sqlite":
            raise AssertionError("An offline reference may only connect to isolated SQLite")
        return original_connect(engine, *args, **kwargs)

    monkeypatch.setattr(Engine, "connect", sqlite_only)
    monkeypatch.setattr(settings, "security_alerts_enabled", False)

    async with _session_factory() as db:
        user = User(
            id=identifier("user"),
            email="reference@example.test",
            full_name="Reference",
            role="user",
            profil_metier="drh",
        )
        db.add(user)
        await db.flush()
        account = Account(id=identifier("account"), name="Reference", owner_id=user.id, plan="vip")
        db.add(account)
        await db.flush()
        profile = PROTOCOL_DATA["profile"]
        org = Organisation(
            id=identifier("org"),
            name=profile["nom"],
            account_id=account.id,
            **{
                key: profile[key]
                for key in (
                    "taille",
                    "forme_juridique",
                    "convention_collective",
                    "secteur_activite",
                    "not_subject_to_ccn",
                )
            },
        )
        db.add(org)
        await db.flush()
        db.add(Membership(user_id=user.id, organisation_id=org.id, role_in_org="user"))
        await db.commit()
        app.dependency_overrides[get_current_user] = lambda: user
        yield SimpleNamespace(db=db, user=user, org=org)


@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
async def test_capture_http_reference(reference_environment, monkeypatch, scenario_id):
    env = reference_environment
    scenario = SCENARIOS[scenario_id]
    case = next(value for value in PROTOCOL_DATA["cases"] if value["id"] == scenario["case_id"])
    raw_plan = planner_fixture(scenario, case)
    history = list(case.get("history", []))
    if scenario.get("history_fixture") == "long_mail":
        history = [
            {"role": "user", "content": "Rédige le mail de demande de pièces à la paie."},
            {
                "role": "assistant",
                "content": (
                    "Bonjour,\nSalaire mensuel brut : 3 200 €.\n"
                    + "Détail du dossier à conserver.\n" * 140
                    + "Merci de transmettre les bulletins et de confirmer la nature de la prime.\n"
                ),
            },
        ]
    corpus = [
        {
            "organisation_id": "common",
            "source_type": "code_travail",
            "document_id": str(identifier("code")),
            "doc_name": "Code synthétique technique",
            "chunk_index": index,
            "text": f"Passage technique synthétique {index}, sans règle réelle.",
            "norme_niveau": 3,
            "norme_poids": 1.0,
            "article_nums": ["L1234-9"],
        }
        for index in range(2)
    ]
    # A foreign tenant's matching point tests the real access filter as well.
    corpus.append(
        {
            **corpus[0],
            "document_id": str(identifier("foreign-document")),
            "organisation_id": str(identifier("foreign-org")),
            "text": "Texte du tenant étranger.",
        }
    )
    inputs = {
        "case": case,
        "scenario": scenario,
        "profile": PROTOCOL_DATA["profile"],
        "history": history,
        "corpus": corpus,
        "raw_plan": raw_plan,
        "raw_chunks": RAW_CHUNKS,
    }
    record = {
        "case_id": scenario_id,
        "input_sha256": digest(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode()),
        "inputs": inputs,
        "runtime": {
            "reference_date": date.today().isoformat(),
            "planner_model": EXPAND_MODEL,
            "generation_model": LLM_MODEL,
            "reasoning_effort": LLM_REASONING_EFFORT,
            "embedding_model": settings.voyage_embedding_model,
            "rerank_model": RERANK_MODEL,
        },
        "mode": "offline_transport_fixtures",
        "model_calls": [],
        "retrieval_calls": [],
        "rerank_calls": [],
        "cost_events": [],
        "wire_chunks": [],
        "http_status": None,
        "answer": "",
        "event_names": [],
        "errors": [],
        "warnings": [],
        "branch_errors": [],
        "cost_usd": None,
        "provider_latency_ms": None,
    }
    vector_store = QdrantClient(":memory:")
    vector_store.create_collection(
        COLLECTION_NAME,
        vectors_config={"dense": VectorParams(size=2, distance=Distance.COSINE)},
        sparse_vectors_config={"sparse-bm25": SparseVectorParams()},
    )
    vector_store.upsert(
        COLLECTION_NAME,
        [
            PointStruct(
                id=index,
                vector={"dense": [1.0, 0.0], "sparse-bm25": {"indices": [0], "values": [1.0]}},
                payload=payload,
            )
            for index, payload in enumerate(corpus)
        ],
    )
    search = HybridSearch.__new__(HybridSearch)
    search.qdrant = vector_store

    async def dense(query, cost_ctx=None):
        record["retrieval_calls"].append({"operation": "dense_fixture", "query": query})
        return [1.0, 0.0]

    monkeypatch.setattr(search, "_encode_dense", dense)
    monkeypatch.setattr(
        search, "_encode_sparse_sync", lambda text: {"indices": [0], "values": [1.0]}
    )
    for operation in ("query_points", "scroll"):
        original = getattr(vector_store, operation)

        def observed(*args, _operation=operation, _original=original, **kwargs):
            call = {"operation": _operation, "request": json_value(kwargs)}
            record["retrieval_calls"].append(call)
            if scenario.get("fault") == "search" and _operation == "query_points":
                call["error"] = "simulated_search_outage"
                raise RuntimeError(call["error"])
            result = _original(*args, **kwargs)
            if _operation == "query_points":
                call["response"] = result.model_dump(mode="json")
            else:
                points, offset = result
                call["response"] = {
                    "points": [point.model_dump(mode="json") for point in points],
                    "offset": offset,
                }
            return result

        monkeypatch.setattr(vector_store, operation, observed)

    reranker = VoyageReranker()

    async def rerank(query, documents):
        response = {
            "data": [{"index": i, "relevance_score": 1.0 / (i + 1)} for i in range(len(documents))],
            "usage": {"total_tokens": 0},
        }
        record["rerank_calls"].append(
            {"query": query, "documents": documents, "response": response}
        )
        return response

    monkeypatch.setattr(reranker, "_call_api", rerank)
    monkeypatch.setattr(agent_module, "_search_engine", search)
    monkeypatch.setattr(agent_module, "get_reranker", lambda: reranker)
    monkeypatch.setattr(agent_module, "_llm", FixtureLLM(raw_plan, record, scenario.get("fault")))
    monkeypatch.setattr(
        "app.services.cost_tracker.cost_tracker.log_bg",
        lambda **kwargs: record["cost_events"].append(json_value(kwargs)),
    )
    started = time.perf_counter()

    async def observed_app(scope, receive, send):
        async def observed_send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                record["wire_chunks"].append(
                    {
                        "elapsed_ms": (time.perf_counter() - started) * 1000,
                        "body_base64": base64.b64encode(message["body"]).decode("ascii"),
                    }
                )
            await send(message)

        await app(scope, receive, observed_send)

    try:
        # Create via the actual service so the conversation's case file exists.
        conv = await ConversationService(env.db).create_conversation(
            env.org.id, env.user, "Reference"
        )
        for index, message in enumerate(history):
            env.db.add(
                Message(
                    id=identifier(f"history-{index}"),
                    conversation_id=conv.id,
                    role=message["role"],
                    content=message["content"],
                    created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=index),
                )
            )
        if scenario["planner"] == "fact_revision":
            case_file = await env.db.scalar(
                select(CaseFile).where(CaseFile.conversation_id == conv.id)
            )
            env.db.add(
                CaseEntry(
                    id=identifier("salary"),
                    case_file_id=case_file.id,
                    entry_type="fact",
                    key="salary",
                    label="Salaire mensuel brut",
                    value_text="3 200 €",
                    value_json={"number": "3200", "unit": "EUR/month"},
                    status="active",
                    source_kind="user_message",
                    created_by_user_id=env.user.id,
                )
            )
        env.db.add(
            Document(
                id=identifier("code"),
                name=corpus[0]["doc_name"],
                source_type="code_travail",
                storage_path="synthetic/no-storage",
                indexation_status="indexed",
            )
        )
        await env.db.commit()
        async with AsyncClient(
            transport=ASGITransport(app=observed_app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/api/v1/conversations/{conv.id}/chat/stream",
                json={"message": case["question"]},
            )
        record["http_status"] = response.status_code
        record["raw_response_base64"] = base64.b64encode(response.content).decode("ascii")
        record["events"] = events = parse_sse(response.text) if response.status_code == 200 else []
        record["event_names"] = [event["event"] for event in events]
        record["errors"] = [event["data"] for event in events if event["event"] == "chat_error"]
        record["warnings"] = [event["data"] for event in events if event["event"] == "chat_warning"]
        record["answer"] = "".join(
            event["data"]["content"] for event in events if event["event"] == "chat_delta"
        )
        record["database"] = {}
        for model in (Message, CaseFile, CaseEntry, CaseTask, CaseEvent):
            values = (await env.db.scalars(select(model))).all()
            # Reload after the endpoint's session committed case changes.
            for value in values:
                await env.db.refresh(value)
            record["database"][model.__tablename__] = json_value([row(value) for value in values])
        saved = [m for m in record["database"]["messages"] if m["role"] == "assistant"]
        if saved:
            execution = (saved[-1].get("rag_trace") or {}).get("case_file_observation", {})
            record["branch_errors"] = [
                {"action_id": branch["action_id"], "status": branch["status"]}
                for branch in (execution.get("execution") or {}).get("branches", [])
                if branch["status"].endswith("_error")
            ]
        assert response.status_code == 200, response.text
        assert record["model_calls"][0]["request"]["model"] == EXPAND_MODEL
        if scenario["planner"] == "invalid":
            assert record["errors"]
            assert not record["answer"]
            assert len(record["model_calls"]) == 1
            assert "chat_done" not in record["event_names"]
            assert any(raw_plan == event["data"].get("router_raw_response") for event in events)
            assert any(
                raw_plan == event["raw_planner_output"]
                for event in record["database"]["case_events"]
            )
        else:
            assert "chat_done" in record["event_names"], response.text
            assert record["answer"] == "".join(RAW_CHUNKS)
            assert saved[-1]["content"] == record["answer"]
            assert saved[-1]["rag_trace"]["case_file_observation"]["execution"]
            assert len(record["model_calls"]) == 2
            if scenario.get("fault") == "stream":
                assert any(event["event"] == "chat_warning" for event in events)
            if scenario.get("fault") == "search":
                # The orchestrator forwards branch failures to final generation;
                # retain this contract without endorsing the generated prose.
                assert record["branch_errors"]
                assert not record["rerank_calls"]
                details = next(e["data"] for e in events if e["event"] == "chat_search_details")
                assert details["warnings"]
                generation = record["model_calls"][-1]["request"]["messages"][1]["content"]
                assert '"status":"search_retrieval_error"' in generation
            if scenario.get("history_fixture") == "long_mail":
                assert (
                    history[-1]["content"]
                    in record["model_calls"][-1]["request"]["messages"][1]["content"]
                )
            if scenario["planner"] == "fact_revision":
                entries = record["database"]["case_entries"]
                assert any(
                    e["value_json"] == {"number": "3450", "unit": "EUR/month"}
                    and e["status"] == "active"
                    for e in entries
                )
        # The real search filters must exclude every point of the other tenant.
        for call in record["rerank_calls"]:
            assert all("Texte du tenant étranger" not in document for document in call["documents"])
    except BaseException as exc:
        record["capture_error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        record["elapsed_ms"] = (time.perf_counter() - started) * 1000
        vector_store.close()
        if output := os.environ.get("AORIARH_AUDIT_OUTPUT"):
            write_json(Path(output) / f"case-{scenario_id}.json", record)
