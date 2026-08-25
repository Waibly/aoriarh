"""Génération de fiches pratiques imprimables (PDF) à partir d'une réponse RAG.

Le LLM produit directement le fragment HTML du corps de la fiche. Sa structure
reste donc libre et s'adapte à la réponse : une procédure conserve toutes ses
étapes, un barème peut devenir un tableau et un avertissement n'apparaît que
s'il apporte quelque chose. L'application maîtrise uniquement le design system,
l'en-tête, le pied de page et la pagination.

Le fragment généré est stocké et rendu tel quel. Les contrôles de format ne le
réécrivent jamais ; ils peuvent seulement ajouter un avertissement visible. Les
anciennes fiches JSON restent prises en charge pendant la transition.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
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


def _load_fonts_css() -> str:
    """Embarque les polices du site (Inter + Sora) en @font-face pour WeasyPrint.

    Les .woff2 (variables, axe de graisse 100→900) sont copiés depuis le site et
    inlinés en base64 : le PDF reste fidèle à la charte sans dépendre des polices
    système ni du chemin d'exécution. Repli silencieux sur la pile système si un
    fichier manque, pour ne jamais casser le rendu.
    """
    fonts_dir = Path(__file__).parent / "assets" / "fonts"
    faces = [
        ("Inter Variable", "inter-latin-wght-normal.woff2"),
        ("Inter Variable", "inter-latin-ext-wght-normal.woff2"),
        ("Sora Variable", "sora-latin-wght-normal.woff2"),
        ("Sora Variable", "sora-latin-ext-wght-normal.woff2"),
    ]
    blocks = []
    for family, filename in faces:
        try:
            raw = (fonts_dir / filename).read_bytes()
        except OSError:
            logger.warning("Police %s introuvable — repli sur la pile système", filename)
            continue
        b64 = base64.b64encode(raw).decode("ascii")
        blocks.append(
            f"@font-face {{ font-family:'{family}'; font-weight:100 900; "
            f"font-style:normal; font-display:swap; "
            f"src:url(data:font/woff2;base64,{b64}) format('woff2'); }}"
        )
    return "\n  ".join(blocks)


_FONTS_CSS = _load_fonts_css()


def _icon(paths: str) -> str:
    """Petite icône SVG (style lucide) qui hérite de la couleur du texte."""
    return (
        '<svg class="section-icon" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round">{paths}</svg>'
    )


_ICON_CLES = _icon('<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>')
_ICON_WARN = _icon(
    '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>'
    '<path d="M12 9v4"/><path d="M12 17h.01"/>'
)
_ICON_STEPS = _icon(
    '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/>'
    '<path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>'
)
_ICON_SOURCES = _icon(
    '<path d="M12 7v14"/>'
    '<path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 '
    '4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 '
    '3 3 0 0 0-3-3z"/>'
)

FICHE_SYSTEM_PROMPT = """\
Tu transformes une réponse juridique RH existante en corps de fiche pratique HTML.
Tu ne fais QUE mettre en forme le contenu fourni. La fidélité est prioritaire.

Règles absolues de contenu :
- N'ajoute AUCUNE règle, interprétation, chiffre, délai, seuil, exception ou source absent de la
  réponse fournie.
- Ne complète pas, ne corrige pas et n'extrapole pas. Si une information manque, elle reste absente.
- Ne supprime aucune information nécessaire. Une procédure qui comporte 10 étapes utiles conserve
  ses 10 étapes. Il n'existe aucune limite arbitraire de longueur, de sections ou de pages.
- Conserve chaque référence juridique visible dans la réponse, mot pour mot et au plus près de
  l'affirmation qu'elle fonde. N'invente jamais de référence.
- Rédige un document autonome : ne parle jamais de « la réponse », « la source » ou « la question ».
- Utilise des phrases courtes, concrètes et actionnables, sans répétition entre les sections.
- N'ajoute un encadré de vigilance que s'il existe un vrai risque, une exception ou une condition.

