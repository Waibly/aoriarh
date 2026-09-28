"""Catalogue contracts and access isolation; no live model or output evaluator."""

import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.models.document import Document
from app.rag.agent import RAGAgent
from app.rag.chronology import ChronologyRequest
from app.rag.legal_catalogue import LegalCatalogueSearch, catalogue_page
from app.rag.parent_expansion import RetrievalError
from app.rag.search import HybridSearch, SearchResult
from app.rag.search_plan import (
    apply_compact_planner_payload,
    build_deterministic_search_plan,
)
from app.services.conversation_requests import RequestLegalSearch, request_schema
from app.services.jorf_service import JorfService
from tests.conftest import test_session_factory


def spec(**changes):
    return ChronologyRequest(
        **{
            "date_kind": "publication",
            "date_from": None,
            "date_to": None,
            "period_basis": "none",
            "source_types": ["decret"],
            "jurisdiction": None,
            "chamber": None,
            "topic": None,
            "order": "newest",
            "limit": 2,
            "offset": 0,
            **changes,
        }
    )


def document(name, **changes):
    return Document(
        **{
            "id": uuid.uuid4(),
            "name": name,
            "source_type": "decret",
            "storage_path": f"common/jorf/{name}.txt",
            "indexation_status": "indexed",
            "organisation_id": None,
            "chunk_count": 1,
            **changes,
        }
    )


async def insert(*documents):
    async with test_session_factory() as db:
        db.add_all(documents)
        await db.commit()


async def page(request):
    async with test_session_factory() as db:
        return await catalogue_page(db, request, today=date(2026, 9, 28))


async def test_latest_documents_have_no_invented_period_and_ignore_chunk_count():
    newest = document("new", publication_date=date(2026, 9, 27), chunk_count=90)
    older = document("old", publication_date=date(2025, 3, 1))
    unknown = document("legacy", date_decision=date(2026, 9, 28))
    future = document("future", publication_date=date(2027, 1, 1))
    await insert(older, newest, unknown, future)
    rows, coverage = await page(spec())
    assert [d.id for d, _ in rows] == [newest.id, older.id]
    assert coverage["request"]["date_from"] is None
    assert coverage["matching_dated_documents"] == 2
    assert coverage["documents_with_unknown_date"] == 1
    assert coverage["collection_status"][0]["status"] == "unknown"


async def test_period_includes_both_endpoints_and_paginates_distinct_documents():
    docs = [document(str(day), publication_date=date(2026, 9, day)) for day in (1, 2, 3, 4)]
    await insert(*docs)
    query = spec(
        date_from=date(2026, 9, 2), date_to=date(2026, 9, 4), period_basis="explicit", limit=2
    )
    rows, report = await page(query)
    assert [d.name for d, _ in rows] == ["4", "3"]
    assert report["catalogue_has_more"] is True
    rows, report = await page(query.model_copy(update={"offset": 2}))
    assert [d.name for d, _ in rows] == ["2"]
    assert report["catalogue_has_more"] is False


async def test_catalogue_excludes_all_private_files_unindexed_documents_and_other_types():
    public = document("public", publication_date=date(2026, 9, 1))
    await insert(
        public,
        document("private", publication_date=date(2026, 9, 27), organisation_id=uuid.uuid4()),
        document("pending", publication_date=date(2026, 9, 27), indexation_status="pending"),
        document(
            "ccn", publication_date=date(2026, 9, 27), source_type="convention_collective_nationale"
        ),
    )
    rows, report = await page(spec(source_types=[]))
    assert [d.id for d, _ in rows] == [public.id]
    assert report["matching_dated_documents"] == 1


