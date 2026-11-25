"""LLM reviewer: finds errors (never imprecisions), then tries to refute each one.

A finding is kept only if both quotes are found verbatim (the answer and the source)
and the counter-check upholds it. Anything unproven is recorded, never alerted.
"""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal

from app.services.cost_tracker import compute_cost

KINDS = ["montant", "date", "article", "jurisprudence", "contradiction", "conclusion"]

_MAX_SOURCE_CHARS = 15_000
_MAX_TOTAL_SOURCE_CHARS = 80_000
_MAX_HISTORY_CHARS = 2_500

REVIEW_PROMPT = """\
Tu es contrôleur qualité juridique (droit du travail français). Une réponse a été rédigée \
par un assistant à partir de sources numérotées. Ton seul travail : trouver les ERREURS \
certaines, en t'appuyant sur les sources fournies.

Une ERREUR est uniquement :
- montant : un chiffre, taux, plafond, durée ou seuil différent de celui de la source, ou \
un calcul faux ;
- date : une date ou une échéance mal calculée à partir de la règle de la source et des \
faits (refais le décompte mois par mois ou jour par jour) ;
- article : un article cité pour une règle que son texte fourni ne pose pas ;
- jurisprudence : une décision de justice citée pour ce qu'elle n'a pas jugé : la réponse \
lui prête une solution, un principe ou un motif décisif que son texte ne contient pas \
(la cour a tranché pour une autre raison, sur un autre point, ou dans l'autre sens). \
source_quote reprend alors le passage de la décision qui montre ce qu'elle a réellement \
jugé et pourquoi ;
- contradiction : une affirmation contredite par le texte d'une source ;
- conclusion : un verdict (oui/non, droit/pas de droit, obligatoire/facultatif) contraire \
à la règle des sources.

Ne signale JAMAIS : une imprécision, une omission, une nuance manquante, le style, une \
formulation prudente, une affirmation simplement non sourcée, une interprétation \
raisonnable, une hypothèse annoncée comme telle, ce que les sources ne permettent pas de \
trancher. Dans le doute, ne signale rien : une fausse alerte coûte plus cher qu'un oubli.

Pour chaque erreur :
- answer_quote : copie EXACTE, caractère pour caractère, du passage fautif de la réponse \
(une phrase au plus) ;
- source_index : numéro de la source qui prouve l'erreur ;
- source_quote : copie EXACTE du passage de cette source qui prouve l'erreur ;
- explanation : pourquoi c'est faux, en deux phrases au plus, avec le décompte s'il y en a un ;
- correction : la phrase corrigée, prête à remplacer answer_quote.

S'il n'y a aucune erreur certaine, renvoie une liste vide."""

COUNTER_PROMPT = """\
Tu es un second contrôleur, chargé de RÉFUTER un constat d'erreur porté sur une réponse \
juridique. Cherche toute raison pour laquelle la réponse n'est pas fausse : passage mal \
lu ou sorti de son contexte, hypothèse explicitement annoncée, règle venant d'une autre \
source ou d'un autre texte applicable, simple imprécision, correction apportée ailleurs \
dans la réponse, décompte du contrôleur lui-même faux. Pour une décision de justice : \
le résumé de la réponse reste-t-il fidèle à ce que la cour a jugé et à sa raison décisive ?

Réponds confirmed uniquement si la réponse est certainement fausse sur ce point au regard \
de la source citée. Sinon réponds refuted. Donne la raison en deux phrases au plus."""

REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "kind",
                    "answer_quote",
                    "source_index",
                    "source_quote",
                    "explanation",
                    "correction",
                ],
                "properties": {
                    "kind": {"type": "string", "enum": KINDS},
                    "answer_quote": {"type": "string"},
                    "source_index": {"type": "integer"},
                    "source_quote": {"type": "string"},
                    "explanation": {"type": "string"},
                    "correction": {"type": "string"},
                },
            },
        }
    },
}

COUNTER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "reason"],
    "properties": {
        "verdict": {"type": "string", "enum": ["confirmed", "refuted"]},
        "reason": {"type": "string"},
    },
}


@dataclass
class ReviewSource:
    label: str
    text: str


@dataclass
class ReviewInput:
    answer: str
    question: str
    answer_date: str
    history: list[tuple[str, str]] = field(default_factory=list)
    sources: list[ReviewSource] = field(default_factory=list)


@dataclass
class LlmFinding:
    kind: str
    answer_quote: str
    source_index: int | None
    source_quote: str
    explanation: str
    correction: str
    validation: str = "unanchored"
    validation_reason: str | None = None
    source_label: str | None = None


@dataclass
class LlmReviewResult:
    findings: list[LlmFinding]
    cost_usd: Decimal
    calls: list[dict]


_QUOTES = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "`": "'",
        "«": '"',
        "»": '"',
        "“": '"',
        "”": '"',
        "‑": "-",
        "–": "-",
        "—": "-",
        "−": "-",
    }
)


