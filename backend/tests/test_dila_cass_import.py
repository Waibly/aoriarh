import base64
import hashlib
import io
import json
import struct
import tarfile
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from lxml import etree

from app.rag.text_extractor import TextExtractor
from app.services.dila_cass_service import (
    canonical_number,
    number_aliases,
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


def test_joined_official_case_references_are_matched_without_changing_sources():
    assert {"0444103", "0444507"} <= number_aliases("04-44.1030444507")
    assert "1427266" in number_aliases("14-27266 et autres")
    assert {"0444103", "0444507"} <= number_aliases("04-44103 à 04-44507")
    assert "6240650" in number_aliases("62-40650 bis")
    assert "0444104" not in number_aliases("04-44103 à 04-44507")
    assert number_aliases("N°") == set()


def test_empty_original_body_cannot_be_replaced_by_an_official_summary():
    with pytest.raises(ValueError, match="empty_decision_body"):
        parse_cass_xml(xml(body=""))


def test_scope_uses_official_headings_and_retains_ambiguous_records_for_review():
    assert topic_scope(("1°\n CONTRAT DE TRAVAIL, EXECUTION - Salaire",)) == "admitted"
    assert topic_scope(("BAIL A FERME - Résiliation",)) == "review_outside_or_mixed_scope"
    assert topic_scope(("CASSATION - Moyen",)) == "review_generic_or_missing_topic"
    assert topic_scope(()) == "review_generic_or_missing_topic"
    assert topic_scope(("BAIL A LOYER", "CONTRAT DE TRAVAIL")) == "admitted"
    assert topic_scope(("FRANCE D'OUTRE-MER - TERRITOIRES - CONTRAT DE TRAVAIL",)) == "admitted"
    assert (
        topic_scope(("BAIL A FERME - REPRISE - TRAVAIL DE SURVEILLANCE ET DE DIRECTION",))
        == "review_outside_or_mixed_scope"
    )
    assert (
        topic_scope(("BAIL A LOYER - BESOINS PROFESSIONNELS - REPRESENTANT DE COMMERCE",))
        == "review_outside_or_mixed_scope"
    )
    assert (
        topic_scope(
            (
                "SECURITE SOCIALE - PENSION - NON-SALARIES",
                "SECURITE SOCIALE CONTENTIEUX",
            )
        )
        == "review_outside_or_mixed_scope"
    )
    assert (
        topic_scope(
            (
                "SECURITE SOCIALE, ASSURANCES DES NON-SALARIES - PENSION",
                "CONTRAT DE TRAVAIL - ASSUJETTISSEMENT",
            )
        )
        == "admitted"
    )


@pytest.mark.parametrize(
    "topic",
    [
        "ELECTIONS - Comités d'entreprise - Représentativité",
        "ELECTIONS - Délégués du personnel - Désignation",
        "AGRICULTURE - ACCIDENT DU TRAVAIL - Indemnisation",
        "QUESTION PRIORITAIRE DE CONSTITUTIONNALITE - Code du travail - Article L. 2314-3",
        "CHEMIN DE FER - S N C F - PERSONNEL - Discipline",
    ],
)
def test_explicit_historical_employment_headings_remain_admitted(topic):
    assert topic_scope((topic,)) == "admitted"


def test_unrelated_elections_and_rural_matters_are_not_employment_headings():
    assert topic_scope(("ELECTIONS - MUTUALITE - ASSEMBLEE GENERALE",)).startswith("review")
    assert topic_scope(("AGRICULTURE - BAIL A FERME - REPRISE",)).startswith("review")


def test_embedding_transport_preserves_float32_and_rejects_invalid_vectors():
    from scripts.maintenance.import_dila_cass import decode_embedding

    vector = [0.125, -0.5, 0.0, 1.0] * 256
    assert decode_embedding(base64.b64encode(struct.pack("<1024f", *vector)).decode()) == vector
    with pytest.raises(ValueError, match="byte count"):
        decode_embedding(base64.b64encode(b"short").decode())
    with pytest.raises(ValueError, match="Non-finite"):
        decode_embedding(base64.b64encode(struct.pack("<1024f", *([float("nan")] * 1024))).decode())


class Tokenizer:
    def encode_batch(self, texts):
        return [SimpleNamespace(ids=list(range(len(value)))) for value in texts]


@pytest.mark.asyncio
async def test_embedding_cache_prevents_second_paid_call_and_disables_truncation(
    tmp_path, monkeypatch
):
    state = state_db(tmp_path)
    embedder = Embeddings(tmp_path, state, Tokenizer(), 100000, 1000)
    vectors = [[0.125] * 1024]
    response = httpx.Response(
        200,
        json={
            "data": [
                {
                    "index": 0,
                    "embedding": base64.b64encode(struct.pack("<1024f", *vectors[0])).decode(),
                }
            ],
            "usage": {"total_tokens": 4},
        },
        request=httpx.Request("POST", "https://example.test"),
    )
    embedder.client.post = AsyncMock(return_value=response)
    monkeypatch.setattr("scripts.maintenance.import_dila_cass.cost_tracker.log", AsyncMock())
    first = await embedder.get(["text"], ["00000000-0000-0000-0000-000000000001"])
    second = await embedder.get(["text"], ["00000000-0000-0000-0000-000000000001"])
    assert first == second == vectors
    assert embedder.client.post.await_count == 1
    assert embedder.client.post.call_args.kwargs["json"]["truncation"] is False
    assert embedder.client.post.call_args.kwargs["json"]["encoding_format"] == "base64"
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
async def test_transport_timeout_requires_investigation_before_another_paid_call(tmp_path):
    state = state_db(tmp_path)
    embedder = Embeddings(tmp_path, state, Tokenizer(), 100000, 1000)
    embedder.client.post = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
    with pytest.raises(httpx.ReadTimeout):
        await embedder.get(["text"], ["owner"])
    assert state.execute("SELECT status FROM requests").fetchone()[0] == "uncertain"
    embedder.next_request = 0
    with pytest.raises(ValueError, match="uncertain paid request"):
        await embedder.get(["text"], ["owner"])
    assert embedder.client.post.await_count == 1
    await embedder.client.aclose()


@pytest.mark.asyncio
async def test_concurrent_batches_settle_in_flight_work_and_stop_after_failure():
    import asyncio

    from scripts.maintenance.import_dila_cass import run_batches

    started = []
    settled = []
    both_started = asyncio.Event()

    async def handler(group):
        started.append(group)
        if len(started) == 2:
            both_started.set()
        await both_started.wait()
        if group == 0:
            raise ValueError("technical failure")
        await asyncio.sleep(0)
        settled.append(group)

    with pytest.raises(ValueError, match="technical failure"):
        await run_batches(range(10), handler, 2)
    assert started == [0, 1]
    assert settled == [1]


@pytest.mark.asyncio
async def test_reconciliation_keeps_different_decision_dates_and_isolates_duplicates(
    tmp_path, monkeypatch
):
    from app.models.document import Document
    from scripts.maintenance.import_dila_cass import doc_for
    from tests.conftest import test_session_factory

    existing_id = uuid.uuid4()
    resumable_raw = (
        xml()
        .replace(b"JURITEXT000007046800", b"JURITEXT000007046804")
        .replace(b"2002-01-31", b"2004-01-31")
    )
    async with test_session_factory() as session:
        session.add(doc_for(parse_cass_xml(resumable_raw)))
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
        xml(body="").replace(b"JURITEXT000007046800", b"JURITEXT000007046803"),
        resumable_raw,
    ]
    with tarfile.open(package, "w:gz") as archive:
        for raw in decisions:
            identifier = etree.fromstring(raw).findtext("META/META_COMMUN/ID")
            member = tarfile.TarInfo(identifier + ".xml")
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
    state = state_db(tmp_path)
    await plan(tmp_path, package, state, Tokenizer())
    rows = {row["id"]: dict(row) for row in state.execute("SELECT * FROM items")}
    assert rows["JURITEXT000007046800"]["disposition"] == "existing"
    assert rows["JURITEXT000007046800"]["document_id"] == str(existing_id)
    assert rows["JURITEXT000007046801"]["disposition"] == "new"
    assert rows["JURITEXT000007046802"]["disposition"] == "review_archive_identity_conflict"
    assert rows["JURITEXT000007046803"]["disposition"] == "review_source_body_missing"
    assert rows["JURITEXT000007046804"]["disposition"] == "new"
    assert json.loads((tmp_path / "plan.json").read_text())["parser_errors"] == []


