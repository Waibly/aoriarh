import re

import tiktoken

from app.rag.config import CHUNK_OVERLAP, CHUNK_SIZE

# Patterns to detect structural sections of a French court decision.
# Supports both traditional "Attendu que" style and post-2019 "direct" style.

# --- Header / References ---
_HEADER_PATTERNS = [
    re.compile(r"(?m)^(?:COUR DE CASSATION|CONSEIL D.ÉTAT|CONSEIL CONSTITUTIONNEL)", re.IGNORECASE),
    re.compile(r"(?m)^(?:Chambre\s+\w+|Assemblée\s+plénière|Section\s+\w+)", re.IGNORECASE),
    re.compile(r"(?m)^Audience\s+publique\s+du\s+", re.IGNORECASE),
    re.compile(r"(?m)^(?:Arrêt|Décision)\s+n[°o]\s*", re.IGNORECASE),
    re.compile(r"(?m)^Pourvoi\s+n[°o]\s*", re.IGNORECASE),
]

# --- Structural sections of a decision ---
_SECTION_MARKERS = [
    # Facts and procedure
    (re.compile(r"(?mi)^(?:FAITS\s+ET\s+PROC[EÉ]DURE|Faits\s+et\s+proc[eé]dure)\s*$"), "faits"),
    (re.compile(r"(?mi)^(?:Sur\s+le\s+rapport\s+de\s+)"), "faits"),
    # Moyens (grounds of appeal)
    (re.compile(r"(?mi)^(?:EXAMEN\s+DES?\s+MOYENS?|Examen\s+des?\s+moyens?)\s*$"), "moyens"),
    (re.compile(r"(?mi)^(?:Sur\s+le\s+(?:premier|deuxième|troisième|quatrième|unique|moyen)\s+moyen)"), "moyens"),
    (re.compile(r"(?mi)^(?:MOYEN\s+(?:UNIQUE|ANNEXÉ|DE\s+CASSATION))"), "moyens"),
    # Motifs / Reasoning — THE KEY PART
    (re.compile(r"(?mi)^(?:MOTIFS\s+DE\s+LA\s+D[EÉ]CISION|Motifs)\s*$"), "motifs"),
    (re.compile(r"(?mi)^(?:R[EÉ]PONSE\s+DE\s+LA\s+COUR)\s*$"), "motifs"),
    (re.compile(r"(?mi)^(?:Vu\s+l[ea']?\s*(?:article|principe|règle))"), "motifs"),
    (re.compile(r"(?mi)^(?:Attendu\s+que\b)"), "motifs"),
    (re.compile(r"(?mi)^(?:Il\s+résulte\s+de\s+ce\s+qui\s+précède)"), "motifs"),
    # Dispositif (ruling)
    (re.compile(r"(?mi)^(?:PAR\s+CES\s+MOTIFS|Par\s+ces\s+motifs)\s*"), "dispositif"),
    (re.compile(r"(?mi)^(?:CASSE\s+ET\s+ANNULE|REJETTE)\b"), "dispositif"),
    (re.compile(r"(?mi)^(?:D[EÉ]CIDE|STATUE)\s*:?\s*$"), "dispositif"),
]


def _classify_line(line: str) -> str | None:
    """Return the section label if the line matches a section marker, else None."""
    stripped = line.strip()
    if not stripped:
        return None
    for pattern, label in _SECTION_MARKERS:
        if pattern.search(stripped):
            return label
    return None


def _is_header_line(line: str) -> bool:
    stripped = line.strip()
    return any(p.search(stripped) for p in _HEADER_PATTERNS)


