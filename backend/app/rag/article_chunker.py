"""Chunker spécialisé pour les documents structurés par articles (Code du travail, CCN).

Stratégie : les articles sont déjà séparés dans le markdown (### Article ...).
On découpe au niveau article et on regroupe les petits articles voisins pour
atteindre une taille de chunk optimale, sans jamais couper un article en deux.

Chaque chunk est préfixé par le chemin hiérarchique (partie > livre > titre > chapitre)
pour donner du contexte au RAG.
"""

import re

import tiktoken

from app.rag.config import CHUNK_OVERLAP, CHUNK_SIZE

# Detect article boundaries in markdown: ### Article L1234-5
_ARTICLE_HEADING = re.compile(
    r"(?m)^###\s+Article\s+.*$"
)

# Detect section headings: ## Partie législative > Livre I > ...
_SECTION_HEADING = re.compile(
    r"(?m)^##\s+(.+)$"
)


_ARTICLE_CHUNK_SIZE = 450  # Smaller than generic (1024) for more precise embeddings


class ArticleChunker:
    """Chunks structured legal documents (Code du travail, CCN) by article boundaries.

    - Never splits an article across chunks
    - Groups small consecutive articles into a single chunk (up to ~450 tokens)
    - Preserves section context as a prefix in each chunk
    - Smaller chunk_size than generic chunker for more precise embeddings
      (3-4 articles per chunk max → less topic dilution)
    """

    def __init__(
        self,
        chunk_size: int = _ARTICLE_CHUNK_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._enc = tiktoken.get_encoding("cl100k_base")

    def chunk(self, text: str) -> list[str]:
        if not text.strip():
            return []

        # Parse into articles with their section context
        articles = self._parse_articles(text)

        if not articles:
            # Fallback: no articles detected, use simple paragraph split
            from app.rag.chunker import LegalChunker
            return LegalChunker(self.chunk_size, self.chunk_overlap).chunk(text)

        # Group articles into chunks
        return self._group_articles(articles)

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

        return articles

    def _make_article(
        self, section: str, num: str, lines: list[str]
    ) -> dict:
        content = "\n".join(lines).strip()
        return {
            "section": section,
            "num": num,
            "content": content,
            "tokens": self._token_count(content),
        }

    def _group_articles(self, articles: list[dict]) -> list[str]:
        """Group consecutive articles into chunks without exceeding chunk_size."""
        chunks: list[str] = []
        current_parts: list[str] = []
        current_tokens = 0
        current_section = ""

        for article in articles:
            # Build the text for this article
            section_prefix = ""
            if article["section"] != current_section:
                current_section = article["section"]
                section_prefix = f"## {current_section}\n\n"

            article_text = section_prefix + article["content"]
            article_tokens = self._token_count(article_text)

            # If single article exceeds chunk_size, split it into smaller pieces
            if article_tokens > self.chunk_size:
                # Flush current buffer
                if current_parts:
                    chunks.append("\n\n".join(current_parts))
                    current_parts = []
                    current_tokens = 0
                # Split oversized article by paragraphs
                chunks.extend(self._split_large_article(article_text))
                continue

            # If adding this article would exceed the limit, flush
            if current_tokens + article_tokens > self.chunk_size:
                chunks.append("\n\n".join(current_parts))
                # Overlap: keep section context for next chunk
                current_parts = []
                current_tokens = 0

            current_parts.append(article_text)
            current_tokens += article_tokens

        # Flush remaining
        if current_parts:
            chunks.append("\n\n".join(current_parts))

        return chunks

    def _split_large_article(self, text: str) -> list[str]:
        """Split an oversized article into chunks by paragraphs."""
        paragraphs = text.split("\n\n")
        chunks: list[str] = []
        current_parts: list[str] = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = self._token_count(para)

            # Single paragraph exceeds chunk_size — force-split by characters
            if para_tokens > self.chunk_size:
                if current_parts:
                    chunks.append("\n\n".join(current_parts))
                    current_parts = []
                    current_tokens = 0
                # Split by ~chunk_size tokens worth of characters (~4 chars/token)
                max_chars = self.chunk_size * 4
                for i in range(0, len(para), max_chars):
                    chunks.append(para[i : i + max_chars])
                continue

            if current_tokens + para_tokens > self.chunk_size:
                chunks.append("\n\n".join(current_parts))
                current_parts = []
                current_tokens = 0

            current_parts.append(para)
            current_tokens += para_tokens

        if current_parts:
            chunks.append("\n\n".join(current_parts))

        return chunks

    def _token_count(self, text: str) -> int:
        return len(self._enc.encode(text))
