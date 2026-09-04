"""Chunker spécialisé pour les documents structurés par articles (Code du travail, CCN).

Stratégie : les articles sont déjà séparés dans le markdown (### Article ...).
On découpe au niveau article et on regroupe les petits articles voisins pour
atteindre une taille de chunk optimale, sans jamais couper un article en deux
et sans jamais mélanger des articles de sections différentes.

Chaque chunk est préfixé par le chemin hiérarchique (partie > livre > titre > chapitre)
pour donner du contexte au RAG.

Retourne des ChunkWithMeta contenant le texte + les metadata structurelles
(numéros d'articles, chemin de section).
"""

import re
from dataclasses import dataclass, field

import tiktoken

from app.rag.chunker import contains_markdown_table, force_split_on_boundary
from app.rag.config import CHUNK_OVERLAP

# Detect article boundaries both in Markdown sources and in historical JORF
# plain-text files: ### Article L1234-5 / Article 3.
_ARTICLE_HEADING = re.compile(r"(?m)^(?:###\s+)?Article\s+.*$")

# Detect section headings: ## Partie législative > Livre I > ...
_SECTION_HEADING = re.compile(r"(?m)^##\s+(.+)$")

_ARTICLE_CHUNK_SIZE = 450  # Smaller than generic (1024) for more precise embeddings
_ARTICLE_CHUNK_OVERLAP = CHUNK_OVERLAP  # Reused when falling back to LegalChunker
_MIN_CHUNK_TOKENS = 15  # Discard chunks below this threshold (title-only ghosts)

# Structural subdivisions commonly found in laws, decrees and ordinances.
# They are stronger split points than ordinary wrapped lines.
_LEGAL_SUBDIVISION_START = re.compile(
    r"^[«\"“]?\s*(?:"
    r"[IVXLCDM]+\s*(?:[.-]\s*)+"  # I.- / II. / IV-
    r"|[A-Z]\s*(?:[.-]\s*)+"  # A.- / B.
    r"|\d+\s*°"  # 1° / 12 °
    r"|[a-z]\s*\)"  # a) / b)
    r"|[-•]\s+"  # tiret de subdivision
    r"|(?:Sous-)?Section\s+"
    r"|Chapitre\s+"
    r"|Art(?:icle)?\.?\s+[LRD]?\s*\d"
    r")",
    re.IGNORECASE,
)


@dataclass
class ChunkWithMeta:
    """A chunk with its structural metadata."""

    text: str
    article_nums: list[str] = field(default_factory=list)
    section_path: str = ""
    instrument_id: str = ""
    instrument_title: str = ""
    effective_from: str = ""
    effective_to: str = ""
    instrument_status: str = ""


