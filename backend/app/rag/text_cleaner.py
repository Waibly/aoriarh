import re
import unicodedata


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

    # Normalize multiple blank lines to max 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Normalize multiple spaces
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip()
