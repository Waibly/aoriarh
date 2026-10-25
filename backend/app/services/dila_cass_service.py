"""Lossless source inventory and layout-preserving chunks for public CASS XML.

This module never generates text or classifies a decision from its prose.
Admission uses the publisher's jurisdiction, formation and Bulletin metadata.
The original XML must always be retained alongside the indexed representation.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import date

import tiktoken
from lxml import etree

SOURCE_PREFIX = "common/dila/cass/"
MAX_XML_BYTES = 16 * 1024 * 1024
_IDENTIFIER = re.compile(r"JURITEXT\d{12}\Z")
_TABLE_TAG = re.compile(r"</?table(?:\s[^>]*)?>", re.IGNORECASE)
_BLOCKS = {
    "texte",
    "bloc_textuel",
    "contenu",
    "sommaire",
    "sct",
    "ana",
    "citation_jp",
    "p",
    "div",
    "section",
    "article",
    "li",
    "ul",
    "ol",
    "blockquote",
    "pre",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}
_TABLE_ELEMENTS = {
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "caption",
    "colgroup",
    "col",
    "p",
    "br",
    "span",
    "div",
    "b",
    "strong",
    "i",
    "em",
    "sup",
    "sub",
}
_TABLE_ATTRIBUTES = {"rowspan", "colspan", "scope", "headers", "id", "span"}


@dataclass(frozen=True)
class CassDecision:
    source_id: str
    decision_date: date
    numbers: tuple[str, ...]
    title: str
    solution: str
    text: str
    xml_sha256: str
    text_sha256: str
    visible_source_sha256: str
    table_count: int
    topics: tuple[str, ...]


def canonical_number(value: str) -> str | None:
    """Compare official case references without punctuation; never use placeholders."""
    key = "".join(character for character in value if character.isalnum()).lower()
    return key if any(character.isdigit() for character in key) else None


def number_aliases(value: str) -> set[str]:
    """Preserve joined legacy references while matching each seven-digit pourvoi.

    Some official records concatenate several modern-format case numbers. This
    only expands a numeric reference whose entire digit string partitions into
    seven-digit numbers; it never edits the stored source or an identifier.
    """
    result = {key} if (key := canonical_number(value)) else set()
    if re.fullmatch(r"[\d\s.,;/\-]+", value):
        digits = "".join(character for character in value if character.isdigit())
        if len(digits) >= 14 and len(digits) % 7 == 0:
            result.update(digits[i : i + 7] for i in range(0, len(digits), 7))
    return result


def _tag(node) -> str:
    if not isinstance(node.tag, str):
        raise ValueError("dila_non_element_node")
    return etree.QName(node).localname.lower()


def render_decision_text(root) -> tuple[str, str, int]:
    """Keep every source text node in order, including all numeric-only lines.

    Tables retain explicit HTML rows/cells and merged-cell attributes. Only safe
    structural tags/attributes are serialized, never scripts or event handlers.
    The untouched XML is the authoritative artifact, not this representation.
    """
    source = root.find("TEXTE")
    if source is None:
        raise ValueError("dila_missing_text")
    parts: list[str] = []
    visited: list[str] = []
    table_count = 0

    def emit_text(value, *, in_table=False):
        if value is not None:
            visited.append(value)
            parts.append(html.escape(value, quote=False) if in_table else value)

    def walk(node, *, in_table=False):
        nonlocal table_count
        tag = _tag(node)
        if tag in {"script", "style", "iframe", "object"}:
            raise ValueError("dila_unsupported_active_content")
        if tag == "table":
            table_count += 1
            parts.append("\n\n")
            in_table = True
        if in_table and tag not in _TABLE_ELEMENTS:
            raise ValueError("dila_unsupported_table_element:" + tag)
        if in_table:
            attributes = "".join(
                f' {key}="{html.escape(value, quote=True)}"'
                for key, value in node.attrib.items()
                if key in _TABLE_ATTRIBUTES
            )
            parts.append(f"<{tag}{attributes}>")
        elif tag == "br":
            parts.append("\n")
        elif tag in _BLOCKS:
            parts.append("\n\n")
        emit_text(node.text, in_table=in_table)
        for child in node:
            walk(child, in_table=in_table)
            emit_text(child.tail, in_table=in_table)
        if in_table:
            if tag != "br":
                parts.append(f"</{tag}>")
        elif tag in _BLOCKS:
            parts.append("\n\n")
        if tag == "table":
            parts.append("\n\n")

    walk(source)
    expected = "".join(source.itertext())
    if "".join(visited) != expected:
        raise ValueError("dila_source_text_coverage_mismatch")
    rendered = "".join(parts).strip()
    if not rendered:
        raise ValueError("dila_empty_decision")
    return rendered, hashlib.sha256(expected.encode()).hexdigest(), table_count


def parse_cass_xml(raw: bytes) -> CassDecision:
    if not raw or len(raw) > MAX_XML_BYTES:
        raise ValueError("dila_invalid_xml_size")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    root = etree.fromstring(raw, parser)
    if root.tag != "TEXTE_JURI_JUDI":
        raise ValueError("dila_invalid_root")
    if (
        root.findtext("META/META_SPEC/META_JURI/JURIDICTION") != "Cour de cassation"
        or root.findtext("META/META_SPEC/META_JURI_JUDI/FORMATION") != "CHAMBRE_SOCIALE"
    ):
        raise ValueError("dila_out_of_social_cassation_scope")
    bulletin = root.find("META/META_SPEC/META_JURI_JUDI/PUBLI_BULL")
    if bulletin is None or bulletin.get("publie") != "oui":
        raise ValueError("dila_not_published_in_bulletin")
    primary = root.find("TEXTE/BLOC_TEXTUEL/CONTENU")
    if primary is None or not "".join(primary.itertext()).strip():
        raise ValueError("dila_empty_decision_body")
    source_id = root.findtext("META/META_COMMUN/ID") or ""
    if not _IDENTIFIER.fullmatch(source_id):
        raise ValueError("dila_invalid_source_id")
    decision_date = date.fromisoformat(root.findtext("META/META_SPEC/META_JURI/DATE_DEC") or "")
    numbers = tuple(
        node.text
        for node in root.findall("META/META_SPEC/META_JURI_JUDI/NUMEROS_AFFAIRES/NUMERO_AFFAIRE")
        if node.text and canonical_number(node.text)
    )
    text, visible_digest, table_count = render_decision_text(root)
    return CassDecision(
        source_id=source_id,
        decision_date=decision_date,
        numbers=numbers,
        title=root.findtext("META/META_SPEC/META_JURI/TITRE") or source_id,
        solution=root.findtext("META/META_SPEC/META_JURI/SOLUTION") or "",
        text=text,
        xml_sha256=hashlib.sha256(raw).hexdigest(),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        visible_source_sha256=visible_digest,
        table_count=table_count,
        topics=tuple("".join(node.itertext()) for node in root.findall("TEXTE/SOMMAIRE/SCT")),
    )


def topic_scope(topics: tuple[str, ...]) -> str:
    """Versioned admission from official documentary headings, never decision prose.

    Generic procedural headings and mixed/unknown headings require reconciliation.
    A housing heading does not exclude an employment case with an explicit labour
    heading (for example employer-provided accommodation).
    """
    families = (
        "CONTRAT DE TRAVAIL",
        "REPRESENTATION DES SALARIES",
        "CONVENTIONS COLLECTIVES",
        "STATUT COLLECTIF DU TRAVAIL",
        "PRUD HOMMES",
        "TRAVAIL",
        "ELECTIONS PROFESSIONNELLES",
        "SYNDICAT PROFESSIONNEL",
        "VOYAGEUR REPRESENTANT PLACIER",
        "REPRESENTANT DE COMMERCE",
        "CONFLIT COLLECTIF DU TRAVAIL",
        "CONFLITS COLLECTIFS DU TRAVAIL",
        "STATUTS PROFESSIONNELS PARTICULIERS",
        "COMITE D ENTREPRISE",
        "DELEGUES DU PERSONNEL",
        "DELEGUE DU PERSONNEL",
        "EMPLOI",
        "APPRENTISSAGE",
        "SALAIRE",
        "CHOMAGE",
        "FORMATION PROFESSIONNELLE",
        "COMITE SOCIAL ET ECONOMIQUE",
        "GREVE",
        "ASSURANCE ACCIDENT DU TRAVAIL",
        "CONGES PAYES",
        "CONSEIL DE PRUD HOMMES",
        "COMITE D ETABLISSEMENT",
        "JOURNALISTE PROFESSIONNEL",
        "AGRICULTURE ACCIDENT DU TRAVAIL",
        "AGRICULTURE ACCIDENTS DU TRAVAIL",
    )
    hierarchies = []
    for topic in topics:
        segments = []
        # Retain the publisher's hierarchy: a leaf mentioning a profession or
        # work does not turn a housing or rural-lease case into employment law.
        for segment in re.split(r"\s+-\s+", topic):
            heading = "".join(
                character
                for character in unicodedata.normalize("NFKD", segment.upper())
                if not unicodedata.combining(character)
            )
            heading = " ".join(re.findall(r"[A-Z]+", heading))
            heading = re.sub(r"^(?:(?:O|ER|EME|DEG) )+", "", heading)
            segments.append(heading)
        if segments:
            hierarchies.append(segments)
    roots = [segments[0] for segments in hierarchies]
    strong_nested_families = (
        "CONTRAT DE TRAVAIL",
        "CONVENTIONS COLLECTIVES",
        "PRUD HOMMES",
        "REPRESENTATION DES SALARIES",
        "STATUT COLLECTIF DU TRAVAIL",
        "ELECTIONS PROFESSIONNELLES",
        "CONSEIL DE PRUD HOMMES",
        "COMITE SOCIAL ET ECONOMIQUE",
        "JOURNALISTE PROFESSIONNEL",
    )

    def belongs(heading, family):
        return heading == family or heading.startswith(family + " ")

    if any(belongs(root, family) for root in roots for family in families) or any(
        belongs(heading, family)
        for segments in hierarchies
        for heading in segments[1:]
        for family in strong_nested_families
    ):
        return "admitted"
    if any(
        root.startswith(("BAIL ", "BAUX ", "JUGE DES LOYERS", "METAYAGE")) for root in roots
    ) or any(
        "NON SALARIE" in heading or "PROFESSIONS LIBERALES" in heading
        for segments in hierarchies
        for heading in segments
    ):
        return "review_outside_or_mixed_scope"
    if any(root.startswith("SECURITE SOCIALE") for root in roots):
        return "admitted"
    return "review_generic_or_missing_topic"


def source_chunks(text: str, *, max_tokens=1024, max_table_tokens=12000) -> list[str]:
    """Partition the whole source exactly; keep tables atomic, without truncation."""
    encoder = tiktoken.get_encoding("cl100k_base")
    table_spans = []
    depth = 0
    start = None
    for match in _TABLE_TAG.finditer(text):
        if match.group().startswith("</"):
            depth -= 1
            if depth < 0:
                raise ValueError("dila_unbalanced_table")
            if depth == 0:
                table_spans.append((start, match.end()))
        else:
            if depth == 0:
                start = match.start()
            depth += 1
    if depth:
        raise ValueError("dila_unbalanced_table")
    chunks = []

    def prose(value):
        while value:
            tokens = encoder.encode(value, disallowed_special=())
            if len(tokens) <= max_tokens:
                chunks.append(value)
                return
            window = encoder.decode_bytes(tokens[:max_tokens])
            while True:
                try:
                    prefix = window.decode("utf-8")
                    break
                except UnicodeDecodeError as exc:
                    window = window[: exc.start]
            if not prefix:
                raise ValueError("dila_chunk_size_too_small")
            boundary = max(prefix.rfind("\n"), prefix.rfind(" "))
            cut = boundary + 1 if boundary >= len(prefix) // 2 else len(prefix)
            chunks.append(value[:cut])
            value = value[cut:]

    offset = 0
    for begin, end in table_spans:
        prose(text[offset:begin])
        table = text[begin:end]
        if len(encoder.encode(table, disallowed_special=())) > max_table_tokens:
            raise ValueError("dila_table_exceeds_embedding_context")
        chunks.append(table)
        offset = end
    prose(text[offset:])
    if "".join(chunks) != text:
        raise ValueError("dila_chunk_coverage_mismatch")
    return chunks