Règles absolues de sortie :
- Renvoie UNIQUEMENT le fragment HTML final, sans JSON, Markdown, commentaire ni balises ```.
- Le fragment commence par <article class="fiche-content"> et finit par </article>.
- Il contient exactement un <h1> avec un titre autonome et précis.
- N'utilise aucun attribut style, id, src, href ou événement, aucune balise script, style, link,
  img, iframe ou objet externe. Le CSS est entièrement géré par l'application.

Catalogue de composants autorisés — choisis uniquement ceux utiles au contenu :
- Introduction : <section class="intro"><p>...</p></section>
- Information essentielle : <aside class="essential"><p>...</p></aside>
- Section libre : <section><h2>...</h2>...</section>
- Points clés : <section class="key-points"><h2>...</h2><ul>...</ul></section>
- Procédure : <section class="procedure"><h2>...</h2><ol>...</ol></section>
- Vigilance : <aside class="warning"><h2>À surveiller</h2>...</aside>
- Information complémentaire : <aside class="info"><h2>...</h2>...</aside>
- Tableau : <div class="table-wrapper"><table class="data-table">...</table></div>
- Définitions : <dl class="definitions"><dt>...</dt><dd>...</dd></dl>
- Références, uniquement si elles existent :
  <section class="legal-references"><h2>Références juridiques</h2><ul>...</ul></section>

Balises autorisées : article, section, aside, div, h1, h2, h3, p, ul, ol, li, dl, dt, dd,
table, thead, tbody, tr, th, td, strong, em, span, br et blockquote.
"""


@dataclass
class FicheContent:
    """Corps HTML brut produit par le LLM, ou contenu JSON historique."""

    eligible: bool = True
    titre: str = ""
    body_html: str = ""
    warnings: list[str] = field(default_factory=list)
    # Champs historiques : nécessaires pour relire les fiches déjà persistées.
    essentiel: str = ""
    points_cles: list[str] = field(default_factory=list)
    tableaux_markdown: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    etapes: list[str] = field(default_factory=list)


@dataclass
class FicheGeneration:
    """Résultat de l'appel LLM : fragment HTML brut ou erreur technique."""

    eligible: bool
    content: FicheContent | None
    reason: str | None = None


# --- Lecture et contrôle non bloquant du fragment ------------------------


_ALLOWED_BODY_TAGS = {
    "article",
    "section",
    "aside",
    "div",
    "h1",
    "h2",
    "h3",
    "p",
    "ul",
    "ol",
    "li",
    "dl",
    "dt",
    "dd",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "strong",
    "em",
    "span",
    "br",
    "blockquote",
}
_ALLOWED_BODY_ATTRIBUTES = {"class", "colspan", "rowspan", "scope"}


class _FicheFragmentInspector(HTMLParser):
    """Inspecte le HTML sans jamais le modifier."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.h1_count = 0
        self._in_first_h1 = False
        self._title_parts: list[str] = []
        self.issues: list[str] = []

    @property
    def title(self) -> str:
        return " ".join("".join(self._title_parts).split())

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.casefold()
        self.tags.append(tag)
        if tag not in _ALLOWED_BODY_TAGS:
            self.issues.append(f"balise <{tag}> non prévue")
        for name, _value in attrs:
            if name.casefold() not in _ALLOWED_BODY_ATTRIBUTES:
                self.issues.append(f"attribut {name} non prévu")
        if tag == "h1":
            self.h1_count += 1
            self._in_first_h1 = self.h1_count == 1

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "h1":
            self._in_first_h1 = False

    def handle_data(self, data: str) -> None:
        if self._in_first_h1:
            self._title_parts.append(data)


def inspect_fiche_fragment(raw: str) -> tuple[str, list[str]]:
    """Extrait le titre et retourne des avertissements purement informatifs."""
    inspector = _FicheFragmentInspector()
    try:
        inspector.feed(raw)
        inspector.close()
    except Exception as exc:  # HTMLParser est tolérant, repli défensif.
        return "", [f"HTML difficile à analyser ({type(exc).__name__})"]

    issues = list(dict.fromkeys(inspector.issues))
    if inspector.h1_count != 1:
        issues.append(f"{inspector.h1_count} titre h1 détecté au lieu d'un")
    if not inspector.tags or inspector.tags[0] != "article":
        issues.append("le fragment ne commence pas par l'article attendu")
    return inspector.title, issues


def parse_fiche_content(raw: str) -> FicheContent:
    """Conserve le HTML brut ; accepte aussi l'ancien JSON pour compatibilité."""
    if not raw.strip():
        raise ValueError("La génération de la fiche est vide")

    if not raw.lstrip().startswith("{"):
        title, warnings = inspect_fiche_fragment(raw)
        return FicheContent(
            titre=title or "Fiche pratique",
            body_html=raw,
            warnings=warnings,
        )

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


def _reference_key(value: object) -> str:
    """Normalise une référence pour la comparaison et la déduplication."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _article_is_cited(article: str, answer_markdown: str) -> bool:
    """Vérifie qu'un numéro d'article de la source figure dans la réponse."""
    article_key = _reference_key(article)
    if not article_key:
        return False

    # Les articles de code comportent une lettre : la normalisation permet de
    # rapprocher L. 2421-3, L2421-3 et L 2421 3 sans faux positif L. 2421-30.
    compact_answer = _reference_key(answer_markdown)
    if article_key[0].isalpha():
        return re.search(rf"{re.escape(article_key)}(?!\d)", compact_answer) is not None

    # Pour un article conventionnel purement numérique, exige le mot article/art.
    # afin qu'un délai ou un montant identique ne soit pas pris pour une citation.
    flexible = r"[.\s\-]*".join(re.escape(char) for char in str(article).strip())
    return (
        re.search(
            rf"\b(?:art(?:icle)?\.?\s*)(?:n[o°]\s*)?{flexible}(?!\d)",
            answer_markdown,
            flags=re.IGNORECASE,
        )
        is not None
    )


def select_fiche_references(answer_markdown: str, sources: list[dict]) -> list[dict]:
    """Conserve uniquement les fondements explicitement cités dans la réponse.

    La sélection est déterministe et ne modifie jamais le texte produit par le
    LLM. Pour chaque source, seuls les articles ou le numéro de décision visibles
    dans la réponse sont conservés. Un document sans identifiant stable n'est
    retenu que si son nom exact ou son IDCC apparaît dans la réponse.
    """
    answer_key = _reference_key(answer_markdown)
    selected: list[dict] = []
    seen: set[tuple] = set()

    for source in sources:
        if not isinstance(source, dict):
            continue

        source_copy = dict(source)
        pourvoi = str(source.get("numero_pourvoi") or "").strip()
        article_nums = [
            str(article).strip()
            for article in (source.get("article_nums") or [])
            if str(article).strip()
        ]

        # Une décision se cite par son numéro, pas par les articles reproduits
        # dans son texte ou ses visas.
        if pourvoi:
            if _reference_key(pourvoi) not in answer_key:
                continue
            source_copy["article_nums"] = None
        elif article_nums:
            cited_articles = [
                article
                for article in article_nums
                if _article_is_cited(article, answer_markdown)
            ]
            if not cited_articles:
                continue
            source_copy["article_nums"] = cited_articles
        else:
            document_name = str(source.get("document_name") or "").strip()
            idcc = str(source.get("idcc") or "").strip()
            name_cited = bool(document_name) and _reference_key(document_name) in answer_key
            idcc_cited = bool(idcc) and _reference_key(idcc) in answer_key
            if not name_cited and not idcc_cited:
                continue

        key = (
            source_copy.get("source_type"),
            source_copy.get("document_name"),
            tuple(source_copy.get("article_nums") or []),
            source_copy.get("numero_pourvoi"),
        )
        if key in seen:
            continue
        seen.add(key)
        selected.append(source_copy)

    return selected


def _format_source(src: dict) -> str:
    """Construit un fondement juridique, sans métadonnée documentaire."""
    label = str(src.get("source_type_label") or src.get("document_name") or "").strip()
    articles = [str(article).strip() for article in (src.get("article_nums") or [])]
    pourvoi = str(src.get("numero_pourvoi") or "").strip()

    if pourvoi:
        label = re.sub(r"^Arrêt\s+", "", label, flags=re.IGNORECASE)
        parts = [label] if label else []
        if src.get("date_decision"):
            try:
                date = datetime.fromisoformat(str(src["date_decision"])).strftime("%d/%m/%Y")
            except ValueError:
                date = str(src["date_decision"])
            parts.append(date)
        parts.append(f"n° {pourvoi}")
        return html.escape(", ".join(parts))

    if articles:
        article_label = "art." if len(articles) == 1 else "art."
        citation = f"{article_label} {', '.join(articles)}"
        return html.escape(f"{label}, {citation}" if label else citation)

    # Pour une CCN, un accord ou un document interne sans article stable, le
    # titre exact du document constitue lui-même le fondement utile.
    return html.escape(str(src.get("document_name") or label).strip())


def _format_reference_lines(sources: list[dict]) -> list[str]:
    """Formate et déduplique les fondements affichables."""
    lines: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        line = _format_source(source)
        key = _reference_key(line)
        if not line or not key or key in seen:
            continue
        seen.add(key)
        lines.append(line)
    return lines


def _render_legacy_body(content: FicheContent, sources: list[dict]) -> str:
    """Rend le précédent format JSON sans modifier les données historiques."""
    blocks: list[str] = []
    blocks.append(f'<h1 class="titre">{_inline(content.titre)}</h1>')
    if content.essentiel:
        blocks.append(f'<div class="essentiel">{_inline(content.essentiel)}</div>')

    if content.points_cles:
        puces = "".join(f"<li>{_inline(p)}</li>" for p in content.points_cles)
        blocks.append(f"<h2>{_ICON_CLES}Points clés</h2><ul>{puces}</ul>")

    for table_md in content.tableaux_markdown:
        table_html = _md_table_to_html(table_md)
        if table_html:
            blocks.append(table_html)

    if content.exceptions:
        items = "".join(f"<li>{_inline(e)}</li>" for e in content.exceptions)
        blocks.append(
            f'<div class="exceptions"><strong>{_ICON_WARN}À surveiller</strong>'
            f"<ul>{items}</ul></div>"
        )

    if content.etapes:
        items = "".join(f"<li>{_inline(s)}</li>" for s in content.etapes)
        blocks.append(f"<h2>{_ICON_STEPS}Étapes</h2><ol>{items}</ol>")

    reference_lines = _format_reference_lines(sources)
    if reference_lines:
        src_items = "".join(f"<li>{line}</li>" for line in reference_lines)
        blocks.append(
            f'<h2>{_ICON_SOURCES}Références juridiques</h2>'
            f'<ul class="sources">{src_items}</ul>'
        )

    return '<article class="fiche-content legacy-content">' + "\n".join(blocks) + "</article>"


def _format_generation_warnings(warnings: list[str]) -> str:
    """Affiche les contrôles sans toucher au fragment généré."""
    if not warnings:
        return ""
    items = "".join(f"<li>{html.escape(warning)}</li>" for warning in warnings)
    return (
        '<aside class="generation-warning"><strong>Avertissement de mise en page</strong>'
        f"<ul>{items}</ul></aside>"
    )


def render_fiche_html(
    content: FicheContent,
    sources: list[dict],
    *,
    generated_at: datetime,
    org_name: str | None = None,
) -> str:
    """Entoure le corps LLM brut du gabarit AORIA RH et du design system."""
    date_str = generated_at.strftime("%d/%m/%Y")

    if content.body_html:
        _title, current_warnings = inspect_fiche_fragment(content.body_html)
        warnings = list(dict.fromkeys([*content.warnings, *current_warnings]))
        # Le fragment est injecté strictement tel qu'il a été produit. Seul un
        # avertissement séparé peut être ajouté, conformément aux règles projet.
        body = content.body_html + _format_generation_warnings(warnings)
    else:
        body = _render_legacy_body(content, sources)

    org_line = f" — {html.escape(org_name)}" if org_name else ""

    return f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="utf-8"><title>{_inline(content.titre)}</title>
<style>
  {_FONTS_CSS}
  @page {{ size: A4; margin: 14mm 0 22mm; }}
  @page:first {{ margin-top: 0; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Inter Variable', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
         color:#3f3f46; margin:0; font-size:13px; line-height:1.5; }}
  .header {{ background:{_VIOLET}; padding:12px 32px; display:grid;
             grid-template-columns:1fr auto 1fr; align-items:center; }}
  .header .logo {{ grid-column:1; justify-self:start; display:flex; align-items:center; }}
  .header svg {{ height:28px; width:auto; }}
  .header .logo-fallback {{ font-family:'Sora Variable','Segoe UI',sans-serif; color:#fff;
                            font-size:20px; font-weight:800; letter-spacing:.5px; }}
  .header .tag {{ grid-column:2; color:#ede9fe; font-size:11px; margin:0;
                 text-transform:uppercase; letter-spacing:1px; }}
  .body {{ padding:24px 32px 0; }}
  .fiche-content > :first-child {{ margin-top:0; }}
  .fiche-content h1, h1.titre {{ font-family:'Sora Variable','Segoe UI',sans-serif;
             color:{_VIOLET}; font-size:22px; font-weight:800; letter-spacing:-0.02em;
             line-height:1.25; margin:0 0 14px; }}
  .fiche-content h2 {{ font-family:'Sora Variable','Segoe UI',sans-serif; color:{_VIOLET};
       font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:.5px;
       margin:20px 0 8px; break-after:avoid; }}
  .fiche-content h3 {{ color:{_VIOLET}; font-size:13px; margin:14px 0 6px;
                      break-after:avoid; }}
  .fiche-content p {{ margin:0 0 10px; }}
  .fiche-content section {{ margin:0 0 16px; }}
  .fiche-content .intro {{ color:#52525b; font-size:14px; }}
  .fiche-content .essential, .essentiel {{ background:#f5f3ff;
               border-left:4px solid {_VIOLET}; padding:12px 16px; font-size:14px;
               font-weight:600; margin:0 0 20px; break-inside:avoid; }}
  .fiche-content .essential > :last-child {{ margin-bottom:0; }}
  .fiche-content .key-points {{ background:#fafafa; border-radius:8px;
                               padding:12px 16px 6px; break-inside:avoid; }}
  .section-icon {{ width:14px; height:14px; flex-shrink:0; }}
  .fiche-content ul, .fiche-content ol {{ margin:0 0 16px; padding-left:20px; }}
  .fiche-content li {{ margin-bottom:6px; break-inside:avoid; }}
  .fiche-content li > ul, .fiche-content li > ol {{ margin:6px 0 0; }}
  .fiche-content .procedure > ol {{ counter-reset:fiche-step; list-style:none;
                                   padding-left:0; }}
  .fiche-content .procedure > ol > li {{ counter-increment:fiche-step;
       position:relative; padding:8px 10px 8px 38px; margin-bottom:6px;
       border:1px solid #ede9fe; border-radius:7px; }}
  .fiche-content .procedure > ol > li::before {{ content:counter(fiche-step);
       position:absolute; left:10px; top:8px; width:20px; height:20px; border-radius:50%;
       background:{_VIOLET}; color:#fff; text-align:center; line-height:20px;
       font-weight:700; font-size:11px; }}
  .table-wrapper {{ overflow:hidden; margin:8px 0 16px; break-inside:avoid; }}
  table {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
  thead {{ display:table-header-group; }}
  tr {{ break-inside:avoid; }}
  th, td {{ border:1px solid #ede9fe; padding:6px 10px; text-align:left; }}
  th {{ background:#f5f3ff; color:{_VIOLET}; }}
  .fiche-content .warning, .exceptions {{ background:#fff7ed; border:1px solid #fed7aa;
                border-radius:8px; padding:12px 16px; margin:0 0 16px;
                break-inside:avoid; }}
  .fiche-content .warning h2 {{ color:#b45309; margin:0 0 6px; }}
  .fiche-content .warning > :last-child {{ margin-bottom:0; }}
  .fiche-content .info {{ background:#f0f9ff; border:1px solid #bae6fd;
                         border-radius:8px; padding:12px 16px; margin:0 0 16px;
                         break-inside:avoid; }}
  .fiche-content .info h2 {{ color:#0369a1; margin-top:0; }}
  .definitions {{ display:grid; grid-template-columns:max-content 1fr; gap:6px 14px;
                  margin:0 0 16px; }}
  .definitions dt {{ color:{_VIOLET}; font-weight:700; }}
  .definitions dd {{ margin:0; }}
  .legal-references {{ border-top:1px solid #ede9fe; padding-top:2px;
                       font-size:12px; color:#5f6b6a; }}
  .exceptions strong {{ display:flex; align-items:center; gap:6px; color:#b45309; }}
  .exceptions ul {{ margin:6px 0 0; }}
  .exceptions li:last-child {{ margin-bottom:0; }}
  .sources {{ font-size:12px; color:#5f6b6a; }}
  .generation-warning {{ border:1px solid #f59e0b; background:#fffbeb; border-radius:6px;
                         padding:8px 12px; margin:16px 0; font-size:10px; color:#92400e; }}
  .generation-warning ul {{ margin:4px 0 0; }}
  .footer {{ position:fixed; left:32px; right:32px; bottom:-17mm;
            border-top:1px solid #ede9fe; padding:7px 0 0; font-size:9.5px;
            line-height:1.35; color:#5f6b6a; }}
  .footer p {{ margin:0 0 2px; }}
  .footer .validite {{ color:{_VIOLET}; font-weight:600; margin:0 0 4px; }}
</style></head>
<body>
  <div class="header">
    <div class="logo">{_LOGO_HTML}</div>
    <div class="tag">Fiche pratique</div>
  </div>
  <div class="body">
    {body}
  </div>
  <div class="footer">
    <p class="validite">Contenu généré le {date_str}.
      Vérifiez l'actualité de ces règles avant application.</p>
    <p>Fiche générée par AORIA RH à partir de votre question{org_line}.
      &copy; {generated_at.year} AORIA RH.</p>
  </div>
</body></html>"""


def _slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:60] or "fiche-pratique"


def html_to_pdf(html_str: str) -> bytes:
    """Convertit le HTML sans autoriser le fragment à charger une URL externe."""
    from weasyprint import HTML  # import différé
    from weasyprint.urls import URLFetcher

    # Le protocole est refusé sans rendre la génération elle-même indisponible :
    # l'avertissement de format reste visible dans le PDF, le HTML reste brut.
    fetcher = URLFetcher(allowed_protocols={"data"}, fail_on_errors=False)
    return HTML(string=html_str, url_fetcher=fetcher.fetch).write_pdf()


# --- Orchestration -------------------------------------------------------


async def generate_fiche_content(
    *,
    question: str,
    answer_markdown: str,
    sources: list[dict] | None = None,
    organisation_id: str | None = None,
    user_id: str | None = None,
) -> FicheGeneration:
    """Appelle le LLM et conserve son fragment HTML exactement tel quel."""
    reference_lines = _format_reference_lines(sources or [])
    references_context = "\n".join(f"- {html.unescape(line)}" for line in reference_lines)
    if not references_context:
        references_context = "Aucune référence structurée supplémentaire."

    user_content = (
        f"Question posée : {question}\n\n"
        f"Réponse à mettre en forme :\n{answer_markdown}\n\n"
        "Références structurées autorisées, déjà citées dans la réponse :\n"
        f"{references_context}"
    )

    response = await _llm.chat.completions.create(
        model=FICHE_MODEL,
        messages=[
            {"role": "system", "content": FICHE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        max_completion_tokens=5000,
        reasoning_effort="minimal",
    )

    if response.usage:
        cost_tracker.log_bg(
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

    raw = response.choices[0].message.content or ""
    content = parse_fiche_content(raw)
    return FicheGeneration(eligible=True, content=content)


def render_fiche_pdf(
    content: FicheContent,
    sources: list[dict],
    *,
    generated_at: datetime,
    org_name: str | None = None,
) -> bytes:
    """Rend le PDF à partir du corps brut (ou du format historique)."""
    html_str = render_fiche_html(
        content, sources, generated_at=generated_at, org_name=org_name
    )
    return html_to_pdf(html_str)


def fiche_filename(content: FicheContent) -> str:
    """Nom de fichier PDF dérivé du titre de la fiche."""
    return f"fiche-{_slugify(content.titre)}.pdf"
