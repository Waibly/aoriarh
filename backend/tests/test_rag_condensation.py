from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag.agent import RAGAgent


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


class TestBuildUserMessageCondensed:
    """La question condensée (utilisée pour chercher les sources) doit être
    fournie à la génération quand elle diffère de la relance brute."""

    def test_condensed_appended_when_different(self, agent):
        msg = agent._build_user_message(
            "Et pour un CDD ?",
            context="[Source]\nContenu : x",
            condensed_query="Quels sont les délais de préavis pour un CDD ?",
        )
        assert "Question : Et pour un CDD ?" in msg
        assert "Quels sont les délais de préavis pour un CDD ?" in msg
        assert "replacée dans le contexte" in msg

    def test_condensed_omitted_when_identical(self, agent):
        msg = agent._build_user_message(
            "Quel préavis pour un CDD ?",
            context="[Source]\nContenu : x",
            condensed_query="quel préavis pour un CDD",
        )
        assert "replacée dans le contexte" not in msg

    def test_no_condensed(self, agent):
        msg = agent._build_user_message(
            "Question simple", context="[Source]\nContenu : x",
        )
        assert "replacée dans le contexte" not in msg


class TestBuildUserMessageDate:
    def test_date_du_jour_present(self, agent):
        msg = agent._build_user_message(
            "Le décret est-il en vigueur ?", context="[Source]\nContenu : x",
        )
        assert "Date du jour :" in msg
        # La date précède la question pour cadrer le raisonnement temporel
        assert msg.index("Date du jour :") < msg.index("Question :")
