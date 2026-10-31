import hashlib
import io
import json
import tarfile
from datetime import UTC
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.rag.parent_expansion import _payload_to_result, fetch_by_identifiers
from app.rag.reranker import document_rerank_input
from app.rag.text_extractor import TextExtractor
from app.services.dila_cass_service import (
    parse_cass_xml,
    parse_inca_xml,
    reconcile_source_references,
    reconciliation_bytes,
)
from app.services.dila_jurisprudence_metadata import source_metadata
from app.services.jurisprudence_references import social_case_references
from scripts.maintenance.import_dila_cass import doc_for, plan, prepared_chunks, state_db


def source(*, publication="non", chamber="CHAMBRE_SOCIALE"):
    return f'''<TEXTE_JURI_JUDI><META><META_COMMUN>
    <ID>JURITEXT000020424075</ID></META_COMMUN><META_SPEC><META_JURI>
    <TITRE>Cour de cassation, chambre sociale, 18 mars 2009, 07-44.780, Inédit</TITRE>
    <DATE_DEC>2009-03-18</DATE_DEC><JURIDICTION>Cour de cassation</JURIDICTION>
    <SOLUTION>Cassation</SOLUTION></META_JURI><META_JURI_JUDI>
    <FORMATION>{chamber}</FORMATION><PUBLI_BULL publie="{publication}"/>
    <NUMEROS_AFFAIRES><NUMERO_AFFAIRE>07-44780</NUMERO_AFFAIRE>
    <NUMERO_AFFAIRE>07-44781</NUMERO_AFFAIRE></NUMEROS_AFFAIRES>
    <FORM_DEC_ATT>Cour d'appel de Saint-Denis de la Réunion</FORM_DEC_ATT>
    <DATE_DEC_ATT>2007-09-26</DATE_DEC_ATT></META_JURI_JUDI></META_SPEC></META>
    <TEXTE><BLOC_TEXTUEL><CONTENU><p>Contrat de travail. 123.</p>
    <p>Soc., 13 novembre 1996, pourvoi n° 94-13.187.</p>
    <table><tr><td colspan="2">Salaire</td></tr><tr><td>1 234,56 €</td><td></td></tr></table>
    <p>Dernier motif, sans correction.</p></CONTENU></BLOC_TEXTUEL><SOMMAIRE/>
    </TEXTE></TEXTE_JURI_JUDI>'''.encode()


def test_unpublished_status_is_explicit_and_bulletin_contract_is_preserved():
    raw = source()
    decision = parse_inca_xml(raw)
    assert decision.publication == "Inédit"
    with pytest.raises(ValueError, match="not_published_in_bulletin"):
        parse_cass_xml(raw)
    with pytest.raises(ValueError, match="not_unpublished"):
        parse_inca_xml(source(publication="oui"))
    with pytest.raises(ValueError, match="out_of_social"):
        parse_inca_xml(source(chamber="CHAMBRE_CRIMINELLE"))


def test_inca_source_retains_text_table_metadata_and_all_case_aliases():
    raw = source()
    decision = parse_inca_xml(raw)
    doc = doc_for(decision)
    assert doc.storage_path.startswith("common/dila/inca/")
    assert doc.publication == "Inédit"
    assert doc.file_hash == hashlib.sha256(raw).hexdigest()
    assert TextExtractor().extract(raw, "xml") == decision.text
    chunks = prepared_chunks(decision, doc)
    assert any('colspan="2"' in chunk and "1 234,56 €" in chunk for chunk in chunks)
    meta = source_metadata(raw)
    assert meta["numero_pourvois"] == ["07-44780", "07-44781"]
    assert {"0744780", "0744781"} <= set(meta["numero_pourvoi_aliases"])
    assert meta["documentary_topics"] == []
    assert meta["appealed_decision_date"] == "2007-09-26"
    assert meta["source_xml_sha256"] == doc.file_hash
    assert meta["social_case_citations"][0]["date"] == "1996-11-13"
    assert "applicable" not in meta and "current_law" not in meta


