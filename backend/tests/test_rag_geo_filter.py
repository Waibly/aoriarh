from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.rag.geo_filter import is_territorial_specific
from app.rag.reranker import VoyageReranker
from app.rag.search import SearchResult

_DUMMY_REQUEST = httpx.Request("POST", "https://api.voyageai.com/v1/rerank")


# --- Détection --------------------------------------------------------------

class TestIsTerritorialSpecific:
    def test_mayotte_decret_detected_from_body(self):
        # Cas réel prod (décret 2026-82) : « Mayotte » n'est PAS dans le titre.
        text = (
            "L'article D. 241-7 s'applique à Mayotte, à l'exception de son III, "
            "sous réserve des adaptations suivantes : le salaire minimum de "
            "croissance en vigueur applicable à Mayotte ..."
        )
        doc_name = "Décret n° 2026-82 du 11 février 2026 portant application de l'article 23"
        assert is_territorial_specific(text, doc_name) is True

    def test_single_mention_with_restriction_cue(self):
        assert is_territorial_specific("Dispositions applicables à Saint-Martin.") is True

    def test_two_mentions_trigger(self):
        assert is_territorial_specific("En Guyane, le régime guyane est spécifique.") is True

    def test_national_text_with_incidental_mention_not_flagged(self):
        # Une seule mention, sans formule de restriction → national.
        text = "La réduction générale s'applique à l'ensemble des employeurs, y compris en Guadeloupe."
        assert is_territorial_specific(text) is False

    def test_enumeration_of_territories_is_national_extension(self):
        text = (
            "Le présent décret est applicable à Mayotte, à Saint-Martin et à "
            "Saint-Barthélemy dans les mêmes conditions."
        )
        assert is_territorial_specific(text) is False

    def test_plain_labor_law_text_not_flagged(self):
        text = "Le préavis de licenciement est de deux mois pour deux ans d'ancienneté (art. L.1234-1)."
        assert is_territorial_specific(text) is False

    def test_reunion_meeting_word_not_flagged(self):
        # « réunion » (du CSE) ne doit jamais déclencher.
        text = "L'employeur convoque une réunion du CSE, puis une seconde réunion sous huit jours."
        assert is_territorial_specific(text) is False


# --- Intégration reranker ---------------------------------------------------

def _make_result(text: str, doc_name: str = "test.pdf", doc_id: str = "d") -> SearchResult:
    return SearchResult(
        text=text, doc_name=doc_name, document_id=doc_id,
        source_type="decret", norme_niveau=5, norme_poids=0.8,
        chunk_index=0, score=0.0,
    )


def _mock_rerank_response(indices_scores):
    return {
        "data": [{"index": i, "relevance_score": s} for i, s in indices_scores],
        "usage": {"total_tokens": 100},
    }


@pytest.mark.asyncio
async def test_territorial_result_demoted_below_national():
    reranker = VoyageReranker()
    # Le texte Mayotte reçoit le MEILLEUR score Voyage (0.90), le national 0.60.
    mayotte = _make_result(
        "L'article D. 241-7 s'applique à Mayotte, sous réserve des adaptations suivantes.",
        doc_name="Décret Mayotte",
    )
    national = _make_result(
        "La réduction générale dégressive unique est calculée selon l'article D.241-7.",
        doc_name="Décret 2026-509",
    )
    results = [mayotte, national]

    mock_response = httpx.Response(
        200, json=_mock_rerank_response([(0, 0.90), (1, 0.60)]), request=_DUMMY_REQUEST,
    )
    with patch("app.rag.reranker.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        reranked = await reranker.rerank("recalcul coût employeur SMIC", results, top_k=2)

    # Sans pénalité, Mayotte serait #1 (0.90). Avec ×0.5 → 0.45 < 0.60 : le
    # national repasse devant.
    assert reranked[0].doc_name == "Décret 2026-509"
    assert reranked[1].doc_name == "Décret Mayotte"
    assert reranked[1].score == pytest.approx(0.45)