async def test_decision_filters_jurisdiction_chamber_and_uses_decision_date():
    target = document(
        "sociale",
        source_type="arret_cour_cassation",
        juridiction="Cour de cassation",
        chambre="Chambre sociale",
        date_decision=date(2026, 9, 23),
    )
    await insert(
        target,
        document(
            "civile",
            source_type="arret_cour_cassation",
            juridiction="Cour de cassation",
            chambre="Chambre civile",
            date_decision=date(2026, 9, 24),
        ),
    )
    rows, _ = await page(
        spec(
            date_kind="decision",
            source_types=["arret_cour_cassation"],
            jurisdiction="cassation",
            chamber="sociale",
        )
    )
    assert [d.id for d, _ in rows] == [target.id]
    # Wildcards supplied as parameters are literal, never SQL match operators.
    rows, _ = await page(spec(date_kind="decision", source_types=[], chamber="%"))
    assert rows == []


async def test_future_effective_dates_are_distinct_from_publication_and_update():
    upcoming = document(
        "upcoming", publication_date=date(2026, 8, 1), effective_date=date(2026, 10, 1)
    )
    boss = document("boss", source_type="boss", source_updated_date=date(2026, 9, 15))
    await insert(upcoming, boss)
    rows, _ = await page(
        spec(
            date_kind="effective",
            date_from=date(2026, 9, 28),
            period_basis="explicit",
            order="oldest",
        )
    )
    assert [(d.id, when) for d, when in rows] == [(upcoming.id, date(2026, 10, 1))]
    rows, _ = await page(spec(date_kind="event", source_types=[]))
    assert [d.id for d, _ in rows] == [boss.id, upcoming.id]


def test_invalid_operation_is_rejected_without_repair():
    with pytest.raises(ValidationError, match="chronology_unattributed_period"):
        spec(date_from=date(2026, 9, 1))
    with pytest.raises(ValidationError, match="chronology_inverted_period"):
        spec(date_from=date(2026, 9, 2), date_to=date(2026, 9, 1), period_basis="explicit")
    with pytest.raises(ValidationError):
        spec(source_types=["contrat_travail"])


def test_journal_publication_does_not_use_signature_date():
    data = {"dateTexte": "2026-09-01", "dateParution": "2026-09-03"}
    assert JorfService._parse_consult(data)[2] == date(2026, 9, 3)
    assert JorfService._parse_consult({"dateTexte": "2026-09-01"})[2] is None


def payload(chronology):
    return {
        "standalone_question": "Les derniers décrets ?",
        "needs_history": False,
        "legal_topics": [],
        "search_queries": ["décrets"],
        "hypothesized_articles": [],
        "source_hints": ["legislation"],
        "jurisprudence": "optional",
        "answer_intent": "legal_news",
        "missing_facts": [],
        "chronology": chronology,
    }


def test_chronology_survives_typed_request_and_plan_compilation():
    query = spec().model_dump(mode="json")
    wire = payload(query)
    arguments = RequestLegalSearch.model_validate_json(
        json.dumps({k: v for k, v in wire.items() if k != "standalone_question"})
    )
    base = build_deterministic_search_plan(wire["standalone_question"])
    plan = apply_compact_planner_payload(
        base,
        {
            **arguments.model_dump(mode="json"),
            "standalone_question": wire["standalone_question"],
        },
    )
    assert plan.chronology == query
    assert plan.chronology["date_from"] is None
    schema = request_schema(1)
    assert "chronology" in schema["$defs"]["RequestLegalSearch"]["required"]


def engine_for(documents):
    engine = HybridSearch.__new__(HybridSearch)
    engine.qdrant = MagicMock()

    def scroll(**kwargs):
        restriction = kwargs["scroll_filter"].model_dump_json()
        assert "common" in restriction
        doc = next(d for d in documents if str(d.id) in restriction)
        return (
            [
                SimpleNamespace(
                    payload={
                        "text": f"Texte original {doc.name}\n\nFIN",
                        "document_id": str(doc.id),
                        "doc_name": doc.name,
                        "source_type": doc.source_type,
                        "chunk_index": 0,
                        "organisation_id": "common",
                    }
                )
            ],
            None,
        )

    engine.qdrant.scroll.side_effect = scroll
    engine.search = AsyncMock()
    return engine


