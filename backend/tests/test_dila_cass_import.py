import hashlib
import io
import json
import tarfile
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.rag.text_extractor import TextExtractor
from app.services.dila_cass_service import (
    canonical_number,
    parse_cass_xml,
    source_chunks,
    topic_scope,
)
from scripts.maintenance.import_dila_cass import Embeddings, plan, state_db


def xml(body="<p>Motifs 2026.</p>", formation="CHAMBRE_SOCIALE", bulletin="oui"):
    return f'''<TEXTE_JURI_JUDI><META><META_COMMUN>
    <ID>JURITEXT000007046800</ID></META_COMMUN><META_SPEC><META_JURI>
    <TITRE>Cour de cassation, chambre sociale</TITRE><DATE_DEC>2002-01-31</DATE_DEC>
    <JURIDICTION>Cour de cassation</JURIDICTION><SOLUTION>Cassation</SOLUTION>
    </META_JURI><META_JURI_JUDI><FORMATION>{formation}</FORMATION>
    <PUBLI_BULL publie="{bulletin}"/><NUMEROS_AFFAIRES>
    <NUMERO_AFFAIRE>00-12431</NUMERO_AFFAIRE></NUMEROS_AFFAIRES>
    </META_JURI_JUDI></META_SPEC></META><TEXTE><BLOC_TEXTUEL><CONTENU>
    {body}</CONTENU></BLOC_TEXTUEL><SOMMAIRE><SCT>CONTRAT DE TRAVAIL - RUPTURE</SCT>
    <ANA><CONTENU>Sommaire officiel complet.</CONTENU></ANA></SOMMAIRE>
    <CITATION_JP><CONTENU>Référence officielle.</CONTENU></CITATION_JP>
    </TEXTE></TEXTE_JURI_JUDI>'''.encode()


def test_source_text_numbers_and_all_sections_survive():
    raw = xml("<p>123</p><p>Article L. 1234-5</p><p>2026</p><p>« A — B »</p>")
    decision = parse_cass_xml(raw)
    assert decision.decision_date == date(2002, 1, 31)
    assert decision.xml_sha256 == hashlib.sha256(raw).hexdigest()
    for value in [
        "123",
        "2026",
        "Article L. 1234-5",
        "« A — B »",
        "Sommaire officiel complet.",
        "Référence officielle.",
    ]:
        assert value in decision.text
    assert decision.text_sha256 == hashlib.sha256(decision.text.encode()).hexdigest()
    assert TextExtractor().extract(raw, "xml") == decision.text


def test_table_merged_cells_empty_cells_and_order_are_preserved():
    raw = xml("""<p>Avant.</p><table><thead><tr><th colspan="2">Montants</th></tr></thead>
    <tbody><tr><td rowspan="2">Salaire</td><td>1 200,50 €</td></tr>
    <tr><td></td></tr></tbody></table><p>Après.</p>""")
    decision = parse_cass_xml(raw)
    assert decision.table_count == 1
    assert 'colspan="2"' in decision.text and 'rowspan="2"' in decision.text
    assert "<td></td>" in decision.text
    chunks = source_chunks(decision.text, max_tokens=20)
    assert "".join(chunks) == decision.text
    tables = [chunk for chunk in chunks if "<table>" in chunk]
    assert len(tables) == 1
    assert "1 200,50 €" in tables[0] and "</table>" in tables[0]
    assert decision.text.index("Avant.") < decision.text.index("Montants")
    assert decision.text.index("Montants") < decision.text.index("Après.")


@pytest.mark.parametrize(
    "formation,bulletin",
    [
        ("CHAMBRE_CRIMINELLE", "oui"),
        ("CHAMBRE_COMMERCIALE", "oui"),
        ("CHAMBRE_SOCIALE", "non"),
    ],
)
def test_other_chambers_and_unpublished_records_are_not_admitted(formation, bulletin):
    with pytest.raises(ValueError):
        parse_cass_xml(xml(formation=formation, bulletin=bulletin))


