"""Tests for the ArticleChunker — section isolation, metadata, ghost filtering."""

from app.rag.article_chunker import ArticleChunker, ChunkWithMeta


# Simplified CCNT66-like markdown (articles 32, 33, 34, 35 across 3 sections)
CCNT66_SAMPLE = """\
# Convention collective — CCNT66 (IDCC 0413)

## Titre IV : Exécution du contrat de travail > Promotion sociale et perfectionnement

### Article 32

Le personnel reconnaît l'obligation morale d'un perfectionnement professionnel permanent.
A cet effet, les signataires de la présente convention mettront à la disposition des
salariés les moyens propres à faciliter ce perfectionnement.

## Titre IV : Exécution du contrat de travail > Conditions générales de discipline

### Article 33

Les mesures disciplinaires applicables aux personnels des établissements ou services
s'exercent sous les formes suivantes :
- l'observation ;
- l'avertissement ;
- la mise à pied avec ou sans salaire pour un maximum de 3 jours ;
- le licenciement.
Toute sanction encourue par un salarié et non suivie d'une autre dans un délai maximal
de 2 ans sera annulée et il n'en sera conservé aucune trace.

### Article 34

Commission régionale paritaire de discipline. En cas de litige disciplinaire, une
commission régionale paritaire de discipline peut être saisie.

## Titre IV : Exécution du contrat de travail > Hygiène et sécurité

### Article 35

Dans le cadre de la législation sur la médecine du travail, des consultations médicales
seront assurées gratuitement et organisées périodiquement à l'intention du personnel.
"""


def test_sections_never_mixed():
    """Articles from different sections must NEVER be in the same chunk."""
    chunker = ArticleChunker()
    chunks = chunker.chunk_with_meta(CCNT66_SAMPLE)

    for c in chunks:
        # Each chunk should reference exactly one section_path
        assert c.section_path, f"Chunk missing section_path: {c.text[:80]}"
        # The text should NOT contain ## headers from multiple sections
        import re
        sections_in_text = re.findall(r"^## (.+)$", c.text, re.MULTILINE)
        assert len(set(sections_in_text)) <= 1, (
            f"Chunk mixes sections: {sections_in_text}"
        )


def test_article_33_isolated_from_32():
    """Article 33 (discipline) must NOT be in same chunk as article 32 (perfectionnement)."""
    chunker = ArticleChunker()
    chunks = chunker.chunk_with_meta(CCNT66_SAMPLE)

    for c in chunks:
        nums = c.article_nums
        assert not ("32" in nums and "33" in nums), (
            f"Articles 32 and 33 are in the same chunk! section={c.section_path}, nums={nums}"
        )


def test_article_34_present():
    """Article 34 must exist in the output (not lost during chunking)."""
    chunker = ArticleChunker()
    chunks = chunker.chunk_with_meta(CCNT66_SAMPLE)

    all_nums = []
    for c in chunks:
        all_nums.extend(c.article_nums)

    assert "34" in all_nums, f"Article 34 missing! Found: {all_nums}"


def test_articles_33_34_same_section():
    """Articles 33 and 34 are in the same section and can share a chunk."""
    chunker = ArticleChunker()
    chunks = chunker.chunk_with_meta(CCNT66_SAMPLE)

    chunk_with_33 = [c for c in chunks if "33" in c.article_nums]
    assert len(chunk_with_33) >= 1
    # Both should be in "Conditions générales de discipline" section
    for c in chunk_with_33:
        assert "discipline" in c.section_path.lower()


def test_metadata_populated():
    """Every chunk must have article_nums and section_path."""
    chunker = ArticleChunker()
    chunks = chunker.chunk_with_meta(CCNT66_SAMPLE)

    assert len(chunks) >= 3, f"Expected at least 3 chunks, got {len(chunks)}"
    for c in chunks:
        assert c.article_nums, f"Missing article_nums in chunk: {c.text[:80]}"
        assert c.section_path, f"Missing section_path in chunk: {c.text[:80]}"


def test_no_ghost_chunks():
    """Chunks that are just a title (< 15 tokens) must be filtered out."""
    # Markdown with a title-only article followed by a real one
    md = """\
## Section A

### Article 1

### Article 2

Contenu réel de l'article 2 avec suffisamment de texte pour dépasser le seuil minimum.
"""
    chunker = ArticleChunker()
    chunks = chunker.chunk_with_meta(md)

    for c in chunks:
        # No chunk should be just a heading
        assert len(c.text) > 30, f"Ghost chunk detected: {repr(c.text)}"


def test_orphan_title_merged():
    """An article with only a heading should be merged into the next article."""
    md = """\
## Section A

### Article 10

### Article 11

Texte de l'article 11 qui est le vrai contenu à indexer dans le vector store.
"""
    chunker = ArticleChunker()
    chunks = chunker.chunk_with_meta(md)

    # Article 10's heading should be merged with article 11
    all_text = " ".join(c.text for c in chunks)
    assert "Article 10" in all_text
    assert "Article 11" in all_text
    # Should be in the same chunk (merged)
    for c in chunks:
        if "Article 11" in c.text:
            assert "Article 10" in c.text, "Article 10 heading should be merged into Article 11 chunk"


def test_backward_compatible_chunk_method():
    """The plain chunk() method should return list[str] for backward compatibility."""
    chunker = ArticleChunker()
    chunks = chunker.chunk(CCNT66_SAMPLE)

    assert isinstance(chunks, list)
    assert all(isinstance(c, str) for c in chunks)
    assert len(chunks) >= 3


def test_large_article_split_preserves_metadata():
    """An article exceeding chunk_size should be split but keep metadata."""
    # Create a very long article
    long_content = "Paragraphe important. " * 200  # ~400 tokens
    md = f"""\
## Section longue

### Article 99

{long_content}
"""
    chunker = ArticleChunker(chunk_size=100)  # Force small chunks
    chunks = chunker.chunk_with_meta(md)

    assert len(chunks) >= 2, f"Expected article to be split, got {len(chunks)} chunks"
    for c in chunks:
        assert c.article_nums == ["99"], f"Split chunk lost article_num: {c.article_nums}"
        assert c.section_path == "Section longue"


def test_split_continuation_has_context():
    """Continuation chunks of a split article must have section + article context."""
    # Create an article that will be split into at least 2 chunks
    para1 = "Premier paragraphe avec du contenu substantiel. " * 30
    para2 = "Deuxième paragraphe tout aussi important pour le RAG. " * 30
    md = f"""\
## Titre IV : Discipline

### Article 33

{para1}

{para2}
"""
    chunker = ArticleChunker(chunk_size=100)  # Force small chunks
    chunks = chunker.chunk_with_meta(md)

    assert len(chunks) >= 2, f"Expected split, got {len(chunks)} chunks"
    # First chunk should have the original heading
    assert "### Article 33" in chunks[0].text
    # Continuation chunks should have context prefix, not start mid-sentence
    for c in chunks[1:]:
        assert "Article 33" in c.text, (
            f"Continuation chunk starts without article context: {c.text[:100]}"
        )
        assert "Discipline" in c.text or "Section" in c.text or "##" in c.text, (
            f"Continuation chunk has no section context: {c.text[:100]}"
        )
