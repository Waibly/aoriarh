import copy
import hashlib
import json
import sqlite3
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from qdrant_client.models import Record
from sqlalchemy import func, select

from app.models.document import Document
from app.rag.agent import RAGAgent
from app.rag.reranker import document_rerank_input
from app.rag.search import SearchResult
from app.services.judilibre_service import JudilibreService
from app.services.jurisprudence_publication import (
    BULLETIN,
    BULLETIN_RAPPORT,
    RAPPORT,
    judilibre_publication_label,
    publication_significance,
)
from scripts.maintenance import backfill_cassation_report as backfill
from tests.conftest import test_session_factory


@pytest.mark.parametrize(
    "codes,label",
    [
        (["b", "r"], BULLETIN_RAPPORT),
        (["r", "b", "c"], BULLETIN_RAPPORT),
        (["B", "R"], BULLETIN_RAPPORT),
        (["b"], BULLETIN),
        (["r"], RAPPORT),
        (["n"], "Inédit"),
        ([], "Inédit"),
        ("P+B+R+I", "P+B+R+I"),
    ],
)
def test_official_publication_codes_are_preserved_without_guessing_historical_sigles(codes, label):
    original = copy.deepcopy(codes)
    assert judilibre_publication_label(codes) == label
    assert len(label) <= 50
    assert codes == original


def test_parser_retains_both_official_labels_and_original_source_text():
    raw = dict(
        id="a" * 24,
        jurisdiction="cc",
        chamber="soc",
        number="14-27.266",
        decision_date="2016-07-06",
        publication=["b", "r"],
        text="  Source\n123\n",
    )
    parsed = JudilibreService._parse_decision(raw)
    assert parsed.publication == BULLETIN_RAPPORT
    assert parsed.text == raw["text"]
    assert raw["publication"] == ["b", "r"]
    assert publication_significance("P+B+R+I", "arret_cour_cassation") is None
    assert publication_significance(BULLETIN_RAPPORT, "arret_cour_appel") is None


def test_reranking_and_generation_receive_publication_context_with_untouched_passage():
    body = "  Source\n123\n<table><tr><td>42</td></tr></table>\n"
    result = SearchResult(
        body,
        "Arrêt",
        "id",
        "arret_cour_cassation",
        4,
        0.85,
        0,
        0.75,
        juridiction="Cour de cassation",
        chambre="Chambre sociale",
        numero_pourvoi="14-27.266",
        date_decision="2016-07-06",
        publication=BULLETIN_RAPPORT,
    )
    metadata, text = document_rerank_input(result).split("\n\nPassage original :\n", 1)
    metadata = json.loads(metadata)
    assert metadata["publication"] == BULLETIN_RAPPORT
    assert metadata["date_decision"] == "2016-07-06"
    assert "Rapport annuel" in metadata["portee_jurisprudentielle"]
    assert text == body
    context = RAGAgent.__new__(RAGAgent)._build_context([result])
    assert BULLETIN_RAPPORT in context and "2016-07-06" in context
    assert "Portée jurisprudentielle officielle" in context
    assert context.endswith(body)
    assert result.score == 0.75 and result.norme_poids == 0.85 and result.text == body


class Lock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def scalar(self, *args):
        return True


class Points:
    def __init__(self, records):
        self.records = records
        self.writes = 0

    def scroll(self, *args, **kwargs):
        assert kwargs["with_vectors"] is True
        return copy.deepcopy(self.records), None

    def set_payload(self, *args, payload, points, wait):
        assert wait is True
        assert set(points) == {p.id for p in self.records}
        for p in self.records:
            p.payload.update(payload)
        self.writes += 1


