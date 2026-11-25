"""Mise en cache explicite du prompt système (modèles gpt-5.6 et suivants).

Par défaut, OpenAI place un point de cache implicite à la fin du message : il
écrit alors en cache tout le message (sources comprises) au tarif d'écriture,
plus cher que l'entrée normale, alors que seule la partie fixe (le prompt
système) est relue ensuite. En mode explicite, seul le prompt système est mis
en cache ; le reste est facturé au tarif d'entrée normal. Le texte reçu par le
modèle est strictement identique.
"""

from __future__ import annotations

_EXPLICIT_CACHE_MODEL_PREFIXES = ("gpt-5.6", "gpt-6")


def supports_explicit_prompt_cache(model: str) -> bool:
    return (model or "").startswith(_EXPLICIT_CACHE_MODEL_PREFIXES)


def system_message(text: str, model: str) -> dict:
    """Message système, avec un point de cache à sa fin si le modèle le permet."""
    if not supports_explicit_prompt_cache(model):
        return {"role": "system", "content": text}
    return {
        "role": "system",
        "content": [
            {
                "type": "text",
                "text": text,
                "prompt_cache_breakpoint": {"mode": "explicit"},
            }
        ],
    }


def prompt_cache_kwargs(model: str) -> dict:
    """Arguments de l'appel qui coupent le point de cache implicite.

    Passés par `extra_body` pour ne pas dépendre de la version du SDK.
    """
    if not supports_explicit_prompt_cache(model):
        return {}
    return {"extra_body": {"prompt_cache_options": {"mode": "explicit"}}}


def message_text_length(message: dict) -> int:
    content = message.get("content")
    if isinstance(content, str):
        return len(content)
    return sum(len(part.get("text", "")) for part in content or [] if isinstance(part, dict))
