"""Checks done by program: certain when they fire, silent when unsure."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.rag.answer_arithmetic import find_arithmetic_errors

# The live chat already appends this notice when it finds a wrong operation:
# those errors were shown to the user and are not reported a second time.
_ARITHMETIC_NOTICE = "**Vérification automatique des calculs**"

# "art. L.3312-2", "D. 3313-13", "R3313-12" (same spelling as legal_references.refs).
_ARTICLE = re.compile(r"\b([LRD])\.?\s?(\d{1,4})((?:[-‑–]\d+)+)\b")
_ABBREVIATION = re.compile(r"\b(art|arts|al|cf|ex|ann|n°)\.\s", re.IGNORECASE)
_JOINER = "\u2060"  # word joiner: not whitespace, so never a sentence break
_SENTENCE_END = re.compile(r"\n+|(?<=[.!?;])\s+")
_OTHER_CODE = re.compile(
    r"code\s+(?!du\s+travail)(de\s+la\s+|de\s+l['’]|des\s+|de\s+|du\s+|civil|pénal|rural)",
    re.IGNORECASE,
)
_LABOUR_CODE = re.compile(r"code\s+du\s+travail", re.IGNORECASE)
_MAX_ARTICLES = 25


@dataclass(frozen=True)
class DeterministicFinding:
    check: str
    kind: str
    answer_excerpt: str
    explanation: str
    proposed_fix: str | None = None
    source_excerpt: str | None = None
    source_label: str | None = None


def arithmetic_findings(answer: str) -> list[DeterministicFinding]:
    if _ARITHMETIC_NOTICE in answer:
        return []
    return [
        DeterministicFinding(
            check="arithmetic",
            kind="montant",
            answer_excerpt=f"{item['operation']} = {item['stated']}",
            explanation=(
                f"L'opération {item['operation']} donne {item['correct']}, et non {item['stated']}."
            ),
            proposed_fix=f"{item['operation']} = {item['correct']}",
        )
        for item in find_arithmetic_errors(answer)
    ]


def normalize_article(letter: str, number: str, suffix: str) -> str:
    return f"{letter.upper()}{number}{re.sub(r'[‑–]', '-', suffix)}"


def labour_code_citations(answer: str) -> dict[str, str]:
    """Articles cited as Code du travail articles, with the sentence citing them.

    A sentence naming another code (sécurité sociale, commerce…) without naming the
    Code du travail is left out: its articles may legitimately be absent from our base.
    """
    found: dict[str, str] = {}
    protected = _ABBREVIATION.sub(lambda m: m.group(0).rstrip() + _JOINER, answer)
    for sentence in _SENTENCE_END.split(protected):
        if not sentence.strip():
            continue
        if _OTHER_CODE.search(sentence) and not _LABOUR_CODE.search(sentence):
            continue
        for match in _ARTICLE.finditer(sentence):
            ref = normalize_article(*match.groups())
            found.setdefault(ref, sentence.replace(_JOINER, " ").strip())
            if len(found) >= _MAX_ARTICLES:
                return found
    return found


async def citation_findings(
    answer: str, exists: Callable[[list[str]], Awaitable[set[str]]]
) -> list[DeterministicFinding]:
    """Cited Code du travail articles that exist nowhere in our indexed texts."""
    cited = labour_code_citations(answer)
    if not cited:
        return []
    present = await exists(sorted(cited))
    return [
        DeterministicFinding(
            check="citation",
            kind="citation_introuvable",
            answer_excerpt=sentence[:600],
            explanation=(
                f"L'article {ref} cité n'existe dans aucun texte en vigueur de notre base "
                "(article inexistant, abrogé ou mal numéroté)."
            ),
        )
        for ref, sentence in cited.items()
        if ref not in present
    ]


def qdrant_article_lookup(client, collection: str) -> Callable[[list[str]], Awaitable[set[str]]]:
    """Return an async function giving the articles present in the index."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    def _exists(ref: str) -> bool:
        result = client.count(
            collection,
            count_filter=Filter(
                must=[FieldCondition(key="article_nums", match=MatchValue(value=ref))]
            ),
            exact=False,
        )
        return result.count > 0

    async def lookup(refs: list[str]) -> set[str]:
        flags = await asyncio.gather(*(asyncio.to_thread(_exists, ref) for ref in refs))
        return {ref for ref, ok in zip(refs, flags, strict=True) if ok}

    return lookup