@pytest.mark.asyncio
async def test_backfill_updates_only_publication_and_recovers_partial_metadata_write(
    tmp_path, monkeypatch
):
    raw = b"Source originale\n123\n"
    identifier = uuid.uuid4()
    async with test_session_factory() as session:
        session.add(
            Document(
                id=identifier,
                name="Original",
                source_type="arret_cour_cassation",
                juridiction="Cour de cassation",
                chambre="Chambre sociale",
                date_decision=date(2016, 7, 6),
                numero_pourvoi="14-27266 et autres",
                organisation_id=None,
                storage_path="common/dila/cass/source.xml",
                file_hash=hashlib.sha256(raw).hexdigest(),
                file_format="xml",
                indexation_status="indexed",
                chunk_count=1,
                publication=BULLETIN,
                norme_niveau=4,
                norme_poids=0.85,
            )
        )
        await session.commit()
    record = Record(
        id=str(uuid.uuid4()),
        payload=dict(
            document_id=str(identifier),
            organisation_id="common",
            source_type="arret_cour_cassation",
            private=False,
            publication=BULLETIN,
            chunk_index=0,
            text="Source originale\n123\n",
        ),
        vector={"dense": [0.125] * 1024, "sparse-bm25": dict(indices=[1, 9], values=[0.5, 1.0])},
    )
    original_vectors = copy.deepcopy(record.vector)
    points = Points([record])
    storage = Mock()
    storage.get_file_bytes_bounded.return_value = raw
    storage.put_file_bytes.side_effect = AssertionError("Source write forbidden")
    monkeypatch.setattr(backfill, "async_session_factory", test_session_factory)
    monkeypatch.setattr(backfill, "StorageService", lambda: storage)
    monkeypatch.setattr(backfill, "get_qdrant_client", lambda: points)
    monkeypatch.setattr(backfill, "engine", SimpleNamespace(begin=Lock))
    inventory = tmp_path / "inventory.sqlite3"
    s = sqlite3.connect(inventory)
    s.execute("create table state (key text,value text)")
    s.execute("insert into state values('complete','1')")
    s.execute("create table items (id text,chamber text,meta text)")
    s.execute(
        "insert into items values (?,?,?)",
        (
            "a" * 24,
            "soc",
            json.dumps(
                dict(
                    jurisdiction="cc",
                    chamber="soc",
                    decision_date="2016-07-06",
                    publication=["b", "r"],
                    number="14-27.266",
                    numbers=["14-27.266"],
                )
            ),
        ),
    )
    s.commit()
    s.close()
    await backfill.plan(tmp_path, inventory, 1)
    plan = json.loads((tmp_path / "plan.json").read_text())
    # A vector change must stop the operation before any metadata write.
    points.records[0].vector["dense"][0] = 0.25
    with pytest.raises(ValueError, match="changed"):
        await backfill.apply(tmp_path, plan)
    assert points.writes == 0
    points.records[0].vector["dense"][0] = 0.125
    # Simulate Qdrant succeeding before a previous PostgreSQL commit failed.
    points.records[0].payload["publication"] = BULLETIN_RAPPORT
    await backfill.apply(tmp_path, plan)
    await backfill.verify(tmp_path, plan)
    await backfill.apply(tmp_path, plan)
    await backfill.verify(tmp_path, plan)
    async with test_session_factory() as session:
        doc = await session.get(Document, identifier)
        assert doc.publication == BULLETIN_RAPPORT
        assert doc.file_hash == hashlib.sha256(raw).hexdigest()
        assert (doc.norme_poids, doc.chunk_count, doc.indexation_status) == (0.85, 1, "indexed")
        assert await session.scalar(select(func.count()).select_from(Document)) == 1
    assert points.records[0].vector == original_vectors
    assert points.records[0].payload["text"] == record.payload["text"]
    storage.put_file_bytes.assert_not_called()
    assert json.loads((tmp_path / "verification.json").read_text())["external_model_calls"] == 0


def test_private_point_is_rejected_before_publication_update():
    doc = SimpleNamespace(id=uuid.uuid4(), chunk_count=1)
    point = Record(
        id=str(uuid.uuid4()),
        vector=[0.1] * 1024,
        payload=dict(
            document_id=str(doc.id),
            organisation_id="private-org",
            source_type="arret_cour_cassation",
            private=True,
            chunk_index=0,
        ),
    )
    with pytest.raises(ValueError, match="Invalid public"):
        backfill.point_snapshot([point], doc)
