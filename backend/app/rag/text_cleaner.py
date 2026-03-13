import re
import unicodedata

# Pattern matching legal structural headings (titles, chapters, sections, etc.)
_HEADING_RE = re.compile(
    r"^\s*("
    r"Partie\s+\S+"
    r"|Livre\s+\S+"
    r"|Titre\s+\S+"
    r"|Chapitre\s+\S+"
    r"|Section\s+\S+"
    r"|Sous-section\s+\S+"
    r"|Paragraphe\s+\S+"
    r"|Art(?:icle)?\.?\s*[LRD]?\d[\d.\-]*"
    r"|Table\s+des\s+matières"
    r"|Sommaire"
    r")",
    re.IGNORECASE,
)

# Minimum consecutive heading-only lines to consider it a TOC block
_TOC_MIN_CONSECUTIVE = 6


def _remove_toc_blocks(text: str) -> str:
    """Remove table-of-contents blocks (sequences of heading-only lines)."""
    lines = text.split("\n")
    to_remove: set[int] = set()
    run_start = -1
    run_length = 0  # count of heading lines (not blanks)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            # Blank lines don't break a heading run
            continue
        if _HEADING_RE.match(stripped) and len(stripped) < 120:
            if run_start == -1:
                run_start = i
            run_length += 1
        else:
            # Non-heading, non-blank line — end of run
            if run_length >= _TOC_MIN_CONSECUTIVE:
                for j in range(run_start, i):
                    to_remove.add(j)
            run_start = -1
            run_length = 0

    # Handle run at end of text
    if run_length >= _TOC_MIN_CONSECUTIVE:
        for j in range(run_start, len(lines)):
            to_remove.add(j)

    if not to_remove:
        return text

    return "\n".join(line for i, line in enumerate(lines) if i not in to_remove)


def clean_text(text: str) -> str:
    """Clean extracted text for RAG indexation."""
    # Remove zero-width chars and control characters (keep newlines and tabs)
    text = "".join(
        ch for ch in text
        if ch in ("\n", "\t", "\r") or not unicodedata.category(ch).startswith("C")
    )

    # Remove repeated headers/footers
    text = re.sub(r"(?mi)^Page\s+\d+\s+sur\s+\d+\s*$", "", text)
    text = re.sub(r"(?mi)^Page\s+\d+\s*/\s*\d+\s*$", "", text)
    text = re.sub(r"(?m)^\s*\d+\s*$", "", text)  # Lone page numbers

    # Normalize typographic characters
    text = text.replace("\u2018", "'").replace("\u2019", "'")  # Smart quotes
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")  # Dashes
    text = text.replace("\u00a0", " ")  # Non-breaking space
    text = text.replace("\u200b", "")  # Zero-width space

    # Merge broken lines (line not ending with sentence-end punctuation,
    # followed by a line starting with lowercase)
    text = re.sub(
        r"(?m)([^.!?:;\n])\n([a-zà-ÿ])",
        r"\1 \2",
        text,
    )

    # Remove TOC blocks (consecutive heading-only lines)
    text = _remove_toc_blocks(text)

    # Normalize multiple blank lines to max 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Normalize multiple spaces
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip()
