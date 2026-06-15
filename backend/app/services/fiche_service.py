"""Génération de fiches pratiques imprimables (PDF) à partir d'une réponse RAG.

Principe : un appel LLM dédié **met en forme** une réponse déjà produite par le
pipeline RAG. Il ne réécrit pas le fond et n'ajoute aucune règle, chiffre ou
source absent de la réponse source — la fidélité juridique prime. Les sources
ne passent jamais par le LLM : elles viennent directement des `RAGSource`
persistées sur le message, donc zéro risque d'hallucination de référence.

Le LLM remplit des champs structurés (JSON). Le gabarit HTML est fixe (charte
AORIA RH, alignée sur les emails) et converti en PDF par WeasyPrint. WeasyPrint
est importé paresseusement pour que le module reste testable sans les libs
système natives (pango/cairo).
"""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from openai import AsyncOpenAI

from app.core.config import settings
from app.services.cost_tracker import cost_tracker

logger = logging.getLogger(__name__)

# Famille gpt-5 : pas de `temperature` (rejetée), budget via max_completion_tokens.
FICHE_MODEL = "gpt-5-mini"

_llm = AsyncOpenAI(
    api_key=settings.openai_api_key,
    timeout=httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=30.0),
    max_retries=2,
)

# Couleurs de la charte (cf. app/services/email/templates.py).
_VIOLET = "#652BB0"


def _load_logo_svg() -> str:
    """Logo AORIA RH (version blanche) à inliner dans l'en-tête violet.

    Renvoie le SVG sans le prologue XML (inutile inline). Repli sur le texte
    « AORIA RH » si le fichier est introuvable, pour ne jamais casser le rendu.
    """
    try:
        raw = (Path(__file__).parent / "assets" / "logo-aoria-white.svg").read_text(
            encoding="utf-8"
        )
        return re.sub(r"<\?xml[^>]*\?>\s*", "", raw).strip()
    except OSError:
        logger.warning("Logo AORIA RH introuvable — repli sur le texte")
        return '<span class="logo-fallback">AORIA RH</span>'


_LOGO_HTML = _load_logo_svg()

FICHE_SYSTEM_PROMPT = """\
Tu mets en forme une réponse juridique RH existante en fiche pratique imprimable.
Tu ne fais QUE reformater le contenu fourni. Règles absolues :
- N'ajoute AUCUNE règle, chiffre, délai, seuil ou source absent de la réponse source.
- Ne complète pas, ne corrige pas, n'extrapole pas. Si une info manque, elle reste absente.
- Reprends les tableaux markdown de la source à l'identique dans "tableaux_markdown".
- N'invente jamais de référence juridique. Les sources sont gérées à part, hors de ta réponse.
- Style : phrases courtes, une idée par puce, ton concret et actionnable, vocabulaire métier clair.
- Si la réponse source porte sur un cas particulier non généralisable en fiche, mets eligible=false.

Réponds UNIQUEMENT en JSON valide selon ce schéma exact :
{
  "eligible": boolean,
  "titre": string,            // le sujet, pas la question. Max 70 caractères.
  "essentiel": string,        // 1 phrase : la réponse en une ligne
  "points_cles": [string],    // 3 à 6 puces, une idée chacune
  "tableaux_markdown": [string],  // tableaux repris tels quels (liste vide si aucun)
  "exceptions": [string],     // cas particuliers / pièges (liste vide si aucun)
  "etapes": [string]          // étapes si la réponse est procédurale (liste vide sinon)
}"""


@dataclass
class FicheContent:
    """Champs structurés produits par le LLM."""

    eligible: bool
    titre: str
    essentiel: str
    points_cles: list[str]
    tableaux_markdown: list[str]
    exceptions: list[str]
    etapes: list[str]


@dataclass
class FicheGeneration:
    """Résultat de l'appel LLM : contenu structuré, ou refus motivé."""

    eligible: bool
    content: FicheContent | None
    reason: str | None = None


# --- Parsing -------------------------------------------------------------


def parse_fiche_content(raw: str) -> FicheContent:
    """Parse la sortie JSON du LLM en `FicheContent`, tolérante aux écarts."""
    data = json.loads(raw)

    def _str_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(v).strip() for v in value if str(v).strip()]

    return FicheContent(
        eligible=bool(data.get("eligible", True)),
        titre=str(data.get("titre", "")).strip(),
        essentiel=str(data.get("essentiel", "")).strip(),
        points_cles=_str_list(data.get("points_cles")),
        tableaux_markdown=_str_list(data.get("tableaux_markdown")),
        exceptions=_str_list(data.get("exceptions")),
        etapes=_str_list(data.get("etapes")),
    )