class ArticleChunker:
    """Chunks structured legal documents (Code du travail, CCN) by article boundaries.

    - Never splits an article across chunks
    - Never mixes articles from different sections in the same chunk
    - Groups small consecutive articles from the SAME section (up to ~450 tokens)
    - Preserves section context as a prefix in each chunk
    - Smaller chunk_size than generic chunker for more precise embeddings
    - Returns ChunkWithMeta with article_nums and section_path metadata
    """

    def __init__(
        self,
        chunk_size: int = _ARTICLE_CHUNK_SIZE,
        chunk_overlap: int = _ARTICLE_CHUNK_OVERLAP,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._enc = tiktoken.get_encoding("cl100k_base")

    def chunk(self, text: str) -> list[str]:
        """Return plain text chunks (backward-compatible interface)."""
        return [c.text for c in self.chunk_with_meta(text)]

    def chunk_with_meta(self, text: str) -> list[ChunkWithMeta]:
        if not text.strip():
            return []

        # Parse into articles with their section context
        articles = self._parse_articles(text)

        if not articles:
            # Fallback: no articles detected, use simple paragraph split
            from app.rag.chunker import LegalChunker

            plain = LegalChunker(self.chunk_size, self.chunk_overlap).chunk(text)
            return [ChunkWithMeta(text=t) for t in plain]

        # Group articles into chunks (respecting section boundaries)
        chunks = self._group_articles(articles)

        # Filter out tiny ghost chunks (title-only)
        return [c for c in chunks if self._token_count(c.text) >= _MIN_CHUNK_TOKENS]

    def _parse_articles(self, text: str) -> list[dict]:
        """Parse markdown into a list of {section, num, content, tokens}."""
        articles: list[dict] = []
        current_section = ""
        current_instrument: dict[str, str] = {}
        current_num = ""
        current_lines: list[str] = []

        for line in text.split("\n"):
            # Check for section heading
            section_match = _SECTION_HEADING.match(line)
            if section_match:
                # Flush current article
                if current_lines and current_num:
                    articles.append(
                        self._make_article(
                            current_section,
                            current_num,
                            current_lines,
                            current_instrument,
                        )
                    )
                    current_lines = []
                heading = section_match.group(1).strip()
                if heading.startswith("Source juridique :"):
                    current_instrument = {
                        "instrument_title": heading.split(":", 1)[1].strip(),
                    }
                    current_section = ""
                else:
                    current_instrument = {}
                    current_section = heading
                current_num = ""
                continue

            # Structured KALI parent metadata is deliberately part of the
            # readable markdown. Parse it before the first article so it can
            # also be copied to the Qdrant payload.
            if not current_num and current_instrument:
                if line.startswith("Référence :"):
                    current_instrument["instrument_id"] = line.split(":", 1)[1].strip()
                    continue
                if line.startswith("Entrée en vigueur :"):
                    current_instrument["effective_from"] = line.split(":", 1)[1].strip()
                    continue
                if line.startswith("Fin d'effet :"):
                    current_instrument["effective_to"] = line.split(":", 1)[1].strip()
                    continue
                if line.startswith("Statut :"):
                    current_instrument["instrument_status"] = line.split(":", 1)[1].strip()
                    continue
                if line.startswith("Section :"):
                    current_section = line.split(":", 1)[1].strip()
                    continue

            # Check for article heading
            article_match = _ARTICLE_HEADING.match(line)
            if article_match:
                # Flush previous article
                if current_lines and current_num:
                    articles.append(
                        self._make_article(
                            current_section,
                            current_num,
                            current_lines,
                            current_instrument,
                        )
                    )
                current_num = line.lstrip("#").strip()
                # Normalize historical JORF plain-text headings so retrieved
                # chunks render consistently in the Markdown source viewer.
                current_lines = [f"### {current_num}"]
                continue

            current_lines.append(line)

        # Flush last article
        if current_lines and current_num:
            articles.append(
                self._make_article(
                    current_section,
                    current_num,
                    current_lines,
                    current_instrument,
                )
            )

        # Merge orphan titles: if an article has no real content (just the heading),
        # prepend it to the next article in the same section
        merged: list[dict] = []
        for i, art in enumerate(articles):
            # Check if this article is content-less (only the heading line)
            first_nl = art["content"].find("\n")
            content_after_heading = art["content"][first_nl + 1 :].strip() if first_nl >= 0 else ""
            same_parent = (
                i + 1 < len(articles)
                and articles[i + 1]["section"] == art["section"]
                and articles[i + 1].get("instrument_id", "") == art.get("instrument_id", "")
            )
            if not content_after_heading and same_parent:
                # Prepend this heading to next article's content
                articles[i + 1]["content"] = art["content"] + "\n\n" + articles[i + 1]["content"]
                articles[i + 1]["tokens"] = self._token_count(articles[i + 1]["content"])
                continue
            merged.append(art)

        return merged

    def _make_article(
        self,
        section: str,
        num: str,
        lines: list[str],
        instrument: dict[str, str] | None = None,
    ) -> dict:
        content = "\n".join(lines).strip()
        # num is e.g. "Article 33" or "Article L1332-4" (### already stripped)
        article_num = (
            num.replace("Article ", "").strip() if num.startswith("Article") else num.strip()
        )
        return {
            "section": section,
            "num": num,
            "article_num": article_num,
            "content": content,
            "tokens": self._token_count(content),
            **(instrument or {}),
        }

    def _group_articles(self, articles: list[dict]) -> list[ChunkWithMeta]:
        """Group consecutive articles into chunks, flushing on section change."""
        chunks: list[ChunkWithMeta] = []
        current_parts: list[str] = []
        current_nums: list[str] = []
        current_tokens = 0
        current_section = ""
        current_instrument: dict[str, str] = {}

        def _flush():
            nonlocal current_parts, current_nums, current_tokens
            if current_parts:
                chunks.append(
                    ChunkWithMeta(
                        text="\n\n".join(current_parts),
                        article_nums=list(current_nums),
                        section_path=current_section,
                        **current_instrument,
                    )
                )
                current_parts = []
                current_nums = []
                current_tokens = 0

        for article in articles:
            article_instrument = {
                "instrument_id": article.get("instrument_id", ""),
                "instrument_title": article.get("instrument_title", ""),
                "effective_from": article.get("effective_from", ""),
                "effective_to": article.get("effective_to", ""),
                "instrument_status": article.get("instrument_status", ""),
            }
            # Section or legal instrument change → always flush. Successive
            # salary agreements must never be merged into the same chunk.
            if article["section"] != current_section or article_instrument != current_instrument:
                _flush()
                current_section = article["section"]
                current_instrument = article_instrument

            # Build the text for this article
            section_prefix = ""
            if not current_parts:
                # First article in this chunk: add section header
                section_prefix = self._context_prefix(
                    current_section,
                    current_instrument,
                )

            article_text = section_prefix + article["content"]
            article_tokens = self._token_count(article_text)

            # If single article exceeds chunk_size, split it into smaller pieces
            if article_tokens > self.chunk_size:
                _flush()
                sub_chunks = self._split_large_article(
                    article_text,
                    current_section,
                    article["article_num"],
                    current_instrument,
                )
                chunks.extend(sub_chunks)
                continue

            # If adding this article would exceed the limit, flush first
            if current_tokens + article_tokens > self.chunk_size:
                _flush()
                # Re-add section prefix since we're starting a new chunk
                article_text = (
                    self._context_prefix(
                        current_section,
                        current_instrument,
                    )
                    + article["content"]
                )
                article_tokens = self._token_count(article_text)

            current_parts.append(article_text)
            current_nums.append(article["article_num"])
            current_tokens += article_tokens

        _flush()
        return chunks

    def _split_large_article(
        self,
        text: str,
        section: str,
        article_num: str,
        instrument: dict[str, str] | None = None,
    ) -> list[ChunkWithMeta]:
        """Split an oversized article on legal subdivisions and paragraphs.

        Each continuation chunk is prefixed with a context line so it never
        starts in the middle of nowhere. If a single subdivision remains too
        large, prefer punctuation (including semicolons) and disable overlap:
        the repeated article heading provides context without making the next
        chunk begin halfway through a reference.
        """
        chunks: list[ChunkWithMeta] = []
        current_parts: list[str] = []
        current_tokens = 0
        is_first_chunk = True

        # Context prefix for continuation chunks
        instrument = instrument or {}
        cont_prefix = self._context_prefix(section, instrument)
        cont_prefix += f"### Article {article_num} (suite)\n\n"
        cont_prefix_tokens = self._token_count(cont_prefix)

        body_limit = max(1, self.chunk_size - cont_prefix_tokens)
        atomic_parts: list[str] = []
        for block in self._split_legal_blocks(text):
            if self._token_count(block) <= body_limit or contains_markdown_table(block):
                atomic_parts.append(block)
            else:
                atomic_parts.extend(
                    force_split_on_boundary(
                        block,
                        self._enc,
                        body_limit,
                        overlap=0,
                    )
                )

        for part in atomic_parts:
            part_tokens = self._token_count(part)
            if current_parts and current_tokens + part_tokens > self.chunk_size:
                chunks.append(
                    ChunkWithMeta(
                        text="\n\n".join(current_parts),
                        article_nums=[article_num],
                        section_path=section,
                        **instrument,
                    )
                )
                current_parts = []
                current_tokens = 0
                is_first_chunk = False

            if not is_first_chunk and not current_parts:
                current_parts.append(cont_prefix.rstrip())
                current_tokens += cont_prefix_tokens

            current_parts.append(part)
            current_tokens += part_tokens

        if current_parts:
            chunks.append(
                ChunkWithMeta(
                    text="\n\n".join(current_parts),
                    article_nums=[article_num],
                    section_path=section,
                    **instrument,
                )
            )

        return chunks

    @staticmethod
    def _split_legal_blocks(text: str) -> list[str]:
        """Keep prose together but start a block at each legal subdivision."""

        blocks: list[str] = []
        current_lines: list[str] = []

        def _flush() -> None:
            if current_lines:
                blocks.append("\n".join(current_lines).strip())
                current_lines.clear()

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                _flush()
                continue
            if current_lines and _LEGAL_SUBDIVISION_START.match(line):
                _flush()
            current_lines.append(line)

        _flush()
        return [block for block in blocks if block]

    @staticmethod
    def _context_prefix(section: str, instrument: dict[str, str]) -> str:
        """Readable parent context prepended to every indexed article chunk."""
        lines: list[str] = []
        title = instrument.get("instrument_title", "")
        if title:
            lines.append(f"## Source juridique : {title}")
            if instrument.get("instrument_id"):
                lines.append(f"Référence : {instrument['instrument_id']}")
            if instrument.get("effective_from"):
                lines.append(f"Entrée en vigueur : {instrument['effective_from']}")
            if instrument.get("effective_to"):
                lines.append(f"Fin d'effet : {instrument['effective_to']}")
            if instrument.get("instrument_status"):
                lines.append(f"Statut : {instrument['instrument_status']}")
            if section:
                lines.append(f"Section : {section}")
        elif section:
            lines.append(f"## {section}")
        return "\n".join(lines) + "\n\n" if lines else ""

    def _token_count(self, text: str) -> int:
        return len(self._enc.encode(text))
