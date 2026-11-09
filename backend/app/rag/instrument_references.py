"""Explicit references to dated legal texts (loi, décret, ordonnance, arrêté).

The user's question is parsed with fixed patterns (no LLM, no judgement of a
generation). A reference is resolved against the public corpus by the exact
number or by the date that opens the official title; it is never guessed.

Resolved texts are only *searched*: their passages join the candidate pool and
the common reranker decides. When a retained passage amends a Code article
(« L'article L. 8115-1 est complété par un 6° »), the current consolidated
version of that article is fetched as an additional candidate, with its
immediate neighbours in the same section (amounts, procedure).
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from dataclasses import dataclass

from app.rag.legal_references import norm as normalize_article
from app.rag.source_intent import CODE_SOURCE_LABELS

MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
}
MONTH_NAMES = {
    1: "janvier",
    2: "février",
    3: "mars",
    4: "avril",
    5: "mai",
    6: "juin",
    7: "juillet",
    8: "août",
    9: "septembre",
    10: "octobre",
    11: "novembre",
    12: "décembre",
}

KIND_SOURCE_TYPES = {
    "loi": ("loi",),
    "decret": ("decret",),
    "ordonnance": ("ordonnance",),
    "arrete": ("arrete",),
}

# Above this many texts for one reference, the reference is reported as
# ambiguous and not searched (e.g. "arrêté du 1er juillet 2025").
MAX_DOCUMENTS_PER_REFERENCE = 8

_KIND = (
    r"(?P<kind>lois?(?:\s+organique|\s+constitutionnelle)?|d[ée]crets?|ordonnances?|arr[êe]t[ée]s?)"
)
_NUMBER = r"(?:\s+(?:n\s*[°o]\.?|num[ée]ro|no\.)?\s*(?P<number>\d{4}\s*-\s*\d{1,5}))"
_DATE = r"(?:\s+du\s+(?P<day>\d{1,2})(?:er)?\s+(?P<month>[a-zéèêûô]+)\s+(?P<year>\d{4}))"
_REFERENCE = re.compile(rf"\b{_KIND}{_NUMBER}?{_DATE}?", re.IGNORECASE)


@dataclass(frozen=True)
class InstrumentReference:
    kind: str
    number: str | None
    date: datetime.date | None
    mention: str

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "number": self.number,
            "date": self.date.isoformat() if self.date else None,
            "mention": self.mention,
        }


def _fold(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", value.lower()) if unicodedata.category(c) != "Mn"
    )


def _kind(value: str) -> str:
    folded = _fold(value)
    for kind in ("loi", "decret", "ordonnance", "arrete"):
        if folded.startswith(kind):
            return kind
    raise ValueError(value)


def detect_instrument_references(*texts: str) -> list[InstrumentReference]:
    """Return explicit references with a number and/or a complete date."""
    found: list[InstrumentReference] = []
    seen: set[tuple] = set()
    for text in texts:
        for m in _REFERENCE.finditer(text or ""):
            number = re.sub(r"\s+", "", m.group("number")) if m.group("number") else None
            date = None
            if m.group("day"):
                month = MONTHS.get(_fold(m.group("month")))
                if month is None:
                    if number is None:
                        continue
                else:
                    try:
                        date = datetime.date(int(m.group("year")), month, int(m.group("day")))
                    except ValueError:
                        if number is None:
                            continue
            if number is None and date is None:
                continue
            reference = InstrumentReference(_kind(m.group("kind")), number, date, m.group(0))
            key = (reference.kind, reference.number, reference.date)
            if key not in seen:
                seen.add(key)
                found.append(reference)
    return found


def _title_head(reference: InstrumentReference) -> re.Pattern:
    """Pattern of the official title opening, e.g. 'LOI n° 2026-534 du 25 juin 2026'."""
    kind = {
        "loi": r"loi(?:\s+organique|\s+constitutionnelle)?",
        "decret": r"d[ée]cret",
        "ordonnance": r"ordonnance",
        "arrete": r"arr[êe]t[ée]",
    }[reference.kind]
    number = r"(?:\s+n\s*°?\s*(?P<number>\d{4}-\d{1,5}))?"
    date = r"(?:\s+du\s+(?P<day>\d{1,2})(?:er)?\s+(?P<month>[a-zéèêûô]+)\s+(?P<year>\d{4}))?"
    return re.compile(rf"^\s*{kind}{number}{date}\b", re.IGNORECASE)


def title_matches(reference: InstrumentReference, name: str) -> bool:
    """True when the *opening* of the title designates the referenced text.

    A text that merely cites the reference later in its title ("portant
    application de la loi n° ... du ...") does not match.
    """
    m = _title_head(reference).match(name or "")
    if not m:
        return False
    if reference.number and m.group("number") != reference.number:
        return False
    if reference.date:
        if not m.group("day"):
            return False
        month = MONTHS.get(_fold(m.group("month") or ""))
        try:
            title_date = datetime.date(int(m.group("year")), month or 0, int(m.group("day")))
        except ValueError:
            return False
        if title_date != reference.date:
            return False
    return True


def sql_like_patterns(reference: InstrumentReference) -> list[str]:
    """Coarse SQL prefilters; the exact check is title_matches()."""
    if reference.number:
        return [f"%{reference.number}%"]
    date = reference.date
    day = "1er" if date.day == 1 else str(date.day)
    return [f"% du {day} {MONTH_NAMES[date.month]} {date.year}%"] + (
        [f"% du 1 {MONTH_NAMES[date.month]} {date.year}%"] if date.day == 1 else []
    )


async def resolve_instrument_references(references, session_factory=None) -> list[dict]:
    """Resolve each reference to public, indexed corpus documents."""
    if not references:
        return []
    from sqlalchemy import or_, select

    from app.models.document import Document

    if session_factory is None:
        from app.core.database import async_session_factory as session_factory

    resolved = []
    async with session_factory() as session:
        for reference in references:
            rows = (
                await session.execute(
                    select(Document.id, Document.name, Document.source_type)
                    .where(
                        Document.organisation_id.is_(None),
                        Document.retired_at.is_(None),
                        Document.indexation_status == "indexed",
                        Document.source_type.in_(KIND_SOURCE_TYPES[reference.kind]),
                        or_(*[Document.name.ilike(p) for p in sql_like_patterns(reference)]),
                    )
                    .limit(200)
                )
            ).all()
            documents = [
                {"document_id": str(row.id), "name": row.name, "source_type": row.source_type}
                for row in rows
                if title_matches(reference, row.name)
            ]
            if not documents:
                status = "not_found"
            elif len(documents) > MAX_DOCUMENTS_PER_REFERENCE:
                status = "ambiguous_not_searched"
            else:
                status = "resolved"
            resolved.append(
                {
                    **reference.as_dict(),
                    "status": status,
                    "documents": documents[: MAX_DOCUMENTS_PER_REFERENCE + 1],
                    "document_count": len(documents),
                }
            )
    return resolved


# --- Amended Code articles ----------------------------------------------------

_ARTICLE = r"([LRD])\.?\s*(\d{1,4}(?:[-‑–]\d+)+)"
_AMENDED = re.compile(
    r"(?:l['’]article|les\s+articles|apr[èe]s\s+l['’]article|à\s+l['’]article|"
    r"au\s+(?:[IVX]+\s+de\s+l['’]|premier\s+alin[ée]a\s+de\s+l['’]|\d+°\s+de\s+l['’])article)\s+"
    + _ARTICLE,
    re.IGNORECASE,
)
_ANY_ARTICLE = re.compile(r"\b" + _ARTICLE + r"\b", re.IGNORECASE)


def _mask_quotations(text: str) -> str:
    """Blank inserted wording (« ... ») while keeping character positions."""
    return re.sub(r"«[^»]*»?", lambda m: " " * len(m.group(0)), text)


def _code_scope_before(masked: str, position: int) -> list[str] | None:
    """Code being amended at position: last 'code X ... est ainsi modifié'
    header outside quotations, else the last Code named outside quotations."""
    best_header = best_any = None
    for label, types in CODE_SOURCE_LABELS.items():
        for m in re.finditer(label, masked[:position], re.IGNORECASE):
            if best_any is None or m.start() > best_any[0]:
                best_any = (m.start(), types)
            if re.match(r"[^.;:]{0,40}?\best\s+ainsi\s+modifi", masked[m.end() : position]):
                if best_header is None or m.start() > best_header[0]:
                    best_header = (m.start(), types)
    best = best_header or best_any
    return list(best[1]) if best else None


def amended_code_articles(article_text: str, passage_start: int) -> list[dict]:
    """Code articles targeted by an amending article, around one passage.

    article_text is the complete text of the amending article (its passages in
    order); passage_start is where the retained passage begins. Kept: the last
    amended article announced before the passage (the passage usually holds
    the inserted wording) and articles cited inside the passage. Each keeps
    the Code named before it in the same article; unnamed Codes are dropped.
    """
    masked = _mask_quotations(article_text)
    before = [m for m in _AMENDED.finditer(masked) if m.start() < passage_start]
    candidates = [(m, "amended") for m in before[-1:]] + [
        (m, "cited") for m in _ANY_ARTICLE.finditer(article_text) if m.start() >= passage_start
    ]
    articles: list[dict] = []
    seen: set[str] = set()
    for m, role in candidates:
        reference = normalize_article("".join(m.groups()))
        if reference in seen:
            continue
        scope = _code_scope_before(masked, m.start())
        tail = article_text[m.end() : m.end() + 60]
        following = next(
            (
                types
                for label, types in CODE_SOURCE_LABELS.items()
                if re.match(r"\s*(?:du|de\s+la|de\s+l['’]|des)\s*" + label, tail, re.IGNORECASE)
            ),
            None,
        )
        scope = list(following) if following else scope
        if not scope:
            continue
        seen.add(reference)
        articles.append({"article": reference, "source_types": scope, "role": role})
    return articles


# --- Qdrant reads (synchronous; run in a thread) ------------------------------


def read_article_passages(qdrant, document_id: str, article_nums: list[str], access_filter):
    """All passages of one article of one document, in document order."""
    from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

    from app.rag.parent_expansion import _payload_to_result
    from app.rag.qdrant_store import COLLECTION_NAME

    must = [
        FieldCondition(key="document_id", match=MatchValue(value=document_id)),
        FieldCondition(key="article_nums", match=MatchAny(any=list(article_nums))),
    ]
    if access_filter is not None:
        must.append(access_filter)
    points, _ = qdrant.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=Filter(must=must),
        limit=40,
        with_payload=True,
        with_vectors=False,
    )
    return sorted(
        (_payload_to_result(p.payload or {}) for p in points), key=lambda r: r.chunk_index
    )


def read_section_neighbours(qdrant, seed, access_filter, before: int = 1, after: int = 2):
    """Passages next to seed in the same document and the same section."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

    from app.rag.parent_expansion import _payload_to_result
    from app.rag.qdrant_store import COLLECTION_NAME

    must = [
        FieldCondition(key="document_id", match=MatchValue(value=seed.document_id)),
        FieldCondition(
            key="chunk_index",
            range=Range(gte=seed.chunk_index - before, lte=seed.chunk_index + after),
        ),
    ]
    if access_filter is not None:
        must.append(access_filter)
    points, _ = qdrant.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=Filter(must=must),
        limit=before + after + 1,
        with_payload=True,
        with_vectors=False,
    )
    return sorted(
        (
            r
            for r in (_payload_to_result(p.payload or {}) for p in points)
            if r.section_path and r.section_path == seed.section_path
        ),
        key=lambda r: r.chunk_index,
    )


def read_document_passages(qdrant, document_id: str, access_filter, limit: int):
    """Every passage of one document, or (partial, False) beyond limit."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from app.rag.parent_expansion import _payload_to_result
    from app.rag.qdrant_store import COLLECTION_NAME

    must = [FieldCondition(key="document_id", match=MatchValue(value=document_id))]
    if access_filter is not None:
        must.append(access_filter)
    found, offset = [], None
    while True:
        kwargs = dict(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(must=must),
            limit=min(256, limit + 1 - len(found)),
            with_payload=True,
            with_vectors=False,
        )
        if offset is not None:
            kwargs["offset"] = offset
        points, offset = qdrant.scroll(**kwargs)
        found.extend(_payload_to_result(p.payload or {}) for p in points)
        if len(found) > limit:
            return found[:limit], False
        if offset is None:
            return sorted(found, key=lambda r: r.chunk_index), True