class JurisprudenceChunker:
    """Chunks French court decisions by structural section.

    Strategy:
    1. Parse the decision into semantic sections (faits, moyens, motifs, dispositif).
    2. Each section becomes one or more chunks.
    3. The "motifs" (reasoning) section is the most important — it is always
       prefixed with a header indicating the court and case reference.
    4. If the text cannot be parsed structurally, falls back to paragraph-based
       chunking (same as LegalChunker).
    """

    def __init__(
        self,
        chunk_size: int = CHUNK_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._enc = tiktoken.get_encoding("cl100k_base")

    def chunk(self, text: str, metadata_header: str = "") -> list[str]:
        """Split a court decision into chunks.

        Args:
            text: The full text of the decision.
            metadata_header: Optional header to prepend to each chunk
                (e.g. "Cass. soc., 15 mars 2023, n° 21-14.490").
        """
        if not text.strip():
            return []

        sections = self._parse_sections(text)

        # If we couldn't detect any structural sections, fall back to paragraphs
        if len(sections) <= 1:
            return self._chunk_by_paragraphs(text, metadata_header)

        chunks: list[str] = []
        for label, content in sections:
            section_header = self._section_label_fr(label)
            prefix = f"{metadata_header}\n{section_header}\n\n" if metadata_header else f"{section_header}\n\n"
            prefix_tokens = self._token_count(prefix)

            effective_size = self.chunk_size - prefix_tokens
            if effective_size < 100:
                effective_size = self.chunk_size

            section_chunks = self._split_text(content.strip(), effective_size)
            for sc in section_chunks:
                chunks.append(f"{prefix}{sc}")

        return chunks

    def _parse_sections(self, text: str) -> list[tuple[str, str]]:
        """Parse text into labeled sections: (label, content)."""
        lines = text.split("\n")
        sections: list[tuple[str, str]] = []
        current_label = "en-tete"
        current_lines: list[str] = []

        for line in lines:
            # Skip pure header lines (court name, date, etc.) — keep in en-tete
            if current_label == "en-tete" and _is_header_line(line):
                current_lines.append(line)
                continue

            detected = _classify_line(line)
            if detected and detected != current_label:
                # Flush previous section
                if current_lines:
                    sections.append((current_label, "\n".join(current_lines)))
                current_label = detected
                current_lines = [line]
            else:
                current_lines.append(line)

        # Flush last section
        if current_lines:
            sections.append((current_label, "\n".join(current_lines)))

        return sections

    def _split_text(self, text: str, max_tokens: int) -> list[str]:
        """Split text into chunks respecting token limits, splitting on paragraphs/sentences."""
        if self._token_count(text) <= max_tokens:
            return [text]

        # Split by paragraphs first
        paragraphs = re.split(r"\n\n+", text)
        chunks: list[str] = []
        current_parts: list[str] = []
        current_count = 0

        for para in paragraphs:
            p_count = self._token_count(para)

            if p_count > max_tokens:
                # Flush current buffer
                if current_parts:
                    chunks.append("\n\n".join(current_parts))
                    current_parts = []
                    current_count = 0
                # Force-split oversized paragraph
                chunks.extend(self._force_split(para, max_tokens))
                continue

            if current_count + p_count > max_tokens:
                chunks.append("\n\n".join(current_parts))
                # Keep last paragraph for overlap
                overlap_parts: list[str] = []
                overlap_count = 0
                for p in reversed(current_parts):
                    pc = self._token_count(p)
                    if overlap_count + pc > self.chunk_overlap:
                        break
                    overlap_parts.insert(0, p)
                    overlap_count += pc
                current_parts = overlap_parts
                current_count = overlap_count

            current_parts.append(para)
            current_count += p_count

        if current_parts:
            chunks.append("\n\n".join(current_parts))

        return chunks

    def _chunk_by_paragraphs(self, text: str, metadata_header: str) -> list[str]:
        """Fallback: chunk by paragraphs when no structural sections detected."""
        prefix = f"{metadata_header}\n\n" if metadata_header else ""
        prefix_tokens = self._token_count(prefix) if prefix else 0
        effective_size = self.chunk_size - prefix_tokens

        raw_chunks = self._split_text(text, effective_size)
        if prefix:
            return [f"{prefix}{c}" for c in raw_chunks]
        return raw_chunks

    def _force_split(self, text: str, max_tokens: int) -> list[str]:
        tokens = self._enc.encode(text)
        step = max_tokens - self.chunk_overlap
        if step < 1:
            step = max_tokens
        chunks: list[str] = []
        for i in range(0, len(tokens), step):
            chunk_tokens = tokens[i : i + max_tokens]
            chunks.append(self._enc.decode(chunk_tokens))
        return chunks

    def _token_count(self, text: str) -> int:
        return len(self._enc.encode(text))

    @staticmethod
    def _section_label_fr(label: str) -> str:
        labels = {
            "en-tete": "[En-tête]",
            "faits": "[Faits et procédure]",
            "moyens": "[Moyens du pourvoi]",
            "motifs": "[Motifs de la décision]",
            "dispositif": "[Dispositif]",
        }
        return labels.get(label, f"[{label.capitalize()}]")