def normalize_for_match(text: str) -> str:
    """Compare quotes without markdown, typography, case or spacing differences."""
    text = unicodedata.normalize("NFKC", text or "").translate(_QUOTES)
    text = re.sub(r"[*_#>|]", " ", text)
    text = re.sub(r"⁠", "", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_found(quote: str, text: str) -> bool:
    """Every fragment of the quote (split on ellipses) appears in the text, in order."""
    fragments = [
        normalize_for_match(part) for part in re.split(r"\.\.\.|…|\[\.\.\.\]", quote or "")
    ]
    fragments = [part.strip(" .,;:") for part in fragments if len(part.strip(" .,;:")) >= 3]
    if not fragments:
        return False
    haystack = normalize_for_match(text)
    position = 0
    for fragment in fragments:
        index = haystack.find(fragment, position)
        if index < 0:
            return False
        position = index + len(fragment)
    return True


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + " […]"


def build_review_message(data: ReviewInput) -> str:
    parts = [f"Date de la réponse : {data.answer_date}."]
    if data.history:
        lines = [
            f"{'Utilisateur' if role == 'user' else 'Assistant'} : "
            f"{_clip(content, _MAX_HISTORY_CHARS)}"
            for role, content in data.history
        ]
        parts.append("## Échanges précédents\n\n" + "\n\n".join(lines))
    parts.append(f"## Question\n\n{data.question}")
    budget = _MAX_TOTAL_SOURCE_CHARS
    source_lines = []
    for index, source in enumerate(data.sources, start=1):
        if budget <= 0:
            break
        text = _clip(source.text, min(_MAX_SOURCE_CHARS, budget))
        budget -= len(text)
        source_lines.append(f"### Source {index} — {source.label}\n\n{text}")
    parts.append(
        "## Sources\n\n" + ("\n\n".join(source_lines) if source_lines else "(aucune source)")
    )
    parts.append(f"## Réponse à contrôler\n\n{data.answer}")
    return "\n\n".join(parts)


class LlmReviewer:
    def __init__(self, client, model: str, *, reasoning_effort: str = "medium"):
        self.client = client
        self.model = model
        self.reasoning_effort = reasoning_effort

    async def _call(self, system: str, user: str, schema: dict, name: str) -> tuple[dict, dict]:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": schema},
            },
            max_completion_tokens=16_000,
            reasoning_effort=self.reasoning_effort,
        )
        usage = response.usage
        call = {
            "name": name,
            "tokens_input": getattr(usage, "prompt_tokens", 0) or 0,
            "tokens_output": getattr(usage, "completion_tokens", 0) or 0,
            "usage": usage,
            "cost_usd": compute_cost(
                "openai",
                self.model,
                getattr(usage, "prompt_tokens", 0) or 0,
                getattr(usage, "completion_tokens", 0) or 0,
                usage=usage,
            ),
        }
        raw = response.choices[0].message.content or "{}"
        return json.loads(raw), call

    async def review(self, data: ReviewInput) -> LlmReviewResult:
        user = build_review_message(data)
        payload, call = await self._call(REVIEW_PROMPT, user, REVIEW_SCHEMA, "quality_review")
        calls = [call]
        findings: list[LlmFinding] = []
        for item in payload.get("findings", [])[:10]:
            index = item.get("source_index")
            source = (
                data.sources[index - 1]
                if isinstance(index, int) and 1 <= index <= len(data.sources)
                else None
            )
            finding = LlmFinding(
                kind=item.get("kind", "contradiction"),
                answer_quote=(item.get("answer_quote") or "")[:2000],
                source_index=index if source else None,
                source_quote=(item.get("source_quote") or "")[:3000],
                explanation=(item.get("explanation") or "")[:2000],
                correction=(item.get("correction") or "")[:2000],
                source_label=source.label[:500] if source else None,
            )
            # Anchoring: a quote that is not found verbatim is the reviewer's invention.
            if (
                source
                and quote_found(finding.answer_quote, data.answer)
                and quote_found(finding.source_quote, source.text)
            ):
                finding.validation = "pending"
            else:
                finding.validation_reason = "citation introuvable dans la réponse ou la source"
            findings.append(finding)

        async def counter_check(finding: LlmFinding) -> None:
            source = data.sources[finding.source_index - 1]
            message = (
                f"Date de la réponse : {data.answer_date}.\n\n## Question\n\n{data.question}"
                f"\n\n## Réponse complète\n\n{data.answer}"
                f"\n\n## Source citée — {source.label}\n\n{_clip(source.text, _MAX_SOURCE_CHARS)}"
                "\n\n## Constat à réfuter\n\n"
                + json.dumps(
                    {
                        "type": finding.kind,
                        "passage_de_la_reponse": finding.answer_quote,
                        "passage_de_la_source": finding.source_quote,
                        "explication": finding.explanation,
                        "correction_proposee": finding.correction,
                    },
                    ensure_ascii=False,
                )
            )
            try:
                verdict, verdict_call = await self._call(
                    COUNTER_PROMPT, message, COUNTER_SCHEMA, "quality_counter_check"
                )
            except Exception as exc:  # unverified: recorded, never alerted
                finding.validation = "unverified"
                finding.validation_reason = f"contre-vérification en échec : {type(exc).__name__}"
                return
            calls.append(verdict_call)
            finding.validation = "confirmed" if verdict.get("verdict") == "confirmed" else "refuted"
            finding.validation_reason = (verdict.get("reason") or "")[:2000]

        pending = [finding for finding in findings if finding.validation == "pending"]
        await asyncio.gather(*(counter_check(finding) for finding in pending))
        return LlmReviewResult(
            findings=findings,
            cost_usd=sum((c["cost_usd"] for c in calls), Decimal(0)),
            calls=calls,
        )