async def test_catalogue_execution_reads_sources_without_semantic_search_or_reranking():
    doc = document("recent", publication_date=date(2026, 9, 1))
    await insert(doc)
    engine, reranker = engine_for([doc]), SimpleNamespace(rerank=AsyncMock())
    service = LegalCatalogueSearch(engine, reranker, session_factory=test_session_factory)
    results, report = await service.search(spec(), str(uuid.uuid4()))
    assert results[0].text == "Texte original recent\n\nFIN"
    assert results[0].publication_date == "2026-09-01"
    assert report["selected_documents"][0]["partial_read"] is False
    engine.search.assert_not_called()
    reranker.rerank.assert_not_called()


async def test_topic_search_is_constrained_before_retrieval_and_final_order_is_chronological():
    new = document("new", publication_date=date(2026, 9, 20))
    old = document("old", publication_date=date(2026, 9, 1))
    excluded = document("outside", publication_date=date(2025, 1, 1))
    await insert(new, old, excluded)
    engine = engine_for([new, old])
    candidates = [
        SearchResult(
            text=d.name,
            doc_name=d.name,
            document_id=str(d.id),
            source_type="decret",
            norme_niveau=5,
            norme_poids=0.5,
            chunk_index=0,
            score=score,
        )
        for d, score in ((old, 0.9), (new, 0.5))
    ]
    engine.search.return_value = candidates
    reranker = SimpleNamespace(rerank=AsyncMock(return_value=candidates))
    service = LegalCatalogueSearch(engine, reranker, session_factory=test_session_factory)
    results, report = await service.search(
        spec(topic="congés payés", date_from=date(2026, 9, 1), period_basis="explicit"),
        str(uuid.uuid4()),
    )
    assert engine.search.await_args.kwargs["document_ids"] == [str(new.id), str(old.id)]
    assert [r.document_id for r in results] == [str(new.id), str(old.id)]
    assert report["topic_selection_is_exhaustive"] is False


async def test_missing_source_text_is_a_technical_error_not_an_empty_catalogue():
    doc = document("missing", publication_date=date(2026, 9, 1))
    await insert(doc)
    engine = engine_for([doc])
    engine.qdrant.scroll.side_effect = None
    engine.qdrant.scroll.return_value = ([], None)
    service = LegalCatalogueSearch(engine, MagicMock(), session_factory=test_session_factory)
    with pytest.raises(RetrievalError, match="chronological_document_unavailable"):
        await service.search(spec(), str(uuid.uuid4()))


async def test_agent_dispatches_catalogue_and_keeps_coverage_when_empty(monkeypatch):
    plan = apply_compact_planner_payload(
        build_deterministic_search_plan("Les derniers décrets ?"),
        payload(spec().model_dump(mode="json")),
    )
    catalogue = AsyncMock(return_value=([], {"matching_dated_documents": 0}))
    monkeypatch.setattr(LegalCatalogueSearch, "search", catalogue)
    agent = RAGAgent()
    agent._search_with_plan = AsyncMock()
    results, _, trace = await agent.prepare_context(
        "Les derniers décrets ?",
        str(uuid.uuid4()),
        search_plan=plan,
    )
    assert results == [] and trace.error is None and trace.no_results
    assert trace.search_plan_validation["chronology"]["matching_dated_documents"] == 0
    agent._search_with_plan.assert_not_called()
    assert catalogue.await_args.args[0].date_from is None


def test_date_migration_never_promotes_ambiguous_jorf_dates():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    path = Path(__file__).parents[1] / "alembic/versions/i8j9chronology01_document_source_dates.py"
    module_spec = importlib.util.spec_from_file_location("date_migration", path)
    migration = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE documents (id INTEGER PRIMARY KEY, "
                "source_type TEXT, organisation_id TEXT, date_decision DATE)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO documents VALUES "
                "(1, 'decret', NULL, '2026-09-01'), "
                "(2, 'boss', NULL, '2026-09-02')"
            )
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        rows = connection.execute(
            text("SELECT publication_date, source_updated_date FROM documents ORDER BY id")
        ).all()
        assert rows == [(None, None), (None, "2026-09-02")]
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert "publication_date" not in {
            column["name"] for column in inspect(connection).get_columns("documents")
        }
    engine.dispose()


