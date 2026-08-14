from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select

from app.api.admin_quality import _run_sandbox_pipeline
from app.models.ccn import CcnReference, OrganisationConvention
from app.models.conversation import Conversation, Message
from app.models.organisation import Organisation
from app.models.user import User
from app.rag.agent import RAGSource, RagTrace
from app.rag.search_plan import (
    PlannerCallResult,
    PlannerStatus,
    build_deterministic_search_plan,
)
from tests.conftest import test_session_factory as _test_session_factory


async def test_sandbox_generation_receives_same_context_as_chat(monkeypatch):
    import app.rag.agent as agent_module
    import app.rag.search_plan as search_plan_module

    async with _test_session_factory() as session:
        org = Organisation(
            name="ACME",
            convention_collective="Ancienne CCN",
            secteur_activite="Conseil",
        )
        session.add(org)
        await session.flush()
        session.add(CcnReference(idcc="1486", titre="Bureaux d'études techniques"))
        await session.flush()
        session.add(
            OrganisationConvention(
                organisation_id=org.id,
                idcc="1486",
                status="ready",
                use_custom=False,
            )
        )
        await session.commit()
        organisation_id = org.id

    trace = RagTrace(query_original="Et pour un cadre ?", low_confidence=True)
    result = MagicMock()
    source = RAGSource(
        document_id="fresh",
        document_name="Code du travail",
        source_type="code_travail",
        source_type_label="Code du travail",
        norme_niveau=2,
        excerpt="Passage utile",
        full_text="Texte complet",
        article_nums=["L1234-1"],
    )
    agent = MagicMock()
    agent.llm = object()
    agent.prepare_context = AsyncMock(return_value=([result], "Question autonome condensée", trace))
    agent.format_sources.return_value = [source]

    async def stream_generate(*args, **kwargs):
        yield "Réponse"

    agent.stream_generate = MagicMock(side_effect=stream_generate)
    monkeypatch.setattr(agent_module, "RAGAgent", lambda: agent)

    plan = build_deterministic_search_plan("Et pour un cadre ?", has_history=True)
    plan = replace(
        plan,
        standalone_question="Quel est le préavis pour un cadre ?",
        planner_status=PlannerStatus.OK,
    )
    monkeypatch.setattr(
        search_plan_module,
        "run_compact_search_planner",
        AsyncMock(return_value=PlannerCallResult(plan=plan)),
    )

    history = [{"role": "assistant", "content": "Réponse précédente"}]
    fresh_duplicate = {
        "document_id": "fresh",
        "article_nums": ["L1234-1"],
        "document_name": "Code du travail",
    }
    prior_source = {
        "document_id": "prior",
        "article_nums": ["L3121-1"],
        "document_name": "Convention collective",
    }

    async with _test_session_factory() as session:
        response = await _run_sandbox_pipeline(
            session,
            query="Et pour un cadre ?",
            organisation_id=organisation_id,
            history=history,
            skip_generation=False,
            cited_sources=["Convention collective"],
            carried_sources=[fresh_duplicate, prior_source],
            user_profile="responsable_rh",
            search_strategy="adaptive_shadow",
        )

    prepare_kwargs = agent.prepare_context.await_args.kwargs
    assert prepare_kwargs["history"] == history
    assert prepare_kwargs["cited_sources"] == ["Convention collective"]
    assert prepare_kwargs["org_idcc_list"] == ["1486"]
    assert prepare_kwargs["org_context"]["convention_collective"] == (
        "Bureaux d'études techniques (IDCC 1486)"
    )
    assert prepare_kwargs["org_context"]["profil_metier"] == "responsable_rh"
    assert prepare_kwargs["search_plan"] == plan

    generation_kwargs = agent.stream_generate.call_args.kwargs
    assert generation_kwargs["history"] == history
    assert generation_kwargs["low_confidence"] is True
    assert generation_kwargs["condensed_query"] == "Question autonome condensée"
    assert generation_kwargs["carried_sources"] == [prior_source]
    assert response.answer == "Réponse"
    assert response.rag_trace["perf_ms"]["generate"] >= 0
    assert response.rag_trace["search_plan_usage"]["execution"] == "adaptive_shadow"
    assert response.rag_trace["search_plan_usage"]["fallback_to_baseline"] is False


async def test_sandbox_replay_rebuilds_production_history_and_carried_sources(
    client, admin_user, monkeypatch
):
    from app.api import admin_quality

    now = datetime.now(UTC)
    async with _test_session_factory() as session:
        admin = (
            await session.execute(select(User).where(User.email == admin_user["email"]))
        ).scalar_one()
        admin.profil_metier = "juriste"
        org = Organisation(name="Organisation replay", account_id=admin.owned_account.id)
        session.add(org)
        await session.flush()
        conversation = Conversation(
            organisation_id=org.id,
            user_id=admin.id,
            title="Replay",
        )
        session.add(conversation)
        await session.flush()

        messages = []
        for index in range(4):
            messages.extend(
                [
                    Message(
                        conversation_id=conversation.id,
                        role="user",
                        content=f"Question {index}",
                        created_at=now - timedelta(minutes=20 - index * 2),
                    ),
                    Message(
                        conversation_id=conversation.id,
                        role="assistant",
                        content=f"Réponse {index}",
                        sources=[
                            {
                                "document_id": f"doc-{index}",
                                "document_name": f"Document {index}",
                                "article_nums": [f"L{index}"],
                            }
                        ],
                        created_at=now - timedelta(minutes=19 - index * 2),
                    ),
                ]
            )
        question = Message(
            conversation_id=conversation.id,
            role="user",
            content="Question à rejouer",
            created_at=now - timedelta(minutes=2),
        )
        answer = Message(
            conversation_id=conversation.id,
            role="assistant",
            content="Réponse à rejouer",
            created_at=now - timedelta(minutes=1),
        )
        session.add_all([*messages, question, answer])
        await session.commit()
        answer_id = answer.id

    mocked_pipeline = AsyncMock(
        return_value=admin_quality.SandboxRunResponse(
            answer="Nouvelle réponse",
            sources=[],
            rag_trace={},
            cost_usd=0,
            duration_ms=1,
        )
    )
    monkeypatch.setattr(admin_quality, "_run_sandbox_pipeline", mocked_pipeline)

    response = await client.post(
        f"/api/v1/admin/quality/sandbox/replay/{answer_id}",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 200
    kwargs = mocked_pipeline.await_args.kwargs
    assert kwargs["query"] == "Question à rejouer"
    assert [item["content"] for item in kwargs["history"]] == [
        "Question 1",
        "Réponse 1",
        "Question 2",
        "Réponse 2",
        "Question 3",
        "Réponse 3",
    ]
    assert kwargs["cited_sources"] == ["Document 1", "Document 2", "Document 3"]
    assert [source["document_id"] for source in kwargs["carried_sources"]] == [
        "doc-3",
        "doc-2",
    ]
    assert kwargs["user_profile"] == "juriste"
