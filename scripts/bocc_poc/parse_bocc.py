"""POC v2 — Parse un BOCC PDF et extrait les avenants par IDCC.

Structure identifiée (constante entre numéros) :
- Page 1     : Couverture (numéro + date) → ignorer
- Page 2     : Sommaire ministères → ignorer
- Pages 3-4  : Sommaire détaillé (IDCC | Nom : titre ... page)
- Pages 5+   : Avenants séparés par en-tête "Brochure n° XXXX | CCN"
- Fin        : Section "Accord(s) professionnel(s)" (optionnel)
- Footer     : "BOCC XXXX-XX TRA" + numéro de page → nettoyer

Usage:
    python scripts/bocc_poc/parse_bocc.py docs/boc_20250052_0001_p000.pdf

Résultat:
    scripts/bocc_poc/output/{idcc}/bocc_{date}_{nor}.txt
    scripts/bocc_poc/output/sommaire.json
"""

import json
import os
import re
import sys

import pymupdf


# ─── En-tête qui sépare chaque avenant ───
# Format 1: Brochure n° XXXX | Convention collective nationale
HEADER_PATTERN_1 = re.compile(
    r"Brochure\s+n°\s*(\d+)\s*\|\s*Convention collective nationale\n"
    r"IDCC\s*:\s*(\d+)\s*\|\s*([^\n]+)\n"
    r"([\s\S]*?)\n"
    r"NOR\s*:\s*(ASET\w+)",
    re.MULTILINE,
)

# Format 2: Convention collective nationale (sans Brochure)
HEADER_PATTERN_2 = re.compile(
    r"Convention collective nationale\n"
    r"IDCC\s*:\s*(\d+)\s*\|\s*([^\n]+)\n"
    r"([\s\S]*?)\n"
    r"NOR\s*:\s*(ASET\w+)",
    re.MULTILINE,
)

# ─── Footer à supprimer ───
FOOTER_PATTERN = re.compile(r"^BOCC\s+\d{4}-\d+\s+TRA\s*$", re.MULTILINE)
PAGE_NUM_PATTERN = re.compile(r"^\d{1,3}\s*$", re.MULTILINE)


def extract_full_text(pdf_path: str) -> tuple[str, dict]:
    """Extract full text and metadata from BOCC PDF."""
    doc = pymupdf.open(pdf_path)

    # Metadata from page 1
    p1 = doc[0].get_text("text")
    numero_match = re.search(r"(\d{4}-\d+)", p1)
    date_match = re.search(r"(\d+\s+\w+\s+\d{4})", p1)

    meta = {
        "numero": numero_match.group(1) if numero_match else "unknown",
        "date": date_match.group(0) if date_match else "unknown",
        "pages": len(doc),
    }

    # Full text from page 5+ (skip cover + sommaire)
    pages_text = []
    for i in range(4, len(doc)):
        pages_text.append(doc[i].get_text("text"))

    doc.close()
    return "\n".join(pages_text), meta


def split_avenants(full_text: str) -> list[dict]:
    """Split full text into individual avenants using header patterns."""

    # Collect all headers from both patterns with their positions
    headers: list[tuple[int, int, dict]] = []  # (start, end, metadata)

    for match in HEADER_PATTERN_1.finditer(full_text):
        headers.append((match.start(), match.end(), {
            "brochure": match.group(1),
            "idcc": match.group(2).zfill(4),
            "ccn_name": match.group(3).strip(),
            "titre_raw": match.group(4).strip(),
            "nor": match.group(5),
            "full_header": match.group(0),
        }))

    for match in HEADER_PATTERN_2.finditer(full_text):
        # Avoid duplicates — skip if position overlaps with a Pattern 1 match
        pos = match.start()
        if any(abs(pos - h[0]) < 50 for h in headers):
            continue
        headers.append((match.start(), match.end(), {
            "brochure": "",
            "idcc": match.group(1).zfill(4),
            "ccn_name": match.group(2).strip(),
            "titre_raw": match.group(3).strip(),
            "nor": match.group(4),
            "full_header": match.group(0),
        }))

    # Sort by position
    headers.sort(key=lambda h: h[0])

    if not headers:
        return []

    avenants = []
    for i, (start, end, meta) in enumerate(headers):
        # Content = from after this header to the next header (or end)
        content_start = end
        content_end = headers[i + 1][0] if i + 1 < len(headers) else len(full_text)

        content = full_text[content_start:content_end]

        # Cut off "Accord(s) professionnel(s)" section at end
        accords_pro = re.search(r"Accord\(s\)\s+professionnel\(s\)", content)
        if accords_pro:
            content = content[:accords_pro.start()]

        # Extract clean title from header
        titre_match = re.search(
            r"((?:Accord|Avenant|Protocole|Annexe)[^\n]*(?:\n[^\n]*?)?)"
            r"(?=\s*NOR\s*:|$)",
            meta["full_header"],
            re.IGNORECASE,
        )
        if titre_match:
            titre = re.sub(r"\s+", " ", titre_match.group(1)).strip()
        else:
            titre = re.sub(r"\s+", " ", meta["titre_raw"]).strip()

        # Capitalize first letter if needed
        if titre and titre[0].islower():
            titre = titre[0].upper() + titre[1:]

        # Clean titre: remove CCN name fragments that leaked in
        # Pattern: "(date)" or "(Salaisons...)" before the real title
        titre = re.sub(r"^\([^)]+\)\s*", "", titre)
        # Remove all-caps CCN name fragments before the title
        titre = re.sub(r"^[A-ZÉÈÊËÀÂÔÎÏÙÛÜÇ\s,.'()-]+(?=Accord|Avenant|Protocole|Annexe)", "", titre).strip()

        content = clean_content(content)

        avenants.append({
            "idcc": meta["idcc"],
            "brochure": meta["brochure"],
            "ccn_name": meta["ccn_name"],
            "titre": titre,
            "nor": meta["nor"],
            "content": content,
            "content_length": len(content),
        })

    return avenants


