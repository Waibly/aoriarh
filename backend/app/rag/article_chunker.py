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


# Detect article boundaries in markdown: ### Article L1234-5
_ARTICLE_HEADING = re.compile(
    r"(?m)^###\s+Article\s+.*$"
)

# Detect section headings: ## Partie législative > Livre I > ...
_SECTION_HEADING = re.compile(
    r"(?m)^##\s+(.+)$"
)

_ARTICLE_CHUNK_SIZE = 450  # Smaller than generic (1024) for more precise embeddings
_MIN_CHUNK_TOKENS = 15  # Discard chunks below this threshold (title-only ghosts)


@dataclass
class ChunkWithMeta:
    """A chunk with its structural metadata."""
    text: str
    article_nums: list[str] = field(default_factory=list)
    section_path: str = ""


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
    ) -> None:
        self.chunk_size = chunk_size
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
        current_num = ""
        current_lines: list[str] = []

        for line in text.split("\n"):
            # Check for section heading
            section_match = _SECTION_HEADING.match(line)
            if section_match:
                # Flush current article
                if current_lines and current_num:
                    articles.append(self._make_article(
                        current_section, current_num, current_lines
                    ))
                    current_lines = []
                current_section = section_match.group(1).strip()
                current_num = ""
                continue

            # Check for article heading
            article_match = _ARTICLE_HEADING.match(line)
            if article_match:
                # Flush previous article
                if current_lines and current_num:
                    articles.append(self._make_article(
                        current_section, current_num, current_lines
                    ))
                current_num = line.lstrip("#").strip()
                current_lines = [line]
                continue

            current_lines.append(line)

        # Flush last article
        if current_lines and current_num:
            articles.append(self._make_article(
                current_section, current_num, current_lines
            ))

        # Merge orphan titles: if an article has no real content (just the heading),
        # prepend it to the next article in the same section
        merged: list[dict] = []
        for i, art in enumerate(articles):
            # Check if this article is content-less (only the heading line)
            first_nl = art["content"].find("\n")
            content_after_heading = art["content"][first_nl + 1:].strip() if first_nl >= 0 else ""
            if not content_after_heading and i + 1 < len(articles) and articles[i + 1]["section"] == art["section"]:
                # Prepend this heading to next article's content
                articles[i + 1]["content"] = art["content"] + "\n\n" + articles[i + 1]["content"]
                articles[i + 1]["tokens"] = self._token_count(articles[i + 1]["content"])
                continue
            merged.append(art)

        return merged

    def _make_article(
        self, section: str, num: str, lines: list[str]
    ) -> dict:
        content = "\n".join(lines).strip()
        # num is e.g. "Article 33" or "Article L1332-4" (### already stripped)
        article_num = num.replace("Article ", "").strip() if num.startswith("Article") else num.strip()
        return {
            "section": section,
            "num": num,
            "article_num": article_num,
            "content": content,
            "tokens": self._token_count(content),
        }

    def _group_articles(self, articles: list[dict]) -> list[ChunkWithMeta]:
        """Group consecutive articles into chunks, flushing on section change."""
        chunks: list[ChunkWithMeta] = []
        current_parts: list[str] = []
        current_nums: list[str] = []
        current_tokens = 0
        current_section = ""

        def _flush():
            nonlocal current_parts, current_nums, current_tokens
            if current_parts:
                chunks.append(ChunkWithMeta(
                    text="\n\n".join(current_parts),
                    article_nums=list(current_nums),
                    section_path=current_section,
                ))
                current_parts = []
                current_nums = []
                current_tokens = 0

        for article in articles:
            # Section change → always flush (never mix sections)
            if article["section"] != current_section:
                _flush()
                current_section = article["section"]

            # Build the text for this article
            section_prefix = ""
            if not current_parts:
                # First article in this chunk: add section header
                section_prefix = f"## {current_section}\n\n" if current_section else ""

            article_text = section_prefix + article["content"]
            article_tokens = self._token_count(article_text)

            # If single article exceeds chunk_size, split it into smaller pieces
            if article_tokens > self.chunk_size:
                _flush()
                sub_chunks = self._split_large_article(
                    article_text, current_section, article["article_num"]
                )
                chunks.extend(sub_chunks)
                continue

            # If adding this article would exceed the limit, flush first
            if current_tokens + article_tokens > self.chunk_size:
                _flush()
                # Re-add section prefix since we're starting a new chunk
                article_text = (f"## {current_section}\n\n" if current_section else "") + article["content"]
                article_tokens = self._token_count(article_text)

            current_parts.append(article_text)
            current_nums.append(article["article_num"])
            current_tokens += article_tokens

        _flush()
        return chunks

    def _split_large_article(
        self, text: str, section: str, article_num: str
    ) -> list[ChunkWithMeta]:
        """Split an oversized article into chunks by paragraphs.

        Each continuation chunk is prefixed with a context line so it never
        starts in the middle of nowhere.
        """
        paragraphs = text.split("\n\n")
        chunks: list[ChunkWithMeta] = []
        current_parts: list[str] = []
        current_tokens = 0
        is_first_chunk = True

        # Context prefix for continuation chunks
        cont_prefix = ""
        if section:
            cont_prefix += f"## {section}\n\n"
        cont_prefix += f"### Article {article_num} (suite)\n\n"
        cont_prefix_tokens = self._token_count(cont_prefix)

        for para in paragraphs:
            para_tokens = self._token_count(para)

            # Single paragraph exceeds chunk_size — force-split by characters
            if para_tokens > self.chunk_size:
                if current_parts:
                    chunks.append(ChunkWithMeta(
                        text="\n\n".join(current_parts),
                        article_nums=[article_num],
                        section_path=section,
                    ))
                    current_parts = []
                    current_tokens = 0
                    is_first_chunk = False
                max_chars = self.chunk_size * 4
                for i in range(0, len(para), max_chars):
                    piece = para[i : i + max_chars]
                    if not is_first_chunk:
                        piece = cont_prefix + piece
                    chunks.append(ChunkWithMeta(
                        text=piece,
                        article_nums=[article_num],
                        section_path=section,
                    ))
                    is_first_chunk = False
                continue

            # Reserve space for continuation prefix in non-first chunks
            effective_limit = self.chunk_size
            if not is_first_chunk and not current_parts:
                effective_limit = self.chunk_size - cont_prefix_tokens

            if current_tokens + para_tokens > effective_limit and current_parts:
                chunks.append(ChunkWithMeta(
                    text="\n\n".join(current_parts),
                    article_nums=[article_num],
                    section_path=section,
                ))
                current_parts = []
                current_tokens = 0
                is_first_chunk = False

            # Add continuation prefix at the start of each non-first chunk
            if not is_first_chunk and not current_parts:
                current_parts.append(cont_prefix.rstrip())
                current_tokens += cont_prefix_tokens

            current_parts.append(para)
            current_tokens += para_tokens

        if current_parts:
            chunks.append(ChunkWithMeta(
                text="\n\n".join(current_parts),
                article_nums=[article_num],
                section_path=section,
            ))

        return chunks

    def _token_count(self, text: str) -> int:
        return len(self._enc.encode(text))
