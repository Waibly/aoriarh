from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag.agent import RAGAgent


def _mock_llm_response(content: str):
    """Create a mock OpenAI chat completion response."""
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


class TestCondensation:
    @pytest.mark.asyncio
    async def test_condense_with_history(self, agent):
        agent.llm.chat.completions.create.return_value = _mock_llm_response(
            "Quels sont les délais de préavis pour un CDD ?"
        )

        history = [
            {"role": "user", "content": "Quels sont les délais de préavis en cas de licenciement ?"},
            {"role": "assistant", "content": "Les délais de préavis dépendent de l'ancienneté..."},
        ]

        result = await agent._condense_question("Et pour un CDD ?", history)

        assert result == "Quels sont les délais de préavis pour un CDD ?"
        agent.llm.chat.completions.create.assert_called_once()
        call_args = agent.llm.chat.completions.create.call_args
        assert call_args.kwargs["model"] == "gpt-4o-mini"
        assert call_args.kwargs["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_no_history_skips_condensation(self, agent):
        """prepare_context with no history should not call _condense_question."""
        agent.llm.chat.completions.create.return_value = _mock_llm_response(
            "reformulated query"
        )
        agent.search_engine = MagicMock()
        agent.search_engine.search = AsyncMock(return_value=[])
        agent.reranker = MagicMock()
        agent.reranker.rerank = AsyncMock(return_value=[])

        await agent.prepare_context("simple question", "org-123", history=None)

        # Only one LLM call (reformulation), no condensation
        assert agent.llm.chat.completions.create.call_count == 1

    @pytest.mark.asyncio
    async def test_history_truncated_to_limit(self, agent):
        agent.llm.chat.completions.create.return_value = _mock_llm_response(
            "condensed question"
        )

        history = [
            {"role": "user", "content": f"Message {i}"}
            for i in range(10)
        ]

        await agent._condense_question("follow up", history)

        call_args = agent.llm.chat.completions.create.call_args
        user_content = call_args.kwargs["messages"][1]["content"]
        # Only last 6 messages should be included
        assert "Message 4" in user_content
        assert "Message 9" in user_content
        assert "Message 3" not in user_content

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self, agent):
        """If condensation LLM fails, pipeline should use original query."""
        agent.llm.chat.completions.create.side_effect = [
            Exception("LLM error"),  # condensation fails
            _mock_llm_response("reformulated"),  # reformulation succeeds
        ]
        agent.search_engine = MagicMock()
        agent.search_engine.search = AsyncMock(return_value=[])
        agent.reranker = MagicMock()
        agent.reranker.rerank = AsyncMock(return_value=[])

        history = [
            {"role": "user", "content": "previous question"},
            {"role": "assistant", "content": "previous answer"},
        ]

        results, reformulated, trace = await agent.prepare_context(
            "follow up", "org-123", history=history,
        )

        # Should fall back to original query and continue with reformulation
        assert agent.llm.chat.completions.create.call_count == 2

    @pytest.mark.asyncio
    async def test_long_messages_truncated(self, agent):
        agent.llm.chat.completions.create.return_value = _mock_llm_response(
            "condensed"
        )

        long_content = "x" * 1000
        history = [
            {"role": "user", "content": long_content},
        ]

        await agent._condense_question("follow up", history)

        call_args = agent.llm.chat.completions.create.call_args
        user_content = call_args.kwargs["messages"][1]["content"]
        # Content should be truncated to 500 chars per message
        lines = user_content.split("\n")
        history_line = [l for l in lines if l.startswith("Utilisateur:")][0]
        # 500 chars + "Utilisateur: " prefix
        assert len(history_line) <= 520

    @pytest.mark.asyncio
    async def test_condense_returns_query_on_none_content(self, agent):
        agent.llm.chat.completions.create.return_value = _mock_llm_response(None)

        history = [
            {"role": "user", "content": "previous"},
        ]

        result = await agent._condense_question("my question", history)
        assert result == "my question"
