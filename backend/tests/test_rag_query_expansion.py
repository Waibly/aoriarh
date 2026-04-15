from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag.agent import RAGAgent
from app.rag.search import SearchResult


def _make_result(
    text: str, score: float, doc_id: str = "doc1", chunk: int = 0,
) -> SearchResult:
    return SearchResult(
        text=text,
        doc_name="test.pdf",
        document_id=doc_id,
        source_type="code_travail",
        norme_niveau=4,
        norme_poids=0.8,
        chunk_index=chunk,
        score=score,
    )


def _mock_llm_response(content: str):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = content
    return mock_response


@pytest.fixture
def agent():
    with patch("app.rag.agent._search_engine"), \
         patch("app.rag.agent.get_reranker"):
        a = RAGAgent()
        a.llm = MagicMock()
        a.llm.chat = MagicMock()
        a.llm.chat.completions = MagicMock()
        a.llm.chat.completions.create = AsyncMock()
        return a


class TestParseVariants:
    def test_parse_5_variants(self):
        content = (
            "1. Quel est le délai de prescription en matière disciplinaire ?\n"
            "2. Combien de temps ai-je pour sanctionner un salarié ?\n"
            "3. Délai de prescription disciplinaire applicable\n"
            "4. prescription disciplinaire délai sanction faute\n"
            "5. Prescription disciplinaire CCN 66 handicapés"
        )
        variants = RAGAgent._parse_variants(content, "prescription disciplinaire")
        assert len(variants) == 5
        assert "prescription" in variants[0].lower()

    def test_parse_with_dashes(self):
        content = (
            "1. — Question corrigée\n"
            "2. – Intention RH\n"
            "3. - Terminologie juridique\n"
            "4. — mots clés\n"
            "5. - variante CCN"
        )
        variants = RAGAgent._parse_variants(content, "query")
        assert len(variants) == 5

    def test_parse_with_parenthesis(self):
        content = (
            "1) Question corrigée\n"
            "2) Intention RH\n"
            "3) Terminologie juridique\n"
            "4) mots clés\n"
            "5) variante CCN"
        )
        variants = RAGAgent._parse_variants(content, "query")
        assert len(variants) == 5

    def test_fallback_on_empty_content(self):
        variants = RAGAgent._parse_variants("", "original query")
        assert variants == ["original query"]

    def test_fallback_on_unparseable_content(self):
        variants = RAGAgent._parse_variants(
            "This is just a paragraph with no numbered lines.",
            "original query",
        )
        assert variants == ["original query"]


class TestBuildExpandUserMessage:
    def test_no_org_context(self):
        msg = RAGAgent._build_expand_user_message("ma question", None)
        assert msg == "Question : ma question"

    def test_empty_org_context_fields(self):
        msg = RAGAgent._build_expand_user_message(
            "ma question",
            {"nom": "Empreintes", "convention_collective": None},
        )
        # Only `nom` is not surfaced to the LLM → no [ORGANISATION] block
        assert msg == "Question : ma question"

    def test_with_ccn(self):
        msg = RAGAgent._build_expand_user_message(
            "prescription disciplinaire",
            {
                "nom": "Empreintes",
                "convention_collective": "CCN Handicapés 66 (IDCC 0413)",
                "secteur_activite": None,
                "taille": None,
                "forme_juridique": None,
            },
        )
        assert "[ORGANISATION]" in msg
        assert "CCN Handicapés 66 (IDCC 0413)" in msg
        assert "Question : prescription disciplinaire" in msg

    def test_with_full_context(self):
        msg = RAGAgent._build_expand_user_message(
            "mes congés",
            {
                "convention_collective": "Syntec (IDCC 1486)",
                "secteur_activite": "Ingénierie",
                "taille": "50-249",
                "forme_juridique": "SAS",
            },
        )
        assert "Syntec" in msg
        assert "Ingénierie" in msg
        assert "50-249" in msg
        assert "SAS" in msg


class TestExpandQueries:
    @pytest.mark.asyncio
    async def test_expand_returns_5_variants(self, agent):
        agent.llm.chat.completions.create.return_value = _mock_llm_response(
            "1. Quel est le délai de prescription en matière disciplinaire ?\n"
            "2. Combien de temps ai-je pour sanctionner un salarié ?\n"
            "3. Délai de prescription disciplinaire applicable\n"
            "4. prescription disciplinaire délai sanction faute\n"
            "5. Prescription disciplinaire CCN 66"
        )

        variants = await agent._expand_queries("prescription disciplinaire")

        assert len(variants) == 5
        agent.llm.chat.completions.create.assert_called_once()
        call_args = agent.llm.chat.completions.create.call_args
        assert call_args.kwargs["temperature"] == 0.3
        assert call_args.kwargs["max_tokens"] == 600

    @pytest.mark.asyncio
    async def test_expand_injects_org_context_in_user_message(self, agent):
        agent.llm.chat.completions.create.return_value = _mock_llm_response(
            "1. a\n2. b\n3. c\n4. d\n5. e"
        )
        await agent._expand_queries(
            "prescription disciplinaire",
            org_context={
                "convention_collective": "CCN Handicapés 66 (IDCC 0413)",
                "secteur_activite": "Médico-social",
                "taille": None,
                "forme_juridique": None,
            },
        )
        call_args = agent.llm.chat.completions.create.call_args
        user_msg = call_args.kwargs["messages"][1]["content"]
        assert "[ORGANISATION]" in user_msg
        assert "CCN Handicapés 66" in user_msg
        assert "Médico-social" in user_msg

    @pytest.mark.asyncio
    async def test_expand_without_org_context_uses_plain_question(self, agent):
        agent.llm.chat.completions.create.return_value = _mock_llm_response(
            "1. a\n2. b\n3. c\n4. d\n5. e"
        )
        await agent._expand_queries("ma question")
        call_args = agent.llm.chat.completions.create.call_args
        user_msg = call_args.kwargs["messages"][1]["content"]
        assert user_msg == "Question : ma question"

    @pytest.mark.asyncio
    async def test_expand_fallback_on_none(self, agent):
        agent.llm.chat.completions.create.return_value = _mock_llm_response(None)

        variants = await agent._expand_queries("test query")
        assert variants == ["test query"]

    @pytest.mark.asyncio
    async def test_expand_hors_scope_marker(self, agent):
        agent.llm.chat.completions.create.return_value = _mock_llm_response(
            "1. [HORS_SCOPE]"
        )
        variants = await agent._expand_queries("quelle est la capitale du Pérou ?")
        assert variants == ["[HORS_SCOPE]"]