async def test_metadata_hydration_previews_then_writes_only_explicit_dates(monkeypatch, capsys):
    from scripts.maintenance import hydrate_jorf_dates

    doc = document("historical", numero_pourvoi="JORFTEXT000000001", date_decision=date(2026, 9, 1))
    await insert(doc)
    monkeypatch.setattr(hydrate_jorf_dates, "async_session_factory", test_session_factory)
    monkeypatch.setattr(
        JorfService,
        "_api_post",
        AsyncMock(
            return_value={
                "dateTexte": "2026-09-01",
                "dateParution": "2026-09-03",
            }
        ),
    )
    await hydrate_jorf_dates.hydrate(limit=1)
    async with test_session_factory() as db:
        stored = await db.get(Document, doc.id)
        assert stored.publication_date is None
    await hydrate_jorf_dates.hydrate(limit=1, apply=True)
    async with test_session_factory() as db:
        stored = await db.get(Document, doc.id)
        assert stored.publication_date == date(2026, 9, 3)
        assert stored.date_decision == date(2026, 9, 1)
        assert stored.effective_date is None
        assert stored.source_url.endswith("JORFTEXT000000001")
    capsys.readouterr()


async def test_catalogue_obeys_application_source_constraints():
    await insert(
        document("decree", publication_date=date(2026, 9, 1)),
        document("law", source_type="loi", publication_date=date(2026, 9, 2)),
    )
    request = spec(source_types=[])
    async with test_session_factory() as db:
        rows, report = await catalogue_page(
            db, request, source_exclusions=["decret"], source_restriction=["decret", "loi"]
        )
    assert [d.source_type for d, _ in rows] == ["loi"]
    assert report["allowed_source_types"] == ["loi"]
    assert request.source_types == []  # The generated operation remains unchanged.


async def test_empty_catalogue_coverage_reaches_generation_and_raw_output_is_preserved():
    original = "  Texte original\n\n<balise>\tfin  "

    async def stream():
        for text in (original[:8], original[8:]):
            yield SimpleNamespace(
                usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
            )

    agent = RAGAgent()
    agent.llm = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(return_value=stream()),
            )
        )
    )
    coverage = {
        "request": spec().model_dump(mode="json"),
        "matching_dated_documents": 0,
        "documents_with_unknown_date": 7,
    }
    output = "".join(
        [
            chunk
            async for chunk in agent.stream_generate(
                "Les derniers décrets ?",
                [],
                chronology_context=coverage,
            )
        ]
    )
    assert output == original
    messages = agent.llm.chat.completions.create.await_args.kwargs["messages"]
    assert json.dumps(coverage, ensure_ascii=False) in messages[1]["content"]
    agent.llm.chat.completions.create.assert_awaited_once()


async def test_batch_metadata_hydration_uses_exact_cid_and_official_publication(
    monkeypatch, capsys
):
    from scripts.maintenance import hydrate_jorf_dates

    doc = document("batch", numero_pourvoi="JORFTEXT000000002")
    await insert(doc)
    monkeypatch.setattr(hydrate_jorf_dates, "async_session_factory", test_session_factory)
    api = AsyncMock(
        return_value={
            "totalResultNumber": 2,
            "results": [
                {
                    "titles": [{"cid": "JORFTEXT000000002"}],
                    "date": "2999-01-01",
                    "datePublication": "2026-09-03T00:00:00.000+0000",
                },
                {"titles": [{"cid": "JORFTEXT_NOT_IN_CORPUS"}], "datePublication": "2026-09-04"},
            ],
        }
    )
    monkeypatch.setattr(JorfService, "_api_post", api)
    await hydrate_jorf_dates.hydrate_year(year=2026, natures=["DECRET"], apply=False)
    async with test_session_factory() as db:
        assert (await db.get(Document, doc.id)).publication_date is None
    await hydrate_jorf_dates.hydrate_year(year=2026, natures=["DECRET"], apply=True)
    async with test_session_factory() as db:
        assert (await db.get(Document, doc.id)).publication_date == date(2026, 9, 3)
    capsys.readouterr()
