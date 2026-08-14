"""Tests for the deterministic shadow search plan."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag.agent import RAGAgent
from app.rag.search_plan import (
    AnswerIntent,
    PlannerStatus,
    SearchMode,
    SourceRequirement,
    apply_compact_planner_payload,
    build_deterministic_search_plan,
    run_compact_search_planner,
)


def test_explicit_article_uses_direct_reference_route_without_llm():
    plan = build_deterministic_search_plan("Que prévoit l'article L. 1234-9 du Code du travail ?")

    assert plan.mode is SearchMode.EXACT_REFERENCE
    assert plan.explicit_identifiers["article_nums"] == ["L1234-9"]
    assert plan.legislation is SourceRequirement.REQUIRED
    assert plan.needs_llm_planner is False


def test_explicit_pourvoi_requires_jurisprudence():
    plan = build_deterministic_search_plan(
        "Que décide la Cour de cassation dans le pourvoi 22-18.875 ?"
    )

    assert plan.mode is SearchMode.EXACT_REFERENCE
    assert plan.explicit_identifiers["numero_pourvoi"] == ["22-18.875"]
    assert plan.jurisprudence is SourceRequirement.REQUIRED


def test_directed_ccn_query_uses_installed_idcc_and_keeps_legal_floor():
    plan = build_deterministic_search_plan(
        "Selon ma convention collective, quel est le préavis de démission ?",
        org_idcc_list=["0413"],
    )

    assert plan.mode is SearchMode.SOURCE_DIRECTED
    assert plan.ccn is SourceRequirement.REQUIRED
    assert plan.applicable_idccs == ["0413"]
    assert plan.legislation is SourceRequirement.REQUIRED
    assert "convention_collective_nationale" in plan.requested_source_types


def test_directed_internal_document_keeps_legislation_as_safety_floor():
    plan = build_deterministic_search_plan(
        "Que prévoit notre règlement intérieur sur les sanctions ?"
    )

    assert plan.mode is SearchMode.SOURCE_DIRECTED
    assert plan.internal_documents is SourceRequirement.REQUIRED
    assert plan.legislation is SourceRequirement.SAFETY_FLOOR


def test_news_defaults_to_30_days_without_llm_planner():
    plan = build_deterministic_search_plan(
        "Quelles sont les dernières actualités en droit social ?"
    )

    assert plan.mode is SearchMode.LEGAL_NEWS
    assert plan.answer_intent is AnswerIntent.LEGAL_NEWS
    assert plan.answer_format == "chronological_digest"
    assert plan.time_scope == {
        "kind": "rolling_days",
        "days": 30,
        "source": "default_news",
    }
    assert plan.needs_llm_planner is False


def test_news_preserves_explicit_rolling_period():
    plan = build_deterministic_search_plan("Quelles sont les actualités RH des 90 derniers jours ?")

    assert plan.time_scope == {
        "kind": "rolling_days",
        "days": 90,
        "source": "explicit",
    }


def test_anaphoric_follow_up_requires_condensation():
    plan = build_deterministic_search_plan(
        "Et pour un cadre ?",
        has_history=True,
        org_idcc_list=["0413"],
    )

    assert plan.mode is SearchMode.FOLLOW_UP
    assert plan.needs_condensation is True
    assert plan.needs_llm_planner is True
    assert plan.ccn is SourceRequirement.SAFETY_FLOOR


def test_short_autonomous_question_does_not_require_condensation():
    plan = build_deterministic_search_plan(
        "Quel est le montant du SMIC ?",
        has_history=True,
    )

    assert plan.mode is SearchMode.STANDARD
    assert plan.needs_condensation is False
    assert plan.answer_intent is AnswerIntent.FACTUAL_RULE


def test_explicit_calculation_is_not_confused_with_a_factual_amount():
    plan = build_deterministic_search_plan(
        "Comment calculer l'indemnité de licenciement avec 8 ans d'ancienneté ?"
    )

    assert plan.answer_intent is AnswerIntent.CALCULATION
    assert plan.answer_format == "formula_then_application"
    assert plan.query_budget == 2


def test_simple_question_limits_planner_to_one_additional_query():
    plan = build_deterministic_search_plan(
        "Un employeur peut-il refuser une demande de congés payés ?"
    )
    enriched = apply_compact_planner_payload(
        plan,
        _valid_payload(
            search_queries=[
                "refus congés payés fixation dates employeur",
                "ordre départs congés payés conditions",
            ]
        ),
    )

    assert plan.query_budget == 1
    assert enriched.search_queries == ["refus congés payés fixation dates employeur"]


def test_bare_legal_source_mentions_do_not_create_source_directed_routes():
    queries = [
        "La convention de forfait doit-elle être écrite ?",
        "Le contrat de travail peut-il prévoir une durée plus longue ?",
        "Une convention collective est-elle obligatoire ?",
    ]

    for query in queries:
        plan = build_deterministic_search_plan(query)
        assert plan.mode is SearchMode.STANDARD, query
        assert plan.requested_source_types == [], query


def test_current_relevance_expression_is_not_misclassified_as_legal_news():
    plan = build_deterministic_search_plan(
        "Cette ancienne règle est-elle toujours d'actualité en droit du travail ?"
    )

    assert plan.mode is SearchMode.STANDARD
    assert plan.answer_intent is AnswerIntent.YES_NO


def test_quoi_de_neuf_is_a_legal_news_request():
    plan = build_deterministic_search_plan("Quoi de neuf en droit social ?")

    assert plan.mode is SearchMode.LEGAL_NEWS
    assert plan.time_scope and plan.time_scope["days"] == 30


def test_ordinary_30_day_legal_deadline_is_not_a_news_time_scope():
    plan = build_deterministic_search_plan("Le délai de consultation du CSE est-il de 30 jours ?")

    assert plan.time_scope is None


def test_explicit_year_is_preserved_for_a_standard_question():
    plan = build_deterministic_search_plan("Quel était le montant du SMIC en 2025 ?")

    assert plan.time_scope == {
        "kind": "calendar_year",
        "year": 2025,
        "source": "explicit",
    }


def test_jurisprudence_news_requires_the_jurisprudence_branch():
    plan = build_deterministic_search_plan(
        "Quelles sont les dernières actualités de jurisprudence sociale ?"
    )

    assert plan.mode is SearchMode.LEGAL_NEWS
    assert plan.jurisprudence is SourceRequirement.REQUIRED


def test_not_subject_to_ccn_overrides_stale_idcc_and_warns_if_requested():
    plan = build_deterministic_search_plan(
        "Selon ma convention collective, quel préavis s'applique ?",
        org_idcc_list=["0413"],
        not_subject_to_ccn=True,
    )

    assert plan.ccn is SourceRequirement.DISABLED
    assert plan.applicable_idccs == []
    assert "ccn_requested_but_organisation_not_subject" in plan.warnings


def test_plan_is_json_serializable():
    plan = build_deterministic_search_plan(
        "Comment calculer l'indemnité de licenciement ?",
        org_idcc_list=["1486"],
    )

    encoded = json.dumps(plan.to_dict())
    assert "deterministic-shadow-v1" in encoded
    assert plan.answer_intent is AnswerIntent.CALCULATION


def _mock_llm_response(content: str, *, prompt_tokens: int = 0, output_tokens: int = 0):
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.usage.prompt_tokens = prompt_tokens
    response.usage.completion_tokens = output_tokens
    return response


def _valid_payload(**overrides):
    payload = {
        "standalone_question": "Quelle est la durée du préavis pour un cadre ?",
        "legal_topics": ["préavis", "cadre"],
        "search_queries": ["durée préavis cadre rupture contrat"],
        "hypothesized_articles": [{"reference": "L. 1234-1", "confidence": "medium"}],
        "source_hints": ["legislation", "ccn"],
        "jurisprudence": "optional",
        "answer_intent": "factual_rule",
        "missing_facts": ["ancienneté du salarié"],
    }
    payload.update(overrides)
    return payload


def test_compact_payload_can_only_rewrite_an_anaphoric_follow_up():
    follow_up = build_deterministic_search_plan("Et pour un cadre ?", has_history=True)
    enriched = apply_compact_planner_payload(follow_up, _valid_payload())
    assert enriched.standalone_question == ("Quelle est la durée du préavis pour un cadre ?")
    assert enriched.planner_status is PlannerStatus.OK

    autonomous = build_deterministic_search_plan("Quel préavis pour un cadre ?")
    autonomous_enriched = apply_compact_planner_payload(
        autonomous,
        _valid_payload(standalone_question="Question silencieusement modifiée"),
    )
    assert autonomous_enriched.standalone_question == autonomous.query_original


def test_hypothesized_articles_are_canonical_limited_and_separate_from_explicit():
    plan = build_deterministic_search_plan("Comment gérer cette rupture ?")
    payload = _valid_payload(
        hypothesized_articles=[
            {"reference": "L. 1234-1", "confidence": "medium"},
            {"reference": "article R1234-2", "confidence": "low"},
            {"reference": "article imaginaire", "confidence": "low"},
            {"reference": "Cass. soc. 22-18.875", "confidence": "medium"},
        ]
    )

    enriched = apply_compact_planner_payload(plan, payload)

    assert [item.reference for item in enriched.hypothesized_articles] == [
        "L1234-1",
        "R1234-2",
    ]


@pytest.mark.asyncio
async def test_deterministic_route_does_not_call_the_llm():
    plan = build_deterministic_search_plan("Que dit l'article L.1234-9 ?")
    llm = MagicMock()
    llm.chat.completions.create = AsyncMock()

    result = await run_compact_search_planner(
        plan,
        llm=llm,
        model="test-model",
    )

    assert result.plan.planner_status is PlannerStatus.NOT_NEEDED
    llm.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_compact_planner_returns_validated_plan_and_usage():
    plan = build_deterministic_search_plan(
        "Et pour un cadre ?", has_history=True, org_idcc_list=["1486"]
    )
    llm = MagicMock()
    llm.chat.completions.create = AsyncMock(
        return_value=_mock_llm_response(
            json.dumps(_valid_payload()),
            prompt_tokens=321,
            output_tokens=87,
        )
    )

    result = await run_compact_search_planner(
        plan,
        llm=llm,
        model="test-model",
        history=[
            {"role": "user", "content": "Quel préavis pour un employé ?"},
            {"role": "assistant", "content": "Réponse antérieure"},
        ],
        org_context={"convention_collective": "Syntec (IDCC 1486)"},
    )

    assert result.plan.planner_status is PlannerStatus.OK
    assert result.plan.search_queries == ["durée préavis cadre rupture contrat"]
    assert result.prompt_tokens == 321
    assert result.completion_tokens == 87
    call = llm.chat.completions.create.call_args.kwargs
    assert call["response_format"] == {"type": "json_object"}
    assert call["reasoning_effort"] == "minimal"


@pytest.mark.asyncio
async def test_invalid_json_falls_back_without_raising_or_changing_constraints():
    plan = build_deterministic_search_plan(
        "Selon ma convention collective, quel préavis ?",
        org_idcc_list=["1486"],
    )
    llm = MagicMock()
    llm.chat.completions.create = AsyncMock(return_value=_mock_llm_response("pas du json"))

    result = await run_compact_search_planner(
        plan,
        llm=llm,
        model="test-model",
    )

    assert result.plan.planner_status is PlannerStatus.FALLBACK
    assert result.plan.ccn is SourceRequirement.REQUIRED
    assert result.plan.applicable_idccs == ["1486"]
    assert "planner_invalid_json" in result.plan.warnings


@pytest.mark.asyncio
async def test_invalid_planner_enums_fall_back_instead_of_weakening_the_plan():
    plan = build_deterministic_search_plan(
        "Selon ma convention collective, quel préavis ?",
        org_idcc_list=["1486"],
    )
    llm = MagicMock()
    llm.chat.completions.create = AsyncMock(
        return_value=_mock_llm_response(
            json.dumps(
                _valid_payload(
                    source_hints=["other_client_database"],
                    jurisprudence="disabled",
                )
            )
        )
    )

    result = await run_compact_search_planner(
        plan,
        llm=llm,
        model="test-model",
    )

    assert result.plan.planner_status is PlannerStatus.FALLBACK
    assert result.plan.legislation is SourceRequirement.REQUIRED
    assert result.plan.ccn is SourceRequirement.REQUIRED


@pytest.mark.asyncio
async def test_prepare_context_records_deterministic_plan_without_extra_llm_call():
    with patch("app.rag.agent._search_engine"), patch("app.rag.agent.get_reranker"):
        agent = RAGAgent()
    agent.llm = MagicMock()
    agent.llm.chat.completions.create = AsyncMock(
        return_value=_mock_llm_response("1. durée préavis démission")
    )
    agent.search_engine = MagicMock()
    agent.search_engine.search = AsyncMock(return_value=[])
    agent.reranker = MagicMock()
    agent.reranker.rerank = AsyncMock(return_value=[])

    _results, _reformulated, trace = await agent.prepare_context(
        "Quel est le préavis de démission ?",
        "org-1",
        org_idcc_list=["1486"],
    )

    # Baseline unchanged: expansion + legal anchor, no compact planner call.
    assert agent.llm.chat.completions.create.call_count == 2
    assert trace.search_plan is not None
    assert trace.search_plan["mode"] == "standard"
    assert trace.search_plan["planner_status"] == "pending"
    assert trace.search_plan["applicable_idccs"] == ["1486"]


@pytest.mark.asyncio
async def test_adaptive_search_uses_queries_but_never_guessed_article_identifiers():
    plan = build_deterministic_search_plan(
        "Quel préavis pour un cadre ?",
        org_idcc_list=["1486"],
    )
    plan = apply_compact_planner_payload(
        plan,
        _valid_payload(
            legal_topics=["préavis de démission", "cadres"],
            search_queries=["préavis démission cadre Syntec"],
            hypothesized_articles=[{"reference": "L.1237-19", "confidence": "low"}],
        ),
    )
    agent = RAGAgent.__new__(RAGAgent)
    agent._run_variant_searches = AsyncMock(return_value=[])

    _pool, variants = await agent._search_with_plan(
        plan,
        plan.standalone_question,
        "org-1",
        org_idcc_list=["1486"],
    )

    assert variants == [
        "Quel préavis pour un cadre ?",
        "préavis démission cadre Syntec",
    ]
    call = agent._run_variant_searches.await_args
    assert call.args[1] == "préavis de démission cadres"
    assert "L1237-19" not in call.args[1]
    assert call.kwargs["apply_legislation_floor"] is True


@pytest.mark.asyncio
async def test_adaptive_prepare_reuses_follow_up_plan_without_condense_or_expansion():
    plan = build_deterministic_search_plan(
        "Et pour un cadre ?",
        has_history=True,
        org_idcc_list=["1486"],
    )
    plan = apply_compact_planner_payload(plan, _valid_payload())

    with patch("app.rag.agent._search_engine"), patch("app.rag.agent.get_reranker"):
        agent = RAGAgent()
    agent._condense_question = AsyncMock()
    agent._search_with_expansion = AsyncMock()
    agent._search_with_plan = AsyncMock(return_value=([], [plan.standalone_question]))
    agent.reranker = MagicMock()
    agent.reranker.rerank = AsyncMock(return_value=[])

    _results, reformulated, trace = await agent.prepare_context(
        "Et pour un cadre ?",
        "org-1",
        history=[{"role": "user", "content": "Quel préavis pour un non-cadre ?"}],
        org_idcc_list=["1486"],
        search_plan=plan,
    )

    agent._condense_question.assert_not_called()
    agent._search_with_expansion.assert_not_called()
    agent._search_with_plan.assert_awaited_once()
    assert reformulated == plan.standalone_question
    assert trace.query_condensed == plan.standalone_question
    assert trace.search_plan["planner_status"] == "ok"
