import copy
import json
import uuid
from unittest.mock import Mock

import pytest
from qdrant_client.models import SparseVector

from app.rag.ingestion import IngestionPipeline
from app.services.social_ca_source import parse_ca_source, prepared_ca_chunks, verified_ca_source
from scripts.maintenance.import_social_ca import case_keys, read_source
from tests.conftest import test_session_factory


def raw_source():
    return dict(
        id="a" * 24,
        jurisdiction="ca",
        type="arret",
        nac="80J",
        location="ca_paris",
        chamber="Pôle 6 - Chambre 3",
        decision_date="2026-01-02",
        number="24/01234",
        numbers=["24/01234", "24/05678"],
        solution="confirme",
        zones={"motivations": [{"start": 0, "end": 10}]},
        text="  Première ligne\r\n\r\n"
        + "𝄞 salaire 1 234,56 €\n" * 200
        + '<table><tr><td colspan="2">Montant</td></tr>'
        + "<tr><td></td><td>1 234,56 €</td></tr></table>\nFin.  ",
    )


def test_original_text_references_and_tables_are_lossless():
    raw = raw_source()
    original = copy.deepcopy(raw)
    source = parse_ca_source(raw)
    doc = source.document()
    chunks = prepared_ca_chunks(source, doc)
    header = IngestionPipeline._build_jurisprudence_header(doc) + "\n\n"
    assert "".join(c[len(header) :] for c in chunks) == raw["text"]
    assert sum("<table>" in c for c in chunks) == 1
    assert source.metadata()["numero_pourvoi_aliases"] == ["2401234", "2405678"]
    assert source.metadata()["source_zones"] == raw["zones"]
    assert json.loads(source.source_bytes) == original == raw
    assert verified_ca_source(doc, raw["text"].encode(), source.source_bytes) == source


@pytest.mark.parametrize(
    "changes",
    [
        {"jurisdiction": "cc"},
        {"type": "ordonnance"},
        {"nac": "88E"},
        {"nac": "14G"},
        {"nac": None},
        {"decision_date": "not-a-date"},
        {"location": None},
        {"text": "\n "},
        {"number": ""},
        {"numbers": [None]},
        {"chamber": "x" * 101},
    ],
)
def test_source_contract_errors_never_fabricate_a_date_reference_or_body(changes):
    with pytest.raises((ValueError, TypeError)):
        parse_ca_source(dict(raw_source(), **changes))


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_url", "https://example.invalid/other"),
        ("file_hash", "0" * 64),
        ("chambre", "Other chamber"),
        ("id", uuid.UUID(int=1)),
        ("private_conversation_id", uuid.UUID(int=2)),
    ],
)
def test_sealed_source_rejects_identity_changes(field, value):
    source = parse_ca_source(raw_source())
    doc = source.document()
    setattr(doc, field, value)
    with pytest.raises(ValueError):
        verified_ca_source(doc, source.text.encode(), source.source_bytes)


def test_sealed_body_and_metadata_both_require_exact_original_bytes():
    source = parse_ca_source(raw_source())
    doc = source.document()
    with pytest.raises(ValueError):
        verified_ca_source(doc, source.text.strip().encode(), source.source_bytes)
    changed = dict(source.raw, nac="80K")
    with pytest.raises(ValueError):
        verified_ca_source(doc, source.text.encode(), parse_ca_source(changed).source_bytes)


def test_deduplication_requires_court_date_and_case_number():
    a = case_keys("Paris", "2026-01-02", ["24/01234"])
    assert a == case_keys("Paris", "2026-01-02", ["24-01234"])
    assert a.isdisjoint(case_keys("Lyon", "2026-01-02", ["24/01234"]))
    assert a.isdisjoint(case_keys("Paris", "2025-01-02", ["24/01234"]))


def test_source_archive_cannot_escape_operator_directory(tmp_path):
    with pytest.raises(ValueError, match="Unsafe"):
        read_source(tmp_path, {"path": "../outside.json.gz"})


@pytest.mark.asyncio
async def test_real_pipeline_keeps_every_character_and_source_metadata(monkeypatch):
    source = parse_ca_source(raw_source())
    doc = source.document()
    files = {
        doc.storage_path: source.text.encode(),
        doc.storage_path + ".source.json": source.source_bytes,
    }
    storage = Mock()
    storage.get_file_bytes.side_effect = files.__getitem__
    storage.get_file_bytes_bounded.side_effect = lambda path, limit: files[path]
    qdrant = Mock()
    qdrant.scroll.return_value = ([], None)
    monkeypatch.setattr(
        "app.rag.ingestion.clean_text",
        Mock(side_effect=AssertionError("Lossless source must bypass cleaner")),
    )
    monkeypatch.setattr(
        "app.rag.ingestion._get_sparse_vectors",
        lambda chunks: [SparseVector(indices=[1], values=[1.0]) for _ in chunks],
    )
    expected = prepared_ca_chunks(source, doc)

    async def embeddings(chunks, *args, **kwargs):
        assert chunks == expected
        return [[0.1] * 1024 for _ in chunks]

    async with test_session_factory() as session:
        session.add(doc)
        await session.commit()
        pipeline = IngestionPipeline(
            storage=storage, qdrant_client=qdrant, embedding_provider=embeddings
        )
        await pipeline.ingest(doc.id, session, expected_source=doc.storage_path)
        await session.refresh(doc)
        assert doc.indexation_status == "indexed", doc.indexation_error
        points = [point for call in qdrant.upsert.call_args_list for point in call.kwargs["points"]]
        assert [p.payload["text"] for p in points] == expected
        for point in points:
            assert (
                point.payload["organisation_id"] == "common" and point.payload["private"] is False
            )
            assert all(point.payload[k] == v for k, v in source.metadata().items())