class TestReciprocalRankFusion:
    def test_basic_fusion(self):
        list1 = [
            _make_result("A", 0.9, "doc1", 0),
            _make_result("B", 0.8, "doc2", 0),
        ]
        list2 = [
            _make_result("B", 0.7, "doc2", 0),
            _make_result("C", 0.6, "doc3", 0),
        ]

        fused = RAGAgent._reciprocal_rank_fusion([list1, list2], k=60)

        # B appears in both lists → higher RRF score
        assert fused[0].document_id == "doc2"  # B appears in both → highest score
        assert len(fused) == 3  # A, B, C deduplicated

    def test_deduplication_by_doc_chunk(self):
        list1 = [
            _make_result("A", 0.9, "doc1", 0),
            _make_result("A copy", 0.8, "doc1", 0),  # same doc_id + chunk
        ]
        list2 = [
            _make_result("A again", 0.7, "doc1", 0),  # same doc_id + chunk
        ]

        fused = RAGAgent._reciprocal_rank_fusion([list1, list2], k=60)

        # All have same (doc1, 0) key → only 1 result
        assert len(fused) == 1

    def test_empty_lists(self):
        fused = RAGAgent._reciprocal_rank_fusion([[], []], k=60)
        assert fused == []

    def test_single_list(self):
        results = [
            _make_result("A", 0.9, "doc1", 0),
            _make_result("B", 0.8, "doc2", 0),
        ]
        fused = RAGAgent._reciprocal_rank_fusion([results], k=60)
        assert len(fused) == 2

    def test_rrf_scores_correct(self):
        list1 = [_make_result("A", 0.9, "doc1", 0)]
        list2 = [_make_result("A", 0.7, "doc1", 0)]

        fused = RAGAgent._reciprocal_rank_fusion([list1, list2], k=60)

        # A is rank 0 in both lists: score = 1/(60+0+1) + 1/(60+0+1) = 2/61
        expected = 2.0 / 61.0
        assert abs(fused[0].score - expected) < 1e-10


class TestSearchWithExpansion:
    @pytest.mark.asyncio
    async def test_parallel_search_3_variants(self, agent):
        agent.llm.chat.completions.create.return_value = _mock_llm_response(
            "1. Variant A\n2. Variant B\n3. Variant C"
        )

        results_per_variant = [
            [_make_result("chunk1", 0.9, "doc1", 0)],
            [_make_result("chunk2", 0.8, "doc2", 0)],
            [_make_result("chunk3", 0.7, "doc3", 0)],
        ]

        call_count = 0

        async def mock_search(query, org_id, top_k=20, org_idcc_list=None):
            nonlocal call_count
            # _search_with_expansion prepends the original query, so we handle
            # more calls than variants; return empty for extras.
            result = (
                results_per_variant[call_count]
                if call_count < len(results_per_variant)
                else []
            )
            call_count += 1
            return result

        agent.search_engine = MagicMock()
        agent.search_engine.search = mock_search

        results, variants = await agent._search_with_expansion(
            "test query", "org-123",
        )

        # Variants from LLM (3) + original query prepended by _search_with_expansion
        assert len(variants) == 4
        assert variants[0] == "test query"
        assert len(results) >= 3  # at least 3 unique chunks
        assert call_count == 4  # original + 3 variants searched in parallel

    @pytest.mark.asyncio
    async def test_search_with_overlap_deduplicates(self, agent):
        agent.llm.chat.completions.create.return_value = _mock_llm_response(
            "1. Variant A\n2. Variant B"
        )

        shared_result = _make_result("shared chunk", 0.9, "doc1", 0)

        call_count = 0

        async def mock_search(query, org_id, top_k=20, org_idcc_list=None):
            nonlocal call_count
            call_count += 1
            # Both variants return the same document
            return [
                SearchResult(
                    text=shared_result.text,
                    doc_name=shared_result.doc_name,
                    document_id=shared_result.document_id,
                    source_type=shared_result.source_type,
                    norme_niveau=shared_result.norme_niveau,
                    norme_poids=shared_result.norme_poids,
                    chunk_index=shared_result.chunk_index,
                    score=0.9 - call_count * 0.1,
                ),
            ]

        agent.search_engine = MagicMock()
        agent.search_engine.search = mock_search

        results, variants = await agent._search_with_expansion(
            "test query", "org-123",
        )

        # Should deduplicate to 1 result
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_handles_variant_failure(self, agent):
        agent.llm.chat.completions.create.return_value = _mock_llm_response(
            "1. Variant A\n2. Variant B"
        )

        call_count = 0

        async def mock_search(query, org_id, top_k=20, org_idcc_list=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Search failed")
            return [_make_result("chunk", 0.8, "doc1", 0)]

        agent.search_engine = MagicMock()
        agent.search_engine.search = mock_search

        results, variants = await agent._search_with_expansion(
            "test query", "org-123",
        )

        # First variant failed but second succeeded
        assert len(results) == 1
