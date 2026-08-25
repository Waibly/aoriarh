from app.rag.agent import _generation_system_prompt


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
    assert max_tokens == 16000
