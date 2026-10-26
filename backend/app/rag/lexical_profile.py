"""Versioned sparse-vector identities: a language change requires a new index."""

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class LexicalProfile:
    vector_name: str
    language: str


LEXICAL_PROFILES = {
    "legacy-en": LexicalProfile("sparse-bm25", "english"),
    "french-v1": LexicalProfile("sparse-bm25-fr-v1", "french"),
}


def lexical_profile(name: str | None = None) -> LexicalProfile:
    return LEXICAL_PROFILES[name or settings.rag_lexical_profile]
