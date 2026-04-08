"""HTML → Markdown converter (maison, sans dépendance externe).

Préserve les éléments structurels qui ont du sens pour le RAG juridique :
- tableaux (`<table>`) → markdown pipe `| col | col |`
- listes ordonnées et non ordonnées
- titres `<h1>`–`<h6>`
- gras / italique
- sauts de ligne (`<br>`) et paragraphes
- liens (texte conservé, URL aussi)

Le reste (styles, scripts, attributs) est jeté. Conçu pour les sources
qu'on ingère (KALI/CCN, Légifrance codes, BOCC HTML), où l'enjeu n°1
est de ne PAS aplatir les barèmes/grilles de salaire des conventions
collectives en blocs de texte illisibles.
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser


_BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer",
    "ul", "ol", "li", "blockquote", "pre",
}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _HtmlToMarkdown(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._stack: list[str] = []
        # Table state
        self._in_table = 0
        self._current_row: list[str] = []
        self._current_cell: list[str] | None = None
        self._is_header_row = False
        self._table_rows: list[tuple[bool, list[str]]] = []
        # List state (stack of (kind, counter))
        self._list_stack: list[tuple[str, int]] = []

    # ---- helpers ---------------------------------------------------------

    def _emit(self, text: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(text)
        else:
            self._out.append(text)

    def _newline(self, n: int = 1) -> None:
        self._emit("\n" * n)

    # ---- table flush -----------------------------------------------------

    def _flush_table(self) -> None:
        if not self._table_rows:
            return
        # Determine column count
        ncols = max(len(cells) for _, cells in self._table_rows)
        if ncols == 0:
            self._table_rows = []
            return

        # Find header row : first explicit header, else first row
        header_idx = next(
            (i for i, (is_h, _) in enumerate(self._table_rows) if is_h), 0,
        )

        def _norm(cells: list[str]) -> list[str]:
            cleaned = [
                re.sub(r"\s+", " ", c).replace("|", "\\|").strip()
                for c in cells
            ]
            cleaned += [""] * (ncols - len(cleaned))
            return cleaned

        header = _norm(self._table_rows[header_idx][1])
        body_rows = [
            _norm(cells)
            for i, (_, cells) in enumerate(self._table_rows)
            if i != header_idx
        ]
        # If header is empty (no real header), synthesize one
        if not any(h.strip() for h in header):
            header = [f"col{i + 1}" for i in range(ncols)]

        lines = ["", "| " + " | ".join(header) + " |"]
        lines.append("| " + " | ".join(["---"] * ncols) + " |")
        for row in body_rows:
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
        self._out.append("\n".join(lines))
        self._table_rows = []

    # ---- HTMLParser hooks ------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        if tag in ("script", "style"):
            self._stack.append(tag)
            return

        if tag == "br":
            self._emit("  \n")
            return

        if tag == "table":
            self._in_table += 1
            self._table_rows = []
            return
        if self._in_table:
            if tag == "tr":
                self._current_row = []
                self._is_header_row = False
                return
            if tag in ("td", "th"):
                self._current_cell = []
                if tag == "th":
                    self._is_header_row = True
                return

        if tag in _HEADING_TAGS:
            level = int(tag[1])
            self._newline(2)
            self._emit("#" * level + " ")
            self._stack.append(tag)
            return

        if tag == "p":
            self._newline(2)
            return

        if tag in ("strong", "b"):
            self._emit("**")
            return
        if tag in ("em", "i"):
            self._emit("*")
            return

        if tag == "ul":
            self._list_stack.append(("ul", 0))
            self._newline()
            return
        if tag == "ol":
            self._list_stack.append(("ol", 0))
            self._newline()
            return
        if tag == "li":
            if self._list_stack:
                kind, counter = self._list_stack[-1]
                counter += 1
                self._list_stack[-1] = (kind, counter)
                indent = "  " * (len(self._list_stack) - 1)
                marker = f"{counter}. " if kind == "ol" else "- "
                self._newline()
                self._emit(indent + marker)
            return

    def handle_endtag(self, tag: str) -> None:
        if self._stack and self._stack[-1] == tag and tag in ("script", "style"):
            self._stack.pop()
            return

        if self._in_table:
            if tag in ("td", "th") and self._current_cell is not None:
                self._current_row.append("".join(self._current_cell))
                self._current_cell = None
                return
            if tag == "tr":
                self._table_rows.append((self._is_header_row, self._current_row))
                self._current_row = []
                self._is_header_row = False
                return
            if tag == "table":
                self._in_table -= 1
                if self._in_table == 0:
                    self._flush_table()
                return

        if tag in _HEADING_TAGS:
            if self._stack and self._stack[-1] == tag:
                self._stack.pop()
            self._newline(2)
            return

        if tag in ("strong", "b"):
            self._emit("**")
            return
        if tag in ("em", "i"):
            self._emit("*")
            return

        if tag == "p":
            self._newline()
            return

        if tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            self._newline()
            return
        if tag == "li":
            return

        if tag in _BLOCK_TAGS:
            self._newline()

    def handle_data(self, data: str) -> None:
        if self._stack and self._stack[-1] in ("script", "style"):
            return
        self._emit(data)

    # ---- public ----------------------------------------------------------

    def result(self) -> str:
        text = "".join(self._out)
        text = unescape(text)
        # Collapse 3+ newlines to 2, trim trailing spaces per line
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_markdown(html: str) -> str:
    """Convert an HTML fragment to clean markdown.

    Idempotent on already-plain text (no tags = passthrough modulo
    whitespace normalization).
    """
    if not html:
        return ""
    parser = _HtmlToMarkdown()
    parser.feed(html)
    parser.close()
    return parser.result()