def test_literal_citations_keep_offsets_and_do_not_infer_unstated_case_or_status():
    text = (
        "Voir Soc., 13 novembre 1996, pourvoi n° 94-13.187 "
        "et chambre sociale, 1er mars 1990, n° 88-40.121."
    )
    refs = social_case_references(text)
    assert [r["date"] for r in refs] == ["1996-11-13", "1990-03-01"]
    assert all(text[r["start"] : r["end"]] == r["literal"] for r in refs)
    assert social_case_references("Crim., 13 novembre 1996, n° 94-13.187") == []
    assert social_case_references("Soc., 31 février 1996, n° 94-13.187") == []
    assert social_case_references("Soc., 13 novembre 1996, Bulletin V n° 386") == []


def test_official_metadata_reaches_reranker_with_original_body_intact():
    raw = source()
    body = parse_inca_xml(raw).text
    result = _payload_to_result(
        {"text": body, "source_type": "arret_cour_cassation", **source_metadata(raw)}
    )
    assert result.numero_pourvois == ["07-44780", "07-44781"]
    assert result.source_url.endswith("JURITEXT000020424075")
    supplied = document_rerank_input(result)
    assert supplied.endswith(body)
    assert "07-44781" in supplied


def test_large_joined_case_sets_keep_exact_identifiers_without_bloating_model_metadata():
    numbers = [f"10-{12000 + i}" for i in range(920)]
    result = _payload_to_result(
        {
            "text": "Texte original intégral.",
            "source_type": "arret_cour_cassation",
            "numero_pourvois": numbers,
            "numero_pourvoi": numbers[0],
        }
    )
    supplied = document_rerank_input(result)
    meta = json.loads(supplied.split("\n\nPassage original :\n", 1)[0])
    assert meta["nombre_references_pourvoi_renseignees"] == 920
    assert meta["numero_pourvoi"] == numbers[0]
    assert "numero_pourvois" not in meta
    assert result.numero_pourvois == numbers
    assert supplied.endswith(result.text)


@pytest.mark.asyncio
async def test_secondary_case_alias_lookup_keeps_organisation_access_filter():
    client = MagicMock()
    client.scroll.return_value = ([], None)
    await fetch_by_identifiers(
        client, {"numero_pourvoi": ["07-44.781"], "article_nums": []}, "org-1"
    )
    flt = client.scroll.call_args.kwargs["scroll_filter"]
    serialized = flt.model_dump_json()
    assert "numero_pourvoi_aliases" in serialized and "0744781" in serialized
    assert "organisation_id" in serialized and "org-1" in serialized
    assert "private" in serialized


@pytest.mark.asyncio
async def test_inca_plan_requires_matching_immutable_subject_evidence(tmp_path, monkeypatch):
    from tests.conftest import test_session_factory

    raw = source()
    archive = tmp_path / "selected.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        member = tarfile.TarInfo("JURITEXT000020424075.xml")
        member.size = len(raw)
        output.addfile(member, io.BytesIO(raw))
    monkeypatch.setattr(
        "scripts.maintenance.import_dila_cass.async_session_factory", test_session_factory
    )
    state = state_db(tmp_path)
    tokenizer = SimpleNamespace(
        encode_batch=lambda texts: [SimpleNamespace(ids=[1, 2]) for _ in texts]
    )
    with pytest.raises(ValueError, match="immutable source qualification"):
        await plan(tmp_path, archive, state, tokenizer, source_parser=parse_inca_xml, selection={})
    evidence = {
        "JURITEXT000020424075": {
            "scope": "admitted",
            "xml_sha256": hashlib.sha256(raw).hexdigest(),
            "reason": "literal primary employment reference",
        }
    }
    await plan(
        tmp_path, archive, state, tokenizer, source_parser=parse_inca_xml, selection=evidence
    )
    stored = state.execute("SELECT meta,disposition FROM items").fetchone()
    assert stored[1] == "new"
    assert json.loads(stored[0])["selection_evidence"] == evidence["JURITEXT000020424075"]
    state.close()


@pytest.mark.asyncio
async def test_all_joined_case_references_survive_incremental_sync_and_retirement():
    from datetime import datetime

    from app.services.document_case_references import (
        find_existing_social_case,
        store_case_references,
    )
    from app.services.judilibre_service import JudilibreService
    from tests.conftest import test_session_factory

    decision = parse_inca_xml(source())
    document = doc_for(decision)
    async with test_session_factory() as session:
        session.add(document)
        await session.flush()
        await store_case_references(session, document, decision.numbers)
        await store_case_references(session, document, decision.numbers)
        await session.commit()
        found = await find_existing_social_case(session, decision.decision_date, ["07-44.781"])
        assert found == {document.id}
        keys, _ = await JudilibreService()._get_existing_social_cassation(session)
        assert ("2009-03-18", "0744781") in keys
        document.retired_at = datetime.now(UTC)
        await session.commit()
        assert not await find_existing_social_case(session, decision.decision_date, ["07-44.781"])