def test_active_content_is_not_executed_or_silently_removed():
    with pytest.raises(ValueError, match="active_content"):
        parse_cass_xml(xml("<script>alert(1)</script>"))


def test_external_entities_are_not_resolved(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("DO_NOT_READ")
    raw = b'<!DOCTYPE x [<!ENTITY stolen SYSTEM "' + str(secret).encode() + b'">]>'
    raw += xml("<p>&stolen;</p>")
    with pytest.raises(ValueError):
        parse_cass_xml(raw)


def test_unicode_chunk_boundaries_preserve_every_character():
    text = ("𝄞 🧑🏽‍💻 salaire 1 234,56 €\n\n" * 150) + "Dernier caractère : é."
    chunks = source_chunks(text, max_tokens=30)
    assert "".join(chunks) == text
    assert "�" not in "".join(chunks)


def test_oversized_table_is_reported_without_truncating():
    text = "<table><tr><td>" + "montant " * 300 + "</td></tr></table>"
    with pytest.raises(ValueError, match="table_exceeds"):
        source_chunks(text, max_table_tokens=20)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("00-12.431", "0012431"),
        ("00-12431", "0012431"),
        ("N°", None),
        ("", None),
    ],
)
def test_identity_normalization_does_not_make_placeholder_a_case_number(value, expected):
    assert canonical_number(value) == expected


def test_scope_uses_official_headings_and_retains_ambiguous_records_for_review():
    assert topic_scope(("1°\n CONTRAT DE TRAVAIL, EXECUTION - Salaire",)) == "admitted"
    assert topic_scope(("BAIL A FERME - Résiliation",)) == "review_outside_or_mixed_scope"
    assert topic_scope(("CASSATION - Moyen",)) == "review_generic_or_missing_topic"
    assert topic_scope(()) == "review_generic_or_missing_topic"
    assert topic_scope(("BAIL A LOYER", "CONTRAT DE TRAVAIL")) == "admitted"


class Tokenizer:
    def encode_batch(self, texts):
        return [SimpleNamespace(ids=list(range(len(value)))) for value in texts]


@pytest.mark.asyncio
async def test_embedding_cache_prevents_second_paid_call_and_disables_truncation(
    tmp_path, monkeypatch
):
    state = state_db(tmp_path)
    embedder = Embeddings(tmp_path, state, Tokenizer(), 100000, 1000)
    vectors = [[0.1] * 1024]
    response = httpx.Response(
        200,
        json={"data": [{"index": 0, "embedding": vectors[0]}], "usage": {"total_tokens": 4}},
        request=httpx.Request("POST", "https://example.test"),
    )
    embedder.client.post = AsyncMock(return_value=response)
    monkeypatch.setattr("scripts.maintenance.import_dila_cass.cost_tracker.log", AsyncMock())
    first = await embedder.get(["text"], ["00000000-0000-0000-0000-000000000001"])
    second = await embedder.get(["text"], ["00000000-0000-0000-0000-000000000001"])
    assert first == second == vectors
    assert embedder.client.post.await_count == 1
    assert embedder.client.post.call_args.kwargs["json"]["truncation"] is False
    assert state.execute("SELECT sum(actual) FROM requests").fetchone()[0] == 4
    await embedder.client.aclose()


@pytest.mark.asyncio
async def test_budget_is_reserved_before_call_and_survives_restart(tmp_path):
    state = state_db(tmp_path)
    state.execute("INSERT INTO requests VALUES ('old',998,998,'success',NULL)")
    state.commit()
    embedder = Embeddings(tmp_path, state, Tokenizer(), 100000, 1000)
    embedder.client.post = AsyncMock()
    with pytest.raises(ValueError, match="token budget"):
        await embedder.get(["text"], ["owner"])
    embedder.client.post.assert_not_called()
    await embedder.client.aclose()


