"""CGCT registration, original source ingestion and scoped exact lookup."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from qdrant_client import QdrantClient, models

from app.rag.ingestion import ARTICLE_AWARE_SOURCE_TYPES
from app.rag.norme_hierarchy import DOCUMENT_TYPE_HIERARCHY
from app.rag.parent_expansion import fetch_by_identifiers, reference_source_types
from app.rag.qdrant_store import COLLECTION_NAME
from app.rag.source_intent import detect_source_intent
from app.services.legi_service import SYNCABLE_CODES, LegiService

CODE = "code_general_collectivites_territoriales"


async def test_cgct_sync_routes_original_articles_to_legislative_and_regulatory_documents():
    service = LegiService()
    service._client_id = service._client_secret = "unit-test"
    service._api_post = AsyncMock(
        return_value={
            "sections": [
                {
                    "title": "PARTIE LÉGISLATIVE",
                    "articles": [
                        {
                            "num": "L2333-87",
                            "etat": "VIGUEUR",
                            "texte": "<p>Règle FPS originale.</p>",
                        },
                    ],
                },
                {
                    "title": "PARTIE RÉGLEMENTAIRE",
                    "articles": [
                        {
                            "num": "R2333-120-1",
                            "etat": "VIGUEUR",
                            "texte": "<p>Procédure originale.</p>",
                        },
                    ],
                },
            ]
        }
    )
    service._sync_part = AsyncMock(side_effect=[(True, "leg-doc"), (True, "reg-doc")])
    with patch("app.services.storage_service.StorageService"):
        result = await service.sync_code(AsyncMock(), uuid.uuid4(), CODE)
    assert result.errors == 0
    assert result.articles_legislatif == result.articles_reglementaire == 1
    calls = service._sync_part.await_args_list
    assert [c.kwargs["source_type"] for c in calls] == [CODE, CODE + "_reglementaire"]
    assert calls[0].kwargs["articles"][0]["content"] == "Règle FPS originale."
    assert calls[1].kwargs["articles"][0]["content"] == "Procédure originale."
    assert service._api_post.call_args.args[2]["textId"] == SYNCABLE_CODES[CODE]["text_id"]
    for kind, level in [(CODE, 3), (CODE + "_reglementaire", 5)]:
        assert kind in ARTICLE_AWARE_SOURCE_TYPES
        assert DOCUMENT_TYPE_HIERARCHY[kind]["niveau"] == level


@pytest.mark.parametrize("label", ["CGCT", "Code général des collectivités territoriales"])
async def test_cgct_reference_resolves_only_authorized_code_passages(label):
    index = QdrantClient(":memory:")
    index.create_collection(
        COLLECTION_NAME, vectors_config=models.VectorParams(size=1, distance=models.Distance.COSINE)
    )
    index.upsert(
        COLLECTION_NAME,
        [
            models.PointStruct(
                id=n,
                vector=[1.0],
                payload={
                    "document_id": f"doc-{n}",
                    "organisation_id": org,
                    "source_type": kind,
                    "article_nums": ["L2333-87"],
                    "chunk_index": 0,
                    "text": text,
                    "doc_name": "CGCT",
                    "norme_niveau": 3,
                    "norme_poids": 0.9,
                },
            )
            for n, (org, kind, text) in enumerate(
                [
                    ("common", CODE, "Texte officiel FPS"),
                    ("other-tenant", CODE, "Texte privé interdit"),
                    ("common", "code_travail", "Autre Code"),
                ]
            )
        ],
    )
    question = f"article L2333-87 du {label}"
    scopes = reference_source_types(question)
    assert set(scopes["L2333-87"]) == {CODE, CODE + "_reglementaire"}
    found = await fetch_by_identifiers(
        index,
        {"article_nums": ["L2333-87"], "numero_pourvoi": []},
        "my-tenant",
        article_source_filters=scopes,
    )
    assert [r.text for r in found] == ["Texte officiel FPS"]
    directed = detect_source_intent(f"Que dit le {label} sur le FPS ?")
    assert any(CODE in kinds for kinds, _ in directed)
