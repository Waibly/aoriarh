import re

import tiktoken

from app.rag.config import CHUNK_OVERLAP, CHUNK_SIZE

# Legal article patterns (no Markdown headings — those are handled by Strategy 2)
ARTICLE_PATTERN = re.compile(
    r"(?m)^(?="
    r"(?:Art(?:icle)?\.?\s*[LRD]?\d[\d.\-]*)"  # Article L1234-5, Art. R123
    r"|(?:Section\s+\d+)"
    r"|(?:Chapitre\s+[IVXLCDM]+)"
    r"|(?:Titre\s+[IVXLCDM]+)"
    r")"
)

MARKDOWN_HEADING_PATTERN = re.compile(r"(?m)^(?=#{1,4}\s)")

# A markdown table starts with a header row "| ... |" followed by a
# separator row "| --- | --- |". Used to detect table blocks so the
# chunker can treat them atomically (cf. _chunk_by_sentences).
_TABLE_HEAD = re.compile(r"^\s*\|.*\|\s*\n\s*\|[\s:|-]+\|", re.MULTILINE)


def contains_markdown_table(text: str) -> bool:
    """Cheap detector — used both for chunking and for the has_table flag
    propagated to Qdrant payload metadata."""
    return bool(_TABLE_HEAD.search(text))


class LegalChunker:
    """Chunks legal text with article-aware splitting."""

    def __init__(
        self,
        chunk_size: int = CHUNK_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._enc = tiktoken.get_encoding("cl100k_base")

    # Max tokens for a section to be considered "title-only" and merged with next
    _TITLE_ONLY_MAX_TOKENS = 30

    def chunk(self, text: str) -> list[str]:
        if not text.strip():
            return []

        # Strategy 1: Try legal article splitting
        sections = ARTICLE_PATTERN.split(text)
        sections = [s.strip() for s in sections if s.strip()]

        if len(sections) > 1:
            sections = self._merge_title_only_sections(sections)
            return self._chunk_sections(sections)

        # Strategy 2: Try Markdown heading splitting
        md_sections = MARKDOWN_HEADING_PATTERN.split(text)
        md_sections = [s.strip() for s in md_sections if s.strip()]

        if len(md_sections) > 1:
            md_sections = self._merge_title_only_sections(md_sections)
            return self._chunk_sections(md_sections)

        # Strategy 3: Fallback — paragraph/sentence splitting
        return self._chunk_by_sentences(text)

    def _merge_title_only_sections(self, sections: list[str]) -> list[str]:
        """Merge title-only sections with the following section as a prefix."""
        if not sections:
            return sections

        merged: list[str] = []
        pending_prefix = ""

        for section in sections:
            if self._token_count(section) <= self._TITLE_ONLY_MAX_TOKENS:
                # This section is just a title — accumulate as prefix
                pending_prefix = f"{pending_prefix}\n{section}".strip() if pending_prefix else section
            else:
                if pending_prefix:
                    section = f"{pending_prefix}\n\n{section}"
                    pending_prefix = ""
                merged.append(section)

        # If trailing titles remain, attach to last chunk or keep as-is
        if pending_prefix:
            if merged:
                merged[-1] = f"{merged[-1]}\n\n{pending_prefix}"
            else:
                merged.append(pending_prefix)

        return merged

    def _token_count(self, text: str) -> int:
        return len(self._enc.encode(text))

    def _chunk_sections(self, sections: list[str]) -> list[str]:
        chunks: list[str] = []
        for section in sections:
            if self._token_count(section) <= self.chunk_size:
                chunks.append(section)
            else:
                # Extract header (first line) to preserve in each sub-chunk
                lines = section.split("\n", 1)
                header = lines[0].strip()
                body = lines[1].strip() if len(lines) > 1 else ""

                if not body:
                    chunks.extend(self._force_split(section))
                else:
                    header_tokens = self._token_count(header + "\n\n")
                    sub_chunks = self._chunk_by_sentences(
                        body,
                        reserved_tokens=header_tokens,
                    )
                    for sub in sub_chunks:
                        chunks.append(f"{header}\n\n{sub}")
        return chunks

    def _chunk_by_sentences(
        self, text: str, reserved_tokens: int = 0
    ) -> list[str]:
        effective_size = self.chunk_size - reserved_tokens

        # Split into paragraphs first
        paragraphs = re.split(r"\n\n+", text)
        sentences: list[str] = []
        for para in paragraphs:
            stripped = para.strip()
            if not stripped:
                continue
            # Tables are kept as a single atomic "sentence" — we never split
            # inside the pipe rows, otherwise both rendering and embeddings
            # become garbage.
            if contains_markdown_table(stripped):
                sentences.append(stripped)
                continue
            # Split sentences on period/exclamation/question followed by space or end
            parts = re.split(r"(?<=[.!?])\s+", stripped)
            sentences.extend(p for p in parts if p.strip())

        if not sentences:
            return [text] if text.strip() else []

        chunks: list[str] = []
        current_tokens: list[str] = []
        current_count = 0

        for sentence in sentences:
            s_count = self._token_count(sentence)

            # Markdown tables must NEVER be force-split: a table cut at an
            # arbitrary token boundary becomes unreadable junk and breaks
            # the rendering downstream. We keep it as its own chunk even
            # if it slightly exceeds chunk_size.
            if contains_markdown_table(sentence):
                if current_tokens:
                    chunks.append(" ".join(current_tokens))
                    current_tokens = []
                    current_count = 0
                chunks.append(sentence)
                continue

            if s_count > effective_size:
                # Flush current buffer
                if current_tokens:
                    chunks.append(" ".join(current_tokens))
                    current_tokens = []
                    current_count = 0
                # Force-split oversized sentence by tokens
                chunks.extend(self._force_split(sentence))
                continue

            if current_count + s_count > effective_size:
                chunks.append(" ".join(current_tokens))
                # Overlap: keep last sentences up to overlap token count
                overlap_tokens: list[str] = []
                overlap_count = 0
                for s in reversed(current_tokens):
                    sc = self._token_count(s)
                    if overlap_count + sc > self.chunk_overlap:
                        break
                    overlap_tokens.insert(0, s)
                    overlap_count += sc
                current_tokens = overlap_tokens
                current_count = overlap_count

            current_tokens.append(sentence)
            current_count += s_count

        if current_tokens:
            chunks.append(" ".join(current_tokens))

        return chunks

    def _force_split(self, text: str) -> list[str]:
        tokens = self._enc.encode(text)
        chunks: list[str] = []
        for i in range(0, len(tokens), self.chunk_size - self.chunk_overlap):
            chunk_tokens = tokens[i : i + self.chunk_size]
            chunks.append(self._enc.decode(chunk_tokens))
        return chunks