def clean_content(text: str) -> str:
    """Clean avenant content: remove footers, page numbers, normalize."""
    # Remove BOCC footer lines
    text = FOOTER_PATTERN.sub("", text)

    # Remove standalone page numbers
    text = PAGE_NUM_PATTERN.sub("", text)

    # Remove the second "IDCC : XXXX" line that appears after NOR
    text = re.sub(r"^IDCC\s*:\s*\d+\s*$", "", text, count=1, flags=re.MULTILINE)

    # Remove repeated page headers
    text = re.sub(r"^MINISTÈRE\s+DU\s+TRAVAIL[^\n]*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^MINISTÈRE\s+DE\s+L.AGRICULTURE[^\n]*$", "", text, flags=re.MULTILINE)

    # Fix soft hyphens (césure) — rejoin words split across lines
    text = re.sub(r"­\s*\n\s*", "", text)
    # Also fix regular hyphens at end of line that are césure
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # Format article headings as markdown
    text = re.sub(r"^(Article\s+\d+[\w]*(?:\s*\|[^\n]*)?)", r"### \1", text, flags=re.MULTILINE)
    text = re.sub(r"^(Préambule)\s*$", r"### Préambule", text, flags=re.MULTILINE)

    # Normalize multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Strip leading/trailing whitespace
    text = text.strip()

    return text


def format_as_markdown(avenant: dict, bocc_numero: str, bocc_date: str) -> str:
    """Format avenant as clean markdown document."""
    lines = [
        f"# {avenant['titre']}",
        "",
        f"**Convention collective** : {avenant['ccn_name']} (IDCC {avenant['idcc']})",
        f"**Brochure** : n° {avenant['brochure']}",
        f"**NOR** : {avenant['nor']}",
        f"**Source** : BOCC n° {bocc_numero} du {bocc_date}",
        "",
        "---",
        "",
        avenant["content"],
    ]
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python parse_bocc.py <chemin_pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        print(f"Fichier introuvable: {pdf_path}")
        sys.exit(1)

    output_dir = os.path.join(os.path.dirname(__file__), "output")
    # Clean previous output
    import shutil
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir)

    print(f"📄 Parsing {pdf_path}...")

    # 1. Extract text
    full_text, meta = extract_full_text(pdf_path)
    print(f"   BOCC n° {meta['numero']} du {meta['date']} — {meta['pages']} pages")

    # 2. Split into avenants
    avenants = split_avenants(full_text)
    print(f"   {len(avenants)} avenants extraits")

    # 3. Write output
    for av in avenants:
        idcc_dir = os.path.join(output_dir, av["idcc"])
        os.makedirs(idcc_dir, exist_ok=True)

        filename = f"bocc_{meta['numero']}_{av['nor']}.md"
        filepath = os.path.join(idcc_dir, filename)

        md = format_as_markdown(av, meta["numero"], meta["date"])
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md)

        print(f"   ✅ IDCC {av['idcc']} | {av['titre'][:70]}")
        print(f"      → {os.path.basename(filepath)} ({av['content_length']:,} chars)")

    # 4. Write index
    index_path = os.path.join(output_dir, "sommaire.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump({
            "bocc_numero": meta["numero"],
            "bocc_date": meta["date"],
            "pages": meta["pages"],
            "avenants_count": len(avenants),
            "avenants": [
                {
                    "idcc": av["idcc"],
                    "ccn_name": av["ccn_name"],
                    "brochure": av["brochure"],
                    "titre": av["titre"],
                    "nor": av["nor"],
                    "content_length": av["content_length"],
                }
                for av in avenants
            ],
        }, f, ensure_ascii=False, indent=2)

    # 5. Stats
    idcc_set = {av["idcc"] for av in avenants}
    total_chars = sum(av["content_length"] for av in avenants)
    print(f"\n📊 Résumé :")
    print(f"   {len(avenants)} avenants pour {len(idcc_set)} CCN distinctes")
    print(f"   {total_chars:,} caractères au total")
    print(f"   📋 Index : {index_path}")


if __name__ == "__main__":
    main()
