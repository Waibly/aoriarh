"""Reference/ACL/context contracts, independent of any LLM generation."""

from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.rag.legal_references import (
    _read_instrument,
    build_graph,
    explicit_reference_scopes,
    extend_reference_context,
    norm,
    refs,
)
from app.rag.parent_expansion import ParentExpansionError
from app.rag.search import SearchResult
from app.rag.source_intent import CODE_SOURCE_LABELS


def chunk(index=1, article="L100-1", text="Règle", **kwargs):
    values = dict(
        text=text,
        doc_name="Instrument",
        document_id="doc",
        source_type="code_travail",
        organisation_id="common",
        norme_niveau=3,
        norme_poids=0.9,
        chunk_index=index,
        article_nums=[article],
        score=0.8,
        section_path="Livre I > Chapitre I > Section 1",
    )
    values.update(kwargs)
    return SearchResult(**values)


def point(r):
    return {"id": str(r.chunk_index), "payload": asdict(r)}


def graph(root, rows):
    return build_graph(
        asdict(root),
        [point(r) for r in rows],
        scope_resolver=lambda text: explicit_reference_scopes(text, CODE_SOURCE_LABELS),
    )


def test_normalized_references():
    assert norm("L. 100‑1") == "L100-1"
    assert refs("L.100-1, R 100-2, D100–3 et A100-4") == {"L100-1", "R100-2", "D100-3", "A100-4"}


@pytest.mark.parametrize(
    "text,scoped",
    [
        ("L100-1 du code civil", {"L100-1"}),
        ("L100-1 et L100-2 du code civil", {"L100-1", "L100-2"}),
        ("L100-1 du code imaginaire", {"L100-1"}),
        ("L100-1 du même code", {"L100-1"}),
    ],
)
def test_other_or_unknown_named_codes_never_attach_to_current_code(text, scoped):
    scopes = explicit_reference_scopes(text, CODE_SOURCE_LABELS)
    assert set(scopes) == scoped
    assert all("code_travail" not in scope for scope in scopes.values())


def test_adjacent_code_scope_does_not_apply_to_whole_paragraph():
    scope = explicit_reference_scopes("L100-1 du code civil. Voir L200-1.", CODE_SOURCE_LABELS)
    assert "L100-1" in scope and "L200-1" not in scope


def test_outbound_cross_section_and_inverse_local():
    root = chunk(text="Voir L200-1")
    outgoing = chunk(2, "L200-1", section_path="Livre II > Chapitre II > Section 2")
    inverse = chunk(3, "L100-2", "Pour L100-1, maintien du droit")
    remote_inverse = chunk(4, "L300-1", "Voir L100-1", section_path="Autre > Section 3")
    result = graph(root, [root, outgoing, inverse, remote_inverse])
    assert {r["point_id"] for r in result["records"]} == {"1", "2", "3"}


def test_missing_section_never_expands_inverse_to_entire_document():
    root = chunk(section_path=None)
    other = chunk(2, "L200-1", "Voir L100-1", section_path=None)
    assert len(graph(root, [root, other])["records"]) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("organisation_id", "other-tenant"),
        ("document_id", "other-document"),
        ("instrument_id", "other-instrument"),
        ("source_type", "code_civil"),
        ("effective_from", "2020-01-01"),
        ("effective_to", "2025-01-01"),
        ("instrument_status", "abroge"),
    ],
)
def test_graph_does_not_cross_identity_or_instrument_version(field, value):
    root = chunk(text="Voir L200-1")
    other = chunk(2, "L200-1", **{field: value})
    result = graph(root, [root, other])
    assert {r["point_id"] for r in result["records"]} == {"1"}
    assert "L200-1" in result["audit"]["unresolved_or_not_expanded_references"]


def test_ambiguous_article_versions_are_reported_and_not_merged():
    root = chunk(text="Voir L200-1")
    a = chunk(2, "L200-1", article_effective_from="2020-01-01")
    b = chunk(3, "L200-1", article_effective_from="2025-01-01")
    result = graph(root, [root, a, b])
    assert result["audit"]["ambiguous_article_versions_not_resolved"] == ["L200-1"]
    assert {r["point_id"] for r in result["records"]} == {"1"}


def test_external_reference_reported_not_resolved_in_same_number():
    root = chunk(text="L200-1 du code civil")
    result = graph(root, [root, chunk(2, "L200-1")])
    assert result["audit"]["external_instrument_references_not_resolved"] == ["L200-1"]
    assert len(result["records"]) == 1


def test_two_rounds_report_remaining_links():
    rows = [
        chunk(text="L200-1"),
        chunk(2, "L200-1", "L300-1"),
        chunk(3, "L300-1", "L400-1"),
        chunk(4, "L400-1"),
    ]
    result = graph(rows[0], rows)
    assert len(result["audit"]["rounds"]) == 2
    assert result["audit"]["unresolved_or_not_expanded_references"] == ["L400-1"]