def test_exact_duplicate_reconciliation_preserves_distinct_cases_and_batch_slots(tmp_path):
    from scripts.maintenance.import_dila_cass import reconcile_exact_duplicates

    state = state_db(tmp_path)
    for identifier, day, numbers in [
        ("a", "1967-10-04", []),
        ("b", "1967-10-04", []),
        ("c", "1967-10-04", ["79-15.417"]),
        ("d", "1967-10-04", ["79-15.735"]),
        ("e", "1968-10-04", []),
    ]:
        state.execute(
            "INSERT INTO items VALUES (?,?,?,?,?,?,NULL)",
            (
                identifier,
                b"xml",
                json.dumps({"date": day, "numbers": numbers, "text_sha256": "same"}),
                identifier,
                "new",
                "pending",
            ),
        )
    state.commit()
    assert reconcile_exact_duplicates(tmp_path, state) == [
        {"source_id": "b", "same_text_and_identity_as": "a"}
    ]
    assert state.execute("SELECT disposition FROM items WHERE id='b'").fetchone()[0] == (
        "review_exact_duplicate"
    )
    assert [
        row[0]
        for row in state.execute(
            "SELECT id FROM items WHERE disposition IN ('new','review_exact_duplicate') ORDER BY id"
        )
    ] == list("abcde")
    assert len(reconcile_exact_duplicates(tmp_path, state)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("publication", ["oui", "non"])
async def test_actual_pipeline_preserves_xml_numbers_and_table_chunks(monkeypatch, publication):
    from app.models.document import Document
    from app.rag.ingestion import IngestionPipeline
    from scripts.maintenance.import_dila_cass import doc_for
    from tests.conftest import test_session_factory

    raw = xml(
        "<p>123</p><table><tr><th>Année</th><th>Montant</th></tr>"
        "<tr><td>2026</td><td>1 234,56 €</td></tr></table>", bulletin=publication
    )
    from app.services.dila_cass_service import parse_social_xml

    decision = parse_social_xml(raw)
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
    assert all(point.payload["source_xml_sha256"] == doc.file_hash for point in points)
    assert all(point.payload["numero_pourvois"] == ["00-12431"] for point in points)
    assert all(point.payload["source_url"] == doc.source_url for point in points)
