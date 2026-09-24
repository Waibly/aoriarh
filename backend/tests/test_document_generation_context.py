from unittest.mock import AsyncMock, MagicMock

import pytest

from app.rag.agent import RAGAgent, RagTrace, _generation_system_prompt
from app.rag.document_generation import (
    build_document_task_context,
    scope_documentary_legal_results,
)
from app.rag.search import SearchResult


def source(identifier):
    return SearchResult(text="  Texte original\n", doc_name="contrat.txt",
                        document_id=identifier, source_type="divers", norme_niveau=9,
                        norme_poids=0.1, chunk_index=0, score=1)


def context(action="documents", results=None):
    task = dict(action=action, objective="  Objectif brut\n", legal_search=None)
    return build_document_task_context(
        [dict(document_id="selected", extraction_id="version-1")],
        results or [source("selected")], RagTrace(search_plan={"document_task": task}),
    )


def test_roles_use_ids_not_names_and_keep_every_source_and_raw_plan():
    results = [source("other"), source("selected")]
    value = context("documents_and_law", results)
    assert [s["role"] for s in value["sources"]] == ["retrieved_reference", "case_document"]
    assert value["plan"]["objective"] == "  Objectif brut\n"
    agent = RAGAgent.__new__(RAGAgent)
    body = agent._build_context(results, document_task_context=value)
    assert "Identifiant document : other\nOrigine : retrieved_reference" in body
    assert "Identifiant document : selected\nOrigine : case_document" in body
    assert body.count("  Texte original\n") == 2


def test_no_document_path_is_byte_identical():
    import hashlib

    assert hashlib.sha256(_generation_system_prompt()[0].encode()).hexdigest() == (
        "9de66cd0dc90aa5bd4e7f7c8139a69720537f3624ae322c6c9cfb30fe067e1d9"
    )
    agent = RAGAgent.__new__(RAGAgent)
    assert _generation_system_prompt() == _generation_system_prompt(document_task_context=None)
    body = agent._build_context([source("selected")])
    assert body == agent._build_context([source("selected")], document_task_context=None)


def test_context_only_deduplicates_identical_blocks_from_the_same_document():
    from dataclasses import replace

    agent = RAGAgent.__new__(RAGAgent)
    original = source("selected")
    distinct = replace(original, text="  Autre passage\n")
    dated = replace(original, effective_from="2026-10-01")
    other = source("other")
    body = agent._build_context([original, original, distinct, dated, other])
    assert body.count("  Texte original\n") == 3
    assert "  Autre passage\n" in body
    assert "2026-10-01" in body
    assert agent._build_user_message("q", body) == agent._build_user_message(
        "q", body, document_task_context=None,
    )


@pytest.mark.parametrize("action", ["documents", "documents_and_law"])
async def test_actual_stream_receives_executed_action_without_extra_call(action):
    from types import SimpleNamespace

    agent = RAGAgent.__new__(RAGAgent)
    agent.llm = MagicMock()

    async def stream():
        yield SimpleNamespace(usage=None, choices=[SimpleNamespace(
            delta=SimpleNamespace(content="  réponse originale\n"))])

    agent.llm.chat.completions.create = AsyncMock(return_value=stream())
    chunks = [chunk async for chunk in agent.stream_generate(
        "q", [source("selected")], document_task_context=context(action),
    )]
    assert chunks == ["  réponse originale\n"]
    assert agent.llm.chat.completions.create.await_count == 1
    messages = agent.llm.chat.completions.create.await_args.kwargs["messages"]
    assert "Contrat de rédaction avec pièces jointes" in messages[0]["content"]
    assert ("SANS recherche juridique" in messages[0]["content"]) == (action == "documents")
    assert "SÉCURITÉ, TRANSPARENCE ET FRONTIÈRES DE CONFIANCE" in messages[0]["content"]
    assert "Tu es l'expert juridique RH intégré" not in messages[0]["content"]
    assert ("FIABILITÉ JURIDIQUE COMMUNE" in messages[0]["content"]) == (
        action == "documents_and_law"
    )
    assert f'"action": "{action}"' in messages[1]["content"]


def test_failed_task_cannot_construct_generation_context():
    with pytest.raises(ValueError):
        build_document_task_context([], [], RagTrace(error="search_planner_error"))


def test_legal_capability_keeps_selected_files_and_org_norms_not_other_personal_files():
    from dataclasses import replace

    selected = source("selected")
    other = source("other")
    contract = replace(other, document_id="contract", source_type="contrat_travail")
    agreement = replace(other, document_id="agreement", source_type="accord_entreprise")
    law = replace(other, document_id="law", source_type="code_travail")
    kept, excluded = scope_documentary_legal_results(
        [dict(document_id="selected")], [selected, other, contract, agreement, law],
    )
    assert kept == [selected, agreement, law]
    assert [item["document_id"] for item in excluded] == ["other", "contract"]
    # Explicit selection admits the very same file regardless of its classification.
    assert scope_documentary_legal_results([dict(document_id="contract")], [contract]) == (
        [contract], [],
    )
