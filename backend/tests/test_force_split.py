"""Tests for boundary-aware force splitting (no mid-word cuts)."""
from __future__ import annotations

import re

import tiktoken

from app.rag.chunker import force_split_on_boundary

_ENC = tiktoken.get_encoding("cl100k_base")
# A trackable word: "mot0000ee".."mot1999ee", optionally followed by a period.
# The trailing letters make it a realistic sentence end (the boundary regex
# intentionally ignores digit/abbreviation periods like "24-13.599" or "R.").
_WORD = re.compile(r"^mot\d{4}ee\.?$")


def _build_text(n_words: int = 2000, per_sentence: int = 10) -> str:
    sentences = []
    for k in range(0, n_words, per_sentence):
        sentences.append(" ".join(f"mot{j:04d}ee" for j in range(k, k + per_sentence)))
    return ". ".join(sentences) + "."


class TestForceSplitOnBoundary:
    def test_short_text_returned_as_is(self):
        out = force_split_on_boundary("court texte.", _ENC, 100, 20)
        assert out == ["court texte."]

    def test_never_cuts_mid_word(self):
        text = _build_text()
        chunks = force_split_on_boundary(text, _ENC, 200, 20)
        assert len(chunks) > 1
        for ch in chunks:
            assert ch == ch.strip()
            tokens = ch.split()
            # Every whitespace-delimited token is a complete word, never a
            # fragment like "mot00" or "23" left by a mid-word cut.
            for tok in (tokens[0], tokens[-1]):
                assert _WORD.match(tok), f"fragment at boundary: {tok!r}"

    def test_prefers_sentence_ends(self):
        text = _build_text()
        chunks = force_split_on_boundary(text, _ENC, 200, 20)
        # With sentences every ~10 words, the tail zone always contains one, so
        # non-final chunks should end on a sentence boundary.
        assert any(ch.endswith(".") for ch in chunks[:-1])

    def test_no_word_is_lost(self):
        text = _build_text()
        chunks = force_split_on_boundary(text, _ENC, 200, 20)
        joined = " ".join(chunks)
        for j in range(2000):
            assert f"mot{j:04d}" in joined, f"missing mot{j:04d}"

    def test_consecutive_chunks_overlap(self):
        text = _build_text()
        chunks = force_split_on_boundary(text, _ENC, 200, 20)
        for i in range(len(chunks) - 1):
            first_word_next = chunks[i + 1].split()[0].rstrip(".")
            assert first_word_next in chunks[i], (
                f"no overlap between chunk {i} and {i + 1}"
            )

    def test_unbreakable_blob_terminates(self):
        # A long run with no whitespace at all: no word boundary to respect, but
        # it must still split, cover the text, and not loop forever.
        blob = "x" * 6000
        chunks = force_split_on_boundary(blob, _ENC, 200, 20)
        assert len(chunks) > 1
        assert sum(ch.count("x") for ch in chunks) >= 6000
