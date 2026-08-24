from unittest.mock import AsyncMock, MagicMock

from app.rag.agent import _generation_system_prompt


def test_editorial_discipline_is_shared_by_chat_and_linkedin():
    chat_prompt, chat_max_tokens = _generation_system_prompt("legal_answer")
    linkedin_prompt, linkedin_max_tokens = _generation_system_prompt("linkedin_post")

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
        assert chat_prompt.count(rule) == 1
        assert linkedin_prompt.count(rule) == 1

    assert "RÔLE" in chat_prompt
    assert "MODE DE SORTIE — POST LINKEDIN" not in chat_prompt
    assert "MODE DE SORTIE — POST LINKEDIN" in linkedin_prompt
    assert "Questions complémentaires" not in linkedin_prompt
    assert chat_max_tokens == 16000
    assert linkedin_max_tokens == 6000


async def test_linkedin_generation_uses_low_reasoning_effort(monkeypatch):
    from app.rag.agent import RAGAgent

    agent = RAGAgent()
    agent.llm = MagicMock()

    async def empty_response():
        if False:
            yield None

    create = AsyncMock(return_value=empty_response())
    agent.llm.chat.completions.create = create

    chunks = [
        chunk
        async for chunk in agent.stream_generate(
            "Le refus du télétravail",
            [],
            generation_mode="linkedin_post",
        )
    ]

    assert chunks == []
    assert create.await_args.kwargs["reasoning_effort"] == "low"
