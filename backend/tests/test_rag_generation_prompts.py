from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag import config as rag_config
from app.rag.agent import RAGAgent, _generation_system_prompt


def test_legal_generation_prompt_contains_each_editorial_rule_once():
    prompt, max_tokens = _generation_system_prompt()

    shared_rules = (
        "DISCIPLINE ÉDITORIALE COMMUNE",
        "Supprime le méta-discours",
        "Écarte les formulations génériques",
        "Évite les automatismes rhétoriques",
        "Limite le langage abstrait ou promotionnel",
        "Évite la sur-structuration",
        "Réduis les connecteurs explicites",
        "Évite la redondance",
        "Varie naturellement la syntaxe",
    )
    for rule in shared_rules:
        assert prompt.count(rule) == 1

    assert "RÔLE" in prompt
    assert "distingue ce que les sources établissent, ce que tu déduis" in prompt
    assert "utilise uniquement une formule et une assiette établies" in prompt
    assert "Ne décide jamais sans fondement que des taux s'additionnent" in prompt
    assert "Vérifie l'opération et l'ordre de grandeur" in prompt
    assert max_tokens == 16000


class _EmptyStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


@pytest.mark.asyncio
async def test_final_generation_uses_terra_with_medium_reasoning(monkeypatch):
    monkeypatch.setattr(rag_config, "LLM_MODEL", "gpt-5.6-terra")
    monkeypatch.setattr(rag_config, "LLM_REASONING_EFFORT", "medium")

    with patch("app.rag.agent._search_engine"), patch("app.rag.agent.get_reranker"):
        agent = RAGAgent()
    agent.llm = MagicMock()
    agent.llm.chat.completions.create = AsyncMock(return_value=_EmptyStream())

    chunks = [chunk async for chunk in agent.stream_generate("Question RH", [])]

    assert chunks == []
    call = agent.llm.chat.completions.create.call_args.kwargs
    assert call["model"] == "gpt-5.6-terra"
    assert call["reasoning_effort"] == "medium"