@pytest.mark.asyncio
async def test_reference_registry_cannot_publish_private_document_identity():
    import uuid

    from app.services.document_case_references import store_case_references
    from tests.conftest import test_session_factory

    decision = parse_inca_xml(source())
    document = doc_for(decision)
    document.organisation_id = uuid.uuid4()
    async with test_session_factory() as session:
        with pytest.raises(ValueError, match="only accepts public"):
            await store_case_references(session, document, decision.numbers)


def reconciliation(decision):
    return {
        "schema": "official-case-reference-reconciliation-v1",
        "source_identifier": decision.source_id,
        "source_xml_sha256": decision.xml_sha256,
        "decision_date": str(decision.decision_date),
        "verified_numbers": [decision.numbers[0]],
        "verified_title": "Official primary case reference",
        "official_decision_url": "https://www.courdecassation.fr/decision/" + "f" * 24,
        "reason": "Explicit source reconciliation fixture, no generated text",
    }


def test_explicit_reference_reconciliation_preserves_original_source_and_declared_numbers():
    raw = source()
    original = parse_inca_xml(raw)
    proof = reconciliation(original)
    corrected = reconcile_source_references(original, proof)
    assert corrected.text == original.text and corrected.xml_sha256 == original.xml_sha256
    assert corrected.numbers == ("07-44780",)
    meta = source_metadata(raw, reference_reconciliation=proof)
    assert meta["numero_pourvois"] == ["07-44780"]
    assert meta["source_declared_case_numbers"] == ["07-44780", "07-44781"]
    assert meta["case_reference_reconciliation"] == proof
    assert doc_for(corrected).storage_path.startswith("common/dila/inca/reconciled/")
    with pytest.raises(ValueError, match="Invalid explicit"):
        reconcile_source_references(original, {**proof, "source_xml_sha256": "0" * 64})
    with pytest.raises(ValueError, match="Invalid explicit"):
        reconcile_source_references(original, {**proof, "verified_numbers": ["99-99999"]})


@pytest.mark.asyncio
@pytest.mark.parametrize("tampered", [False, True])
async def test_pipeline_checks_sealed_reference_reconciliation_before_any_embedding(
    monkeypatch, tampered
):
    from unittest.mock import AsyncMock

    from app.rag.ingestion import IngestionPipeline
    from tests.conftest import test_session_factory

    raw = source()
    original = parse_inca_xml(raw)
    proof = reconciliation(original)
    corrected = reconcile_source_references(original, proof)
    document = doc_for(corrected)
    storage = MagicMock()
    storage.get_file_bytes.return_value = raw
    identity = reconciliation_bytes(proof)
    storage.get_file_bytes_bounded.return_value = identity + (b" " if tampered else b"")
    client = MagicMock()
    client.scroll.return_value = ([], None)
    embeddings = AsyncMock(return_value=[[0.1] * 1024] * len(prepared_chunks(corrected, document)))
    monkeypatch.setattr("app.rag.ingestion.clean_text", MagicMock(side_effect=AssertionError()))
    monkeypatch.setattr(
        "app.rag.ingestion._get_sparse_vectors",
        lambda texts: [{"indices": [1], "values": [1.0]} for _ in texts],
    )
    async with test_session_factory() as session:
        session.add(document)
        await session.commit()
        pipeline = IngestionPipeline(embeddings, storage=storage, qdrant_client=client)
        await pipeline.ingest(document.id, session)
        await session.refresh(document)
        if tampered:
            assert document.indexation_status == "error"
            embeddings.assert_not_called()
            client.upsert.assert_not_called()
        else:
            assert document.indexation_status == "indexed"
            points = [p for call in client.upsert.call_args_list for p in call.kwargs["points"]]
            assert all(p.payload["numero_pourvois"] == ["07-44780"] for p in points)
            assert all(
                p.payload["source_declared_case_numbers"] == ["07-44780", "07-44781"]
                for p in points
            )