# --- Rendu HTML ----------------------------------------------------------


def _inline(text: str) -> str:
    """Échappe le HTML puis restitue le gras markdown (**...**)."""
    escaped = html.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def _md_table_to_html(md: str) -> str:
    """Convertit un tableau markdown GFM en HTML. Renvoie '' si non-tableau."""
    lines = [ln.strip() for ln in md.splitlines() if ln.strip()]
    if len(lines) < 2 or "|" not in lines[0]:
        return ""

    def _cells(line: str) -> list[str]:
        parts = line.split("|")
        # Retire les bords vides dûs aux pipes de début/fin.
        if parts and parts[0].strip() == "":
            parts = parts[1:]
        if parts and parts[-1].strip() == "":
            parts = parts[:-1]
        return [c.strip() for c in parts]

    # La 2e ligne doit être le séparateur (---|---).
    if not set(lines[1].replace("|", "").replace(":", "").strip()) <= {"-", " "}:
        return ""

    header = _cells(lines[0])
    rows = [_cells(ln) for ln in lines[2:]]

    thead = "".join(f"<th>{_inline(c)}</th>" for c in header)
    body = "".join(
        "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>"
        for row in rows
        if any(row)
    )
    return f"<table><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table>"


def _format_source(src: dict) -> str:
    """Construit une ligne de source 'Label — réf (date)' depuis un RAGSource."""
    label = src.get("source_type_label") or src.get("document_name") or "Source"
    ref_parts: list[str] = []
    article_nums = src.get("article_nums")
    if article_nums:
        ref_parts.append(", ".join(str(a) for a in article_nums))
    if src.get("numero_pourvoi"):
        ref_parts.append(f"n° {src['numero_pourvoi']}")
    ref = " — ".join(ref_parts) if ref_parts else (src.get("document_name") or "")
    date = src.get("date_decision")
    line = html.escape(str(label))
    if ref:
        line += f" — {html.escape(str(ref))}"
    if date:
        line += f" ({html.escape(str(date))})"
    return line


def render_fiche_html(
    content: FicheContent,
    sources: list[dict],
    *,
    generated_at: datetime,
    org_name: str | None = None,
) -> str:
    """Assemble le gabarit HTML final (charte AORIA RH) prêt pour WeasyPrint."""
    date_str = generated_at.strftime("%d/%m/%Y")

    blocks: list[str] = []
    blocks.append(f'<h1 class="titre">{_inline(content.titre)}</h1>')
    if content.essentiel:
        blocks.append(f'<div class="essentiel">{_inline(content.essentiel)}</div>')

    if content.points_cles:
        puces = "".join(f"<li>{_inline(p)}</li>" for p in content.points_cles)
        blocks.append(f"<h2>Points clés</h2><ul>{puces}</ul>")

    for table_md in content.tableaux_markdown:
        table_html = _md_table_to_html(table_md)
        if table_html:
            blocks.append(table_html)

    if content.exceptions:
        items = "".join(f"<li>{_inline(e)}</li>" for e in content.exceptions)
        blocks.append(
            f'<div class="exceptions"><strong>À surveiller</strong><ul>{items}</ul></div>'
        )

    if content.etapes:
        items = "".join(f"<li>{_inline(s)}</li>" for s in content.etapes)
        blocks.append(f"<h2>Étapes</h2><ol>{items}</ol>")

    if sources:
        src_items = "".join(f"<li>{_format_source(s)}</li>" for s in sources)
        blocks.append(f'<h2>Sources</h2><ul class="sources">{src_items}</ul>')

    org_line = f" — {html.escape(org_name)}" if org_name else ""
    body = "\n".join(blocks)

    return f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="utf-8"><title>{_inline(content.titre)}</title>
