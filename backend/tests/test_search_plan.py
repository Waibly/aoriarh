"""Tests for the adaptive search plan."""

from __future__ import annotations

import datetime
import json
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag.agent import RAGAgent
from app.rag.search import SearchResult
from app.rag.search_plan import (
    AnswerIntent,
    PlannerCallResult,
    PlannerStatus,
    SearchMode,
    SourceRequirement,
    apply_compact_planner_payload,
    build_deterministic_search_plan,
    needs_interpretive_sources,
    run_compact_search_planner,
)


def _search_result(
    document_id: str,
    chunk_index: int,
    *,
    article_nums: list[str] | None = None,
    source_type: str = "code_travail",
) -> SearchResult:
    return SearchResult(
        text=f"Texte {document_id} {chunk_index}",
        doc_name="Document test",
        document_id=document_id,
        source_type=source_type,
        norme_niveau=2,
        norme_poids=0.9,
        chunk_index=chunk_index,
        score=0.5,
        article_nums=article_nums,
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


def test_payroll_recovery_searches_operational_rule_and_its_limits():
    plan = build_deterministic_search_plan(
        "Récupérer huit mois de trop-perçu d'un coup sur la prochaine paie"
    )

    assert plan.answer_intent is AnswerIntent.PROCEDURE
    assert plan.answer_format == "numbered_steps"
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


def test_interpretive_legal_family_gets_jurisprudence_and_two_distinct_angles():
    plan = build_deterministic_search_plan(
        "Quelle durée de garantie d'emploi est prévue par la convention collective ?",
        org_idcc_list=["1486"],
    )
    enriched = apply_compact_planner_payload(
        plan,
        _valid_payload(
            search_queries=[
                "garantie emploi absence maladie",
                "conditions rupture désorganisation remplacement définitif",
            ],
            jurisprudence="optional",
        ),
    )

    assert needs_interpretive_sources(plan.query_original) is True
    # A passive source mention must not narrow retrieval. Full-corpus recall is
    # safer here; explicit wording such as "selon ma CCN" remains directed.
    assert plan.mode is SearchMode.STANDARD
    assert plan.requested_source_types == []
    assert plan.jurisprudence is SourceRequirement.REQUIRED
    assert plan.query_budget == 2
    assert len(enriched.search_queries) == 2
    # The LLM cannot weaken the deterministic safety floor.
    assert enriched.jurisprudence is SourceRequirement.REQUIRED
    assert enriched.planner_jurisprudence is SourceRequirement.OPTIONAL


def test_simple_numeric_rule_does_not_pay_for_interpretive_branch():
    plan = build_deterministic_search_plan("Quel est le montant actuel du SMIC ?")

    assert needs_interpretive_sources(plan.query_original) is False
    assert plan.jurisprudence is SourceRequirement.OPTIONAL
    assert plan.query_budget == 1


def test_explicit_multi_issue_case_gets_four_complementary_searches():
    question = """Une entreprise de 180 salariés envisage deux procédures :
- peut-elle utiliser les preuves issues de la messagerie professionnelle ?
- quelles règles s'appliquent au licenciement du salarié protégé ?
- quand et sur quoi faut-il consulter le CSE ?
- le licenciement économique de 12 salariés sur 30 jours impose-t-il un PSE ?
- quelles sont les conséquences contentieuses de ces procédures ?"""
    plan = build_deterministic_search_plan(question)
    enriched = apply_compact_planner_payload(
        plan,
        _valid_payload(
            legal_topics=[
                "preuve issue de la messagerie professionnelle",
                "licenciement d'un salarié protégé",
                "consultation du CSE",
                "plan de sauvegarde de l'emploi",
                "nullité et réintégration",
            ],
            search_queries=[
                "preuve numérique information salariés proportionnalité",
                "licenciement salarié protégé autorisation inspection travail",
                "consultation CSE licenciement individuel et collectif",
                "PSE douze licenciements entreprise 180 salariés nullité",
            ],
        ),
    )

    assert plan.query_budget == 4
    assert "explicit_multi_issue_question" in plan.reasons
    assert len(enriched.legal_topics) == 5
    assert len(enriched.search_queries) == 4


def test_long_unstructured_question_keeps_existing_two_query_budget():
    plan = build_deterministic_search_plan(
        "Une entreprise souhaite savoir comment organiser une procédure "
        "de licenciement après plusieurs incidents successifs tout en tenant "
        "compte du contexte de travail, des échanges déjà intervenus avec le "
        "salarié et des éventuelles difficultés qui pourraient être soulevées."
    )

    assert plan.query_budget == 2
    assert "explicit_multi_issue_question" not in plan.reasons


def test_bulleted_facts_do_not_trigger_multi_issue_searches():
    plan = build_deterministic_search_plan(
        "Calculez l'indemnité avec ces données :\n"
        "- salaire mensuel : 3 000 euros\n"
        "- ancienneté : 8 ans\n"
        "- temps de travail : temps plein"
    )

    assert plan.query_budget < 4
    assert "explicit_multi_issue_question" not in plan.reasons


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
    assert "adaptive-v1" in encoded
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


def test_planner_answer_intent_updates_generation_format():
    plan = build_deterministic_search_plan("Comment gérer cette situation ?")
    enriched = apply_compact_planner_payload(
        plan,
        _valid_payload(answer_intent="comparison"),
    )

    assert enriched.planner_answer_intent is AnswerIntent.COMPARISON
    assert enriched.answer_format == "comparison_table"


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
            source_hints=["legislation"],
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
async def test_adaptive_search_executes_all_four_multi_issue_queries():
    question = """Analysez les points suivants :
- la preuve tirée de la messagerie professionnelle ;
- le licenciement du salarié protégé ;
- les consultations du CSE ;
- l'obligation d'établir un PSE ;
- les conséquences contentieuses."""
    plan = build_deterministic_search_plan(question)
    queries = [
        "preuve numérique loyauté proportionnalité",
        "licenciement salarié protégé autorisation",
        "consultations CSE procédures concomitantes",
        "PSE licenciement collectif nullité réintégration",
    ]
    plan = apply_compact_planner_payload(
        plan,
        _valid_payload(search_queries=queries),
    )
    agent = RAGAgent.__new__(RAGAgent)
    agent._run_variant_searches = AsyncMock(return_value=[])
    agent.search_engine = MagicMock()
    agent.search_engine.search = AsyncMock(return_value=[])
    agent._org_id = "org-1"
    agent._user_id = None
    agent._conversation_id = None
    agent._is_replay = True

    _pool, variants = await agent._search_with_plan(
        plan,
        plan.standalone_question,
        "org-1",
    )

    assert variants == [question, *queries]
    agent._run_variant_searches.assert_awaited_once()


@pytest.mark.asyncio
async def test_exact_reference_uses_direct_lookup_plus_one_general_safety_search():
    plan = build_deterministic_search_plan(
        "Que prévoit l'article L.1234-9 du Code du travail ?",
        org_idcc_list=["1486"],
    )
    direct = _search_result(
        "code-direct",
        0,
        article_nums=["L1234-9"],
    )
    safety = _search_result("related", 1, source_type="arret_cour_cassation")
    agent = RAGAgent.__new__(RAGAgent)
    agent.search_engine = MagicMock()
    agent.search_engine.qdrant = MagicMock()
    agent.search_engine.search = AsyncMock(return_value=[direct, safety])
    agent._org_id = "org-1"
    agent._user_id = None
    agent._conversation_id = None
    agent._is_replay = True

    with patch(
        "app.rag.agent.fetch_by_identifiers",
        AsyncMock(return_value=[direct]),
    ) as fetch:
        pool, variants = await agent._search_with_plan(
            plan,
            plan.standalone_question,
            "org-1",
            org_idcc_list=["1486"],
        )

    fetch.assert_awaited_once()
    agent.search_engine.search.assert_awaited_once()
    assert variants == [plan.query_original]
    assert [(result.document_id, result.chunk_index) for result in pool] == [
        ("code-direct", 0),
        ("related", 1),
    ]
    assert agent._plan_search_diagnostics == {
        "direct_reference_candidate_chunks": 1,
        "general_safety_candidate_chunks": 2,
    }


@pytest.mark.asyncio
async def test_legal_news_adds_dated_candidates_without_dropping_broad_fallback():
    plan = build_deterministic_search_plan(
        "Quelles sont les dernières actualités en droit social ?"
    )
    broad = _search_result("broad", 0, source_type="code_travail")
    dated = _search_result("dated", 0, source_type="loi")
    agent = RAGAgent.__new__(RAGAgent)
    agent._run_variant_searches = AsyncMock(return_value=[broad])
    agent.search_engine = MagicMock()
    agent.search_engine.search = AsyncMock(return_value=[dated])
    agent._org_id = "org-1"
    agent._user_id = None
    agent._conversation_id = None
    agent._is_replay = True

    pool, _variants = await agent._search_with_plan(
        plan,
        plan.standalone_question,
        "org-1",
    )

    assert [(result.document_id, result.chunk_index) for result in pool] == [
        ("broad", 0),
        ("dated", 0),
    ]
    chronology_call = agent.search_engine.search.await_args
    assert chronology_call.kwargs["date_from"] is not None
    assert chronology_call.kwargs["date_to"] is not None
    assert (chronology_call.kwargs["date_to"] - chronology_call.kwargs["date_from"]).days == 30
    assert agent._plan_search_diagnostics["priority_branches"] == [
        {"kind": "chronology", "candidate_chunks": 1, "added_chunks": 1}
    ]


def test_legal_news_time_guard_keeps_current_sources_and_undated_context():
    plan = build_deterministic_search_plan(
        "Quelles sont les dernières actualités en droit social ?"
    )
    today = datetime.date.today()
    recent = _search_result("recent", 0, source_type="arret_cour_appel")
    recent.date_decision = today.isoformat()
    older_recent = _search_result("older-recent", 0, source_type="loi")
    older_recent.content_date = f"{today - datetime.timedelta(days=20)}T00:00:00Z"
    old = _search_result("old", 0, source_type="arret_cour_cassation")
    old.date_decision = (today - datetime.timedelta(days=365)).isoformat()
    undated = [_search_result(f"context-{index}", 0) for index in range(3)]

    kept, diagnostics = RAGAgent._apply_news_time_scope(
        [old, *undated, older_recent, recent],
        plan,
    )

    assert [result.document_id for result in kept] == [
        "older-recent",
        "recent",
        "context-0",
        "context-1",
    ]
    assert diagnostics == {
        "in_period": 2,
        "undated": 3,
        "out_of_period": 1,
        "status": "applied",
        "undated_context_kept": 2,
    }
    assert [result.document_id for result in RAGAgent._sort_news_results(kept, plan)] == [
        "recent",
        "older-recent",
        "context-0",
        "context-1",
    ]


def test_legal_news_time_guard_preserves_broad_fallback_on_corpus_gap():
    plan = build_deterministic_search_plan(
        "Quelles sont les dernières actualités en droit social ?"
    )
    old = _search_result("old", 0, source_type="arret_cour_cassation")
    old.date_decision = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    undated = _search_result("context", 0)

    kept, diagnostics = RAGAgent._apply_news_time_scope([old, undated], plan)

    assert kept == [old, undated]
    assert diagnostics["status"] == "broad_fallback_no_in_period_match"


def test_temporal_rule_priority_prefers_applicable_regime_without_deleting_history():
    current = _search_result("boss", 69, source_type="boss")
    current.text = (
        "Evaluation applicable à compter du 1er février 2025 : "
        "le forfait est fixé par le tableau suivant."
    )
    current.score = 0.72
    expired = _search_result("boss", 68, source_type="boss")
    expired.text = "Evaluation applicable jusqu'au 31 janvier 2025 : ancien tableau récapitulatif."
    expired.score = 0.79
    neutral = _search_result("boss", 30, source_type="boss")
    neutral.text = "La valeur réelle comprend l'assurance et l'entretien."
    neutral.score = 0.80

    ranked, diagnostics = RAGAgent._apply_temporal_rule_priority(
        [neutral, expired, current],
        target_date=datetime.date(2026, 8, 15),
    )

    assert [result.chunk_index for result in ranked] == [69, 30, 68]
    assert expired in ranked
    assert diagnostics == {
        "classified": 2,
        "applicable": 1,
        "expired": 1,
        "future": 0,
    }


def test_temporal_rule_priority_does_not_reclassify_case_law_facts():
    ruling = _search_result(
        "ruling",
        0,
        source_type="arret_cour_cassation",
    )
    ruling.text = "Le contrat avait été conclu avant le 1er février 2025."
    ruling.score = 0.76

    ranked, diagnostics = RAGAgent._apply_temporal_rule_priority(
        [ruling],
        target_date=datetime.date(2026, 8, 15),
    )

    assert ranked == [ruling]
    assert ruling.score == 0.76
    assert diagnostics["classified"] == 0


@pytest.mark.asyncio
async def test_source_directed_plan_preserves_filtered_results_and_bounds_fallback():
    plan = build_deterministic_search_plan(
        "Selon ma convention collective, quel préavis pour un cadre ?",
        org_idcc_list=["1486"],
    )
    plan = apply_compact_planner_payload(
        plan,
        _valid_payload(
            legal_topics=[
                "préavis de démission",
                "cadres",
                "convention collective Syntec (IDCC 1486)",
            ],
            search_queries=["préavis démission cadre Syntec IDCC 1486"],
            hypothesized_articles=[],
            source_hints=["ccn", "legislation", "jurisprudence"],
            jurisprudence="optional",
        ),
    )
    ccn_1 = _search_result(
        "ccn-1",
        0,
        source_type="convention_collective_nationale",
    )
    ccn_2 = _search_result("ccn-1", 1, source_type="accord_branche")
    duplicate = _search_result(
        "ccn-1",
        1,
        source_type="code_travail",
    )
    code_1 = _search_result("code-1", 0, source_type="code_travail")
    code_2 = _search_result("code-2", 0, source_type="code_securite_sociale")

    agent = RAGAgent.__new__(RAGAgent)
    agent._run_variant_searches = AsyncMock(return_value=[ccn_1, ccn_2])
    agent.search_engine = MagicMock()
    agent.search_engine.search = AsyncMock(return_value=[duplicate, code_1, code_2])
    agent._org_id = "org-1"
    agent._user_id = None
    agent._conversation_id = None
    agent._is_replay = True

    pool, _variants = await agent._search_with_plan(
        plan,
        plan.standalone_question,
        "org-1",
        org_idcc_list=["1486"],
    )

    assert [(result.document_id, result.chunk_index) for result in pool] == [
        ("ccn-1", 0),
        ("ccn-1", 1),
        ("code-1", 0),
        ("code-2", 0),
    ]
    agent._run_variant_searches.assert_awaited_once()
    assert agent._run_variant_searches.await_args.kwargs["apply_legislation_floor"] is False
    complement_call = agent.search_engine.search.await_args
    assert agent.search_engine.search.await_count == 1
    assert complement_call.args[0] == "préavis de démission cadres"
    assert complement_call.kwargs["top_k"] == 5
    assert "code_travail" in complement_call.kwargs["source_type_filter"]
    assert "loi" in complement_call.kwargs["source_type_filter"]
    assert "convention_oit" in complement_call.kwargs["source_type_filter"]
    assert "boss" not in complement_call.kwargs["source_type_filter"]
    assert "arret_cour_cassation" not in complement_call.kwargs["source_type_filter"]
    assert agent._plan_search_diagnostics == {
        "directed_primary_source_types": [
            "convention_collective_nationale",
            "accord_branche",
        ],
        "complement_query": "préavis de démission cadres",
        "complement_branches": [
            {
                "kind": "legislation",
                "candidate_chunks": 3,
                "added_chunks": 2,
            }
        ],
    }


@pytest.mark.asyncio
async def test_standard_plan_adds_ccn_priority_candidates_without_narrowing_main_search():
    plan = build_deterministic_search_plan(
        "Quel préavis s'applique à un cadre ?",
        org_idcc_list=["1486"],
    )
    plan = apply_compact_planner_payload(
        plan,
        _valid_payload(
            legal_topics=["préavis", "cadres"],
            search_queries=["durée préavis cadre"],
            hypothesized_articles=[],
            source_hints=["ccn", "legislation", "jurisprudence"],
            jurisprudence="optional",
        ),
    )
    code = _search_result("code-1", 0, source_type="code_travail")
    ccn = _search_result(
        "ccn-1",
        9,
        article_nums=["9.1"],
        source_type="convention_collective_nationale",
    )
    agent = RAGAgent.__new__(RAGAgent)
    agent._run_variant_searches = AsyncMock(return_value=[code])
    agent.search_engine = MagicMock()
    agent.search_engine.search = AsyncMock(return_value=[ccn])
    agent._org_id = "org-1"
    agent._user_id = None
    agent._conversation_id = None
    agent._is_replay = True

    pool, _variants = await agent._search_with_plan(
        plan,
        plan.standalone_question,
        "org-1",
        org_idcc_list=["1486"],
    )

    assert [(result.document_id, result.chunk_index) for result in pool] == [
        ("code-1", 0),
        ("ccn-1", 9),
    ]
    agent._run_variant_searches.assert_awaited_once()
    assert agent._run_variant_searches.await_args.kwargs["source_type_filter"] is None
    priority_call = agent.search_engine.search.await_args
    assert priority_call.kwargs["top_k"] == 8
    assert set(priority_call.kwargs["source_type_filter"]) == {
        "convention_collective_nationale",
        "accord_branche",
    }
    assert agent._plan_search_diagnostics == {
        "priority_branches": [{"kind": "ccn", "candidate_chunks": 1, "added_chunks": 1}]
    }


@pytest.mark.parametrize(
    ("question", "planner_jurisprudence"),
    [
        ("Selon le Code du travail, quel préavis pour un cadre ?", "required"),
        (
            "Selon le Code du travail, quelle garantie d'emploi s'applique "
            "en cas d'absence maladie ?",
            "optional",
        ),
    ],
)
@pytest.mark.asyncio
async def test_source_directed_plan_adds_jurisprudence_when_either_layer_requires_it(
    question,
    planner_jurisprudence,
):
    plan = build_deterministic_search_plan(
        question,
        org_idcc_list=["1486"],
    )
    plan = apply_compact_planner_payload(
        plan,
        _valid_payload(
            legal_topics=["validité du préavis", "rupture du contrat"],
            search_queries=["validité préavis rupture contrat"],
            hypothesized_articles=[],
            source_hints=["legislation", "jurisprudence", "boss"],
            jurisprudence=planner_jurisprudence,
        ),
    )
    primary = [
        _search_result(
            "code-1",
            index,
            source_type="code_travail",
        )
        for index in range(3)
    ]
    agent = RAGAgent.__new__(RAGAgent)
    agent._run_variant_searches = AsyncMock(return_value=primary)
    agent.search_engine = MagicMock()
    legislation = _search_result("law-1", 0, source_type="loi")
    ruling = _search_result("case-1", 0, source_type="arret_cour_cassation")
    agent.search_engine.search = AsyncMock(side_effect=[[primary[0], legislation], [ruling]])
    agent._org_id = "org-1"
    agent._user_id = None
    agent._conversation_id = None
    agent._is_replay = True

    pool, _variants = await agent._search_with_plan(
        plan,
        plan.standalone_question,
        "org-1",
        org_idcc_list=["1486"],
    )

    assert [(result.document_id, result.chunk_index) for result in pool] == [
        ("code-1", 0),
        ("code-1", 1),
        ("code-1", 2),
        ("law-1", 0),
        ("case-1", 0),
    ]
    assert agent.search_engine.search.await_count == 2
    legislation_call, jurisprudence_call = agent.search_engine.search.await_args_list
    assert legislation_call.args[0] == "validité du préavis rupture du contrat"
    assert "loi" in legislation_call.kwargs["source_type_filter"]
    assert "boss" in legislation_call.kwargs["source_type_filter"]
    assert jurisprudence_call.kwargs["top_k"] == 3
    assert set(jurisprudence_call.kwargs["source_type_filter"]) == {
        "arret_cour_cassation",
        "arret_cour_appel",
        "arret_conseil_etat",
        "decision_conseil_constitutionnel",
    }
    assert agent._run_variant_searches.await_args.kwargs["apply_legislation_floor"] is False


@pytest.mark.asyncio
async def test_adaptive_article_hypotheses_are_tenant_filtered_bounded_candidates():
    plan = build_deterministic_search_plan(
        "Combien de jours de congés l'employeur peut-il imposer ?",
        org_idcc_list=["1486"],
    )
    plan = apply_compact_planner_payload(
        plan,
        _valid_payload(
            hypothesized_articles=[
                {"reference": "L.3141-16", "confidence": "medium"},
                {"reference": "L3141-15", "confidence": "medium"},
            ]
        ),
    )
    fetched = [
        _search_result("code-1", 0, article_nums=["L3141-16"]),
        _search_result("code-1", 1, article_nums=["L3141-16"]),
        _search_result("code-1", 2, article_nums=["L3141-16"]),
        _search_result("code-2", 0, article_nums=["L3141-15"]),
        _search_result(
            "ccn-1",
            0,
            article_nums=["L3141-15"],
            source_type="convention_collective_nationale",
        ),
    ]
    baseline = [_search_result("semantic", 0, article_nums=["L3141-16"])]

    with patch(
        "app.rag.agent.fetch_by_identifiers",
        new=AsyncMock(return_value=fetched),
    ) as fetch_mock:
        agent = RAGAgent.__new__(RAGAgent)
        agent.search_engine = MagicMock()
        agent.search_engine.qdrant = MagicMock()
        (
            results,
            validation,
            refs_by_key,
            added_keys,
        ) = await agent._inject_plan_hypothesis_candidates(
            plan,
            baseline,
            "org-1",
            ["1486"],
        )

    fetch_mock.assert_awaited_once_with(
        agent.search_engine.qdrant,
        {
            "numero_pourvoi": [],
            "article_nums": ["L3141-16", "L3141-15"],
        },
        organisation_id="org-1",
        org_idcc_list=["1486"],
    )
    assert [(result.document_id, result.chunk_index) for result in results] == [
        ("semantic", 0),
        ("code-1", 0),
        ("code-1", 1),
        ("code-2", 0),
    ]
    assert validation == {
        "status": "ok",
        "hypotheses_proposed": ["L3141-16", "L3141-15"],
        "hypotheses_requested": ["L3141-16", "L3141-15"],
        "hypotheses_skipped_low_confidence": [],
        "corpus_matches": ["L3141-15", "L3141-16"],
        "candidate_chunks_fetched": 3,
        "candidate_chunks_added": 3,
        "rejected_below_confidence_floor": [],
        "retained_after_rerank": [],
        "retained_in_final_sources": [],
    }
    assert refs_by_key[("code-1", 0)] == {"L3141-16"}
    assert ("ccn-1", 0) not in refs_by_key
    assert added_keys == {("code-1", 0), ("code-1", 1), ("code-2", 0)}


@pytest.mark.asyncio
async def test_low_confidence_article_hypotheses_never_reach_the_corpus_lookup():
    plan = build_deterministic_search_plan("Un licenciement pendant une maladie ?")
    plan = apply_compact_planner_payload(
        plan,
        _valid_payload(
            hypothesized_articles=[
                {"reference": "L1226-9", "confidence": "low"},
            ]
        ),
    )
    agent = RAGAgent.__new__(RAGAgent)
    agent.search_engine = MagicMock()

    with patch(
        "app.rag.agent.fetch_by_identifiers",
        new=AsyncMock(return_value=[]),
    ) as fetch_mock:
        (
            results,
            validation,
            refs_by_key,
            added_keys,
        ) = await agent._inject_plan_hypothesis_candidates(
            plan,
            [],
            "org-1",
            ["1486"],
        )

    fetch_mock.assert_not_awaited()
    assert results == []
    assert refs_by_key == {}
    assert added_keys == set()
    assert validation["hypotheses_proposed"] == ["L1226-9"]
    assert validation["hypotheses_requested"] == []
    assert validation["hypotheses_skipped_low_confidence"] == ["L1226-9"]


@pytest.mark.asyncio
async def test_adaptive_trace_distinguishes_found_and_reranker_retained_hypotheses():
    plan = build_deterministic_search_plan(
        "Combien de jours de congés l'employeur peut-il imposer ?"
    )
    plan = apply_compact_planner_payload(
        plan,
        _valid_payload(
            hypothesized_articles=[
                {"reference": "L3141-16", "confidence": "medium"},
                {"reference": "L9999-1", "confidence": "medium"},
            ]
        ),
    )
    relevant = _search_result("code-1", 0, article_nums=["L3141-16"])
    irrelevant = _search_result("code-2", 0, article_nums=["L9999-1"])
    relevant.score = 0.7
    irrelevant.score = 0.4

    with patch("app.rag.agent._search_engine"), patch("app.rag.agent.get_reranker"):
        agent = RAGAgent()
    agent._search_with_plan = AsyncMock(return_value=([], [plan.standalone_question]))
    agent.reranker = MagicMock()
    agent.reranker.rerank = AsyncMock(return_value=[relevant, irrelevant])

    with (
        patch(
            "app.rag.agent.fetch_by_identifiers",
            new=AsyncMock(return_value=[relevant, irrelevant]),
        ),
        patch(
            "app.rag.agent.expand_to_parents",
            new=AsyncMock(return_value=[relevant]),
        ),
    ):
        _results, _reformulated, trace = await agent.prepare_context(
            plan.query_original,
            "org-1",
            search_plan=plan,
        )

    assert trace.search_plan_validation["corpus_matches"] == [
        "L3141-16",
        "L9999-1",
    ]
    assert trace.search_plan_validation["rejected_below_confidence_floor"] == ["L9999-1"]
    assert trace.search_plan_validation["retained_after_rerank"] == ["L3141-16"]
    assert trace.search_plan_validation["retained_in_final_sources"] == ["L3141-16"]


@pytest.mark.asyncio
async def test_baseline_never_fetches_plan_article_hypotheses():
    with patch("app.rag.agent._search_engine"), patch("app.rag.agent.get_reranker"):
        agent = RAGAgent()
    agent._search_with_expansion = AsyncMock(return_value=([], ["question"]))
    agent.reranker = MagicMock()
    agent.reranker.rerank = AsyncMock(return_value=[])

    with (
        patch(
            "app.rag.agent.fetch_by_identifiers",
            new=AsyncMock(return_value=[]),
        ) as fetch_mock,
        patch(
            "app.rag.agent.expand_to_parents",
            new=AsyncMock(return_value=[]),
        ),
    ):
        await agent.prepare_context("question", "org-1")

    fetch_mock.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_production_adaptive_search_executes_deterministic_plan_without_llm():
    """Exact routes become adaptive without paying for a planning LLM call."""

    with patch("app.rag.agent._search_engine"), patch("app.rag.agent.get_reranker"):
        agent = RAGAgent()
    agent._search_with_plan = AsyncMock(return_value=([], ["question"]))
    agent._search_with_expansion = AsyncMock()
    agent.reranker = MagicMock()
    agent.reranker.rerank = AsyncMock(return_value=[])

    with (
        patch(
            "app.rag.agent.run_compact_search_planner",
            wraps=run_compact_search_planner,
        ) as planner,
        patch(
            "app.rag.agent.expand_to_parents",
            new=AsyncMock(return_value=[]),
        ),
    ):
        _results, _reformulated, trace = await agent.prepare_context(
            "Quelles sont les dernières actualités en droit social ?",
            "org-1",
            adaptive_search=True,
        )

    planner.assert_awaited_once()
    agent._search_with_plan.assert_awaited_once()
    agent._search_with_expansion.assert_not_awaited()
    assert trace.search_plan_usage["execution"] == "adaptive"
    assert trace.search_plan_usage["prompt_tokens"] == 0


@pytest.mark.asyncio
async def test_production_adaptive_search_falls_back_to_deterministic_search():
    """An unavailable compact planner must not prevent deterministic retrieval."""

    query = "Un employeur peut-il licencier un salarié pendant un arrêt maladie ?"
    deterministic = build_deterministic_search_plan(query)
    fallback = replace(
        deterministic,
        planner_status=PlannerStatus.FALLBACK,
        warnings=[*deterministic.warnings, "planner_timeout"],
    )

    with patch("app.rag.agent._search_engine"), patch("app.rag.agent.get_reranker"):
        agent = RAGAgent()
    agent._search_with_plan = AsyncMock()
    agent._search_with_expansion = AsyncMock(return_value=([], [query]))
    agent.reranker = MagicMock()
    agent.reranker.rerank = AsyncMock(return_value=[])

    with (
        patch(
            "app.rag.agent.run_compact_search_planner",
            new=AsyncMock(return_value=PlannerCallResult(plan=fallback)),
        ),
        patch(
            "app.rag.agent.expand_to_parents",
            new=AsyncMock(return_value=[]),
        ),
    ):
        _results, _reformulated, trace = await agent.prepare_context(
            query,
            "org-1",
            adaptive_search=True,
        )

    agent._search_with_expansion.assert_awaited_once()
    agent._search_with_plan.assert_not_awaited()
    assert trace.search_plan_usage["execution"] == "deterministic_fallback"
    assert trace.search_plan_usage["fallback_to_deterministic"] is True
    assert trace.search_plan["planner_status"] == "fallback"