@pytest.mark.asyncio
async def test_reconciliation_keeps_different_decision_dates_and_isolates_duplicates(
    tmp_path, monkeypatch
):
    from app.models.document import Document
    from tests.conftest import test_session_factory

    existing_id = uuid.uuid4()
    async with test_session_factory() as session:
        session.add(
            Document(
                id=existing_id,
                name="Existing",
                organisation_id=None,
                source_type="arret_cour_cassation",
                chambre="Chambre sociale",
                numero_pourvoi="00-12.431",
                date_decision=date(2002, 1, 31),
                storage_path="existing.txt",
                indexation_status="indexed",
                chunk_count=1,
            )
        )
        await session.commit()
    monkeypatch.setattr(
        "scripts.maintenance.import_dila_cass.async_session_factory", test_session_factory
    )
    package = tmp_path / "package.tar.gz"
    decisions = [
        xml(),
        xml()
        .replace(b"JURITEXT000007046800", b"JURITEXT000007046801")
        .replace(b"2002-01-31", b"2003-01-31"),
        xml()
        .replace(b"JURITEXT000007046800", b"JURITEXT000007046802")
        .replace(b"2002-01-31", b"2003-01-31"),
    ]
    with tarfile.open(package, "w:gz") as archive:
        for raw in decisions:
            decision = parse_cass_xml(raw)
            member = tarfile.TarInfo(decision.source_id + ".xml")
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
    state = state_db(tmp_path)
    await plan(tmp_path, package, state, Tokenizer())
    rows = {row["id"]: dict(row) for row in state.execute("SELECT * FROM items")}
    assert rows["JURITEXT000007046800"]["disposition"] == "existing"
    assert rows["JURITEXT000007046800"]["document_id"] == str(existing_id)
    assert rows["JURITEXT000007046801"]["disposition"] == "new"
    assert rows["JURITEXT000007046802"]["disposition"] == "review_archive_identity_conflict"
    assert json.loads((tmp_path / "plan.json").read_text())["parser_errors"] == []


@pytest.mark.asyncio
async def test_actual_pipeline_preserves_xml_numbers_and_table_chunks(monkeypatch):
    from app.models.document import Document
    from app.rag.ingestion import IngestionPipeline
    from scripts.maintenance.import_dila_cass import doc_for
    from tests.conftest import test_session_factory

    raw = xml(
        "<p>123</p><table><tr><th>Année</th><th>Montant</th></tr>"
        "<tr><td>2026</td><td>1 234,56 €</td></tr></table>"
    )
    decision = parse_cass_xml(raw)
    doc = doc_for(decision)
    async with test_session_factory() as session:
        session.add(doc)
        await session.commit()
    storage = Mock()
    storage.get_file_bytes.return_value = raw
    qdrant = Mock()
    qdrant.scroll.return_value = ([], None)
    monkeypatch.setattr("app.rag.ingestion.StorageService", lambda: storage)
    monkeypatch.setattr("app.rag.ingestion.get_qdrant_client", lambda: qdrant)
    monkeypatch.setattr("app.rag.ingestion.ensure_collection", lambda client: None)
    monkeypatch.setattr(
        "app.rag.ingestion.clean_text", Mock(side_effect=AssertionError("Source cleaned"))
    )
    monkeypatch.setattr(
        "app.rag.ingestion._get_sparse_vectors",
        lambda texts: [{"indices": [1], "values": [1.0]} for _ in texts],
    )

    async def embeddings(texts, *args, **kwargs):
        return [[0.1] * 1024 for _ in texts]

    async with test_session_factory() as session:
        pipeline = IngestionPipeline(embedding_provider=embeddings)
        await pipeline.ingest(doc.id, session)
        current = await session.get(Document, doc.id)
        assert current.indexation_status == "indexed"
    points = [point for call in qdrant.upsert.call_args_list for point in call.kwargs["points"]]
    header = IngestionPipeline._build_jurisprudence_header(doc) + "\n\n"
    assert "".join(point.payload["text"][len(header) :] for point in points) == decision.text
    assert any(point.payload["has_table"] for point in points)
    assert all(point.payload["organisation_id"] == "common" for point in points)
    assert all(point.payload["private"] is False for point in points)