<style>
  @page {{ size: A4; margin: 14mm 0; }}
  @page:first {{ margin-top: 0; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
         color:#3f3f46; margin:0; font-size:13px; line-height:1.5; }}
  .header {{ background:{_VIOLET}; padding:20px 32px; text-align:center; }}
  .header svg {{ height:34px; width:auto; }}
  .header .logo-fallback {{ color:#fff; font-size:20px; font-weight:700; letter-spacing:.5px; }}
  .header .tag {{ color:#ede9fe; font-size:11px; margin-top:6px; text-transform:uppercase;
                 letter-spacing:1px; }}
  .body {{ padding:24px 32px; }}
  h1.titre {{ color:{_VIOLET}; font-size:22px; font-weight:700; margin:0 0 12px; }}
  .essentiel {{ background:#f5f3ff; border-left:4px solid {_VIOLET}; padding:12px 16px;
               font-size:14px; font-weight:600; margin-bottom:20px; }}
  h2 {{ color:{_VIOLET}; font-size:13px; text-transform:uppercase; letter-spacing:.5px;
       margin:20px 0 8px; }}
  ul, ol {{ margin:0 0 16px; padding-left:20px; }}
  li {{ margin-bottom:6px; }}
  table {{ width:100%; border-collapse:collapse; margin:8px 0 16px; font-size:12.5px; }}
  th, td {{ border:1px solid #ede9fe; padding:6px 10px; text-align:left; }}
  th {{ background:#f5f3ff; color:{_VIOLET}; }}
  .exceptions {{ background:#fff7ed; border:1px solid #fed7aa; border-radius:8px;
                padding:10px 16px; margin-bottom:16px; }}
  .exceptions ul {{ margin:6px 0 0; }}
  .sources {{ font-size:12px; color:#5f6b6a; }}
  .footer {{ border-top:1px solid #ede9fe; margin:8px 32px 0; padding:14px 0; font-size:11px;
            color:#5f6b6a; }}
  .footer .validite {{ color:{_VIOLET}; font-weight:600; margin:0 0 4px; }}
</style></head>
<body>
  <div class="header">
    {_LOGO_HTML}
    <div class="tag">Fiche pratique</div>
  </div>
  <div class="body">
    {body}
  </div>
  <div class="footer">
    <p class="validite">À jour au {date_str}. Vérifiez l'actualité de ces règles avant application.</p>
    <p>Fiche générée par AORIA RH à partir de votre question{org_line}. &copy; {generated_at.year} AORIA RH.</p>
  </div>
</body></html>"""


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "fiche-pratique"


def html_to_pdf(html_str: str) -> bytes:
    """Convertit le HTML en PDF via WeasyPrint (import paresseux)."""
    from weasyprint import HTML  # import différé : libs natives requises

    return HTML(string=html_str).write_pdf()


# --- Orchestration -------------------------------------------------------


async def generate_fiche_content(
    *,
    question: str,
    answer_markdown: str,
    organisation_id: str | None = None,
    user_id: str | None = None,
) -> FicheGeneration:
    """Appelle le LLM pour produire le contenu structuré de la fiche.

    Ne rend pas le PDF (cf. `render_fiche_pdf`) : on stocke ce contenu et on
    régénère le PDF à la demande avec la date du jour. Renvoie `eligible=False`
    avec un motif quand la réponse ne se prête pas à une fiche générale.
    """
    user_content = (
        f"Question posée : {question}\n\n"
        f"Réponse à mettre en forme :\n{answer_markdown}"
    )

    response = await _llm.chat.completions.create(
        model=FICHE_MODEL,
        messages=[
            {"role": "system", "content": FICHE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=2000,
        reasoning_effort="minimal",
    )

    if response.usage:
        await cost_tracker.log(
            provider="openai",
            model=FICHE_MODEL,
            operation_type="fiche",
            tokens_input=response.usage.prompt_tokens,
            tokens_output=response.usage.completion_tokens,
            organisation_id=organisation_id,
            user_id=user_id,
            context_type="fiche",
            context_id=None,
        )

    raw = response.choices[0].message.content or "{}"
    content = parse_fiche_content(raw)

    if not content.eligible or not content.titre or not content.points_cles:
        return FicheGeneration(
            eligible=False,
            content=None,
            reason=(
                "Cette réponse porte sur un cas précis et ne se prête pas à une "
                "fiche pratique générale."
            ),
        )

    return FicheGeneration(eligible=True, content=content)


def render_fiche_pdf(
    content: FicheContent,
    sources: list[dict],
    *,
    generated_at: datetime,
    org_name: str | None = None,
) -> bytes:
    """Rend le PDF de la fiche à partir du contenu structuré + sources."""
    html_str = render_fiche_html(
        content, sources, generated_at=generated_at, org_name=org_name
    )
    return html_to_pdf(html_str)


def fiche_filename(content: FicheContent) -> str:
    """Nom de fichier PDF dérivé du titre de la fiche."""
    return f"fiche-{_slugify(content.titre)}.pdf"