def test_scroll_uses_application_acl_and_all_pages():
    qdrant = MagicMock()
    qdrant.scroll.side_effect = [([SimpleNamespace(id="x", payload={})], "next"), ([], None)]
    rows, pages = _read_instrument(qdrant, chunk(instrument_id="instrument"), "tenant", ["1486"])
    assert len(rows) == 1 and pages == 2
    filters = qdrant.scroll.call_args_list[0].kwargs["scroll_filter"].model_dump_json()
    assert all(x in filters for x in ["tenant", "common", "private", "1486", "instrument", "doc"])
    assert qdrant.scroll.call_args_list[1].kwargs["offset"] == "next"
    assert qdrant.scroll.call_args_list[0].kwargs["with_vectors"] is False


def test_repeated_pagination_is_technical_error():
    qdrant = MagicMock()
    qdrant.scroll.return_value = ([], "same")
    with pytest.raises(ParentExpansionError, match="pagination_not_progressing"):
        _read_instrument(qdrant, chunk(), "tenant", [])


async def test_additions_preserve_all_ten_initial_groups_and_whole_linked_passages():
    root = chunk(text="Voir L200-1", context_chunk_indices=[1])
    baseline = [root, *[chunk(i, f"L{100 + i}-1", document_id=f"doc{i}") for i in range(2, 11)]]
    linked = chunk(11, "L200-1", "Passage original " + "x" * 12000)
    qdrant = MagicMock()
    qdrant.scroll.return_value = ([SimpleNamespace(**point(r)) for r in [root, linked]], None)
    diagnostics = []
    output = await extend_reference_context(
        baseline, qdrant, organisation_id="tenant", diagnostics=diagnostics
    )
    assert output[:10] == baseline
    assert len(output) == 11 and output[-1].text == linked.text
    assert output[-1].context_chunk_indices == [11]
    assert diagnostics[0]["added_passages"][0]["selection_reason"] == "explicit_reference_link"


async def test_passage_dedup_and_root_article_continuation_keep_baseline_intact():
    root = chunk(text="Début", context_chunk_indices=[1])
    following = chunk(2, text="Suite intacte")
    qdrant = MagicMock()
    qdrant.scroll.return_value = ([SimpleNamespace(**point(r)) for r in [root, following]], None)
    output = await extend_reference_context([root], qdrant, organisation_id="tenant")
    assert output[0] is root and output[0].text == "Début"
    assert len(output) == 2 and output[1].text == "Suite intacte"
    assert output[1].context_chunk_indices == [2]


async def test_no_supported_article_does_not_read_qdrant():
    qdrant = MagicMock()
    baseline = [chunk(source_type="arret_cour_appel"), chunk(2, article="9")]
    assert await extend_reference_context(baseline, qdrant) is baseline
    qdrant.scroll.assert_not_called()


async def test_reference_transport_failure_is_not_an_empty_search_or_fallback():
    qdrant = MagicMock()
    qdrant.scroll.side_effect = OSError("network")
    diagnostics = []
    with pytest.raises(ParentExpansionError, match="reference_read_failed"):
        await extend_reference_context(
            [chunk()], qdrant, organisation_id="tenant", diagnostics=diagnostics
        )
    assert diagnostics[0]["reason"] == "reference_read_failed"


async def test_linked_passages_keep_source_identity_and_exact_display_text():
    from app.rag.agent import RAGAgent

    root = chunk(text="Voir L200-1", context_chunk_indices=[1])
    linked = chunk(2, "L200-1", "  Passage justificatif intégral\n")
    qdrant = MagicMock()
    qdrant.scroll.return_value = (
        [SimpleNamespace(**point(r)) for r in [root, linked]],
        None,
    )
    output = await extend_reference_context([root], qdrant, organisation_id="tenant")
    source = RAGAgent.__new__(RAGAgent)._format_sources(output)[0]
    assert source.document_id == root.document_id
    assert set(source.article_nums) == {"L100-1", "L200-1"}
    assert [p["text"] for p in source.context_passages] == [root.text, linked.text]
    assert source.context_passages[-1]["chunk_indices"] == [2]
    assert source.full_text == root.text + "\n\n" + linked.text


async def test_article_displaced_by_ten_rulings_still_starts_reference_graph():
    baseline = [
        chunk(i, source_type="arret_cour_appel", document_id=f"ruling-{i}", article_nums=None)
        for i in range(10)
    ]
    root = chunk(11, text="Voir L200-1", score=0.4)
    linked = chunk(12, "L200-1", "Règle complémentaire intacte")
    qdrant = MagicMock()
    qdrant.scroll.return_value = ([SimpleNamespace(**point(r)) for r in [root, linked]], None)
    output = await extend_reference_context(
        baseline,
        qdrant,
        organisation_id="tenant",
        candidate_roots=[*baseline, root],
    )
    assert output[:10] == baseline
    assert {a for r in output for a in r.article_nums or []} == {"L100-1", "L200-1"}
    assert all(r.text in [p.text for p in output] for r in [root, linked])
