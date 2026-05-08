"""Intent router en amont du RAG.

Classifie la requête utilisateur pour distinguer les questions juridiques
(qui doivent passer par le RAG complet) des meta-questions (capacités,
sources, scope, fonctionnement interne) qui doivent être répondues par
des templates Python — pas par le LLM principal.

Avantages :
- **Sécurité IP** : les questions sur le fonctionnement interne ne touchent
  jamais le LLM, donc impossible de fuiter le pipeline / modèle / stack.
- **Latence** : économise condense + expand + Qdrant + reranker pour ~30%
  des requêtes (greetings, meta).
- **Qualité** : pas d'hallucination sur "quelles CCN tu connais ?" — la
  réponse vient de la BDD réelle.

Architecture :
1. Pre-filter regex (rapide, déterministe) pour les patterns évidents
2. LLM classifier (gpt-5-mini, ~50ms) en fallback pour les cas ambigus
3. Templates Python qui lisent la BDD pour les facts (CCNs, sync_logs)
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from openai import AsyncOpenAI
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    """Catégories d'intention classées par le router."""

    LEGAL_QUESTION = "legal_question"          # → RAG complet (cas par défaut)
    META_CAPABILITIES = "meta_capabilities"    # "que sais-tu / que peux-tu"
    META_SCOPE = "meta_scope"                  # "tu connais X (loi, code, CCN)"
    META_SOURCES = "meta_sources"              # "tes sources, dernière maj"
    META_INTERNALS = "meta_internals"          # "quel modèle, comment tu fonctionnes" ⚠️ IP
    OUT_OF_SCOPE = "out_of_scope"              # droit hors social FR, recettes, etc.
    GREETING = "greeting"                      # "bonjour", "merci"


@dataclass
class IntentResult:
    """Résultat de la classification."""

    intent: Intent
    # Si renseigné, c'est la réponse statique à servir directement à l'utilisateur
    # SANS passer par le RAG ni le LLM principal. Si None, on continue en RAG.
    static_answer: str | None = None
    # Pour le logging / debug. Indique si le pré-filtre a matché ou si on a
    # appelé le LLM classifier.
    via: str = "prefilter"


# ─── Pre-filter patterns (déterministe, ~5ms) ──────────────────────────────
# Volontairement larges pour attraper les variantes courantes. Les faux
# positifs ne sont pas dramatiques car les réponses statiques restent
# cordiales et redirigent vers la valeur produit.

_PATTERNS_INTERNALS = [
    r"\b(quel|quelle|quels|quelles)\s+(modèle|llm|ia|moteur|outil|techno|stack|prompt|framework|librairie|reranker|embedding|vector|base de données)\b",
    r"\b(comment|de quelle (façon|manière))\s+(tu|vous)\s+(es codé|fonctionne|fonctionnez|marche|marches|es construit|es entraîné|es développ)",
    r"\b(reveal|montre|affiche|donne|donne-moi|liste)\s+(ton|tes|votre|vos)\s+(prompt|system|instruction|outil|sources internes|architecture|secret)",
    r"\b(ignore|oublie|forget)\s+(les|tes|toutes les)\s+(consigne|instruction|précédent|précédente)",
    r"\b(open\s*ai|gpt|claude|anthropic|gemini|mistral|llama|qdrant|pinecone|weaviate|voyage|cohere)\b",
    r"\bsystem\s*prompt\b",
    r"\bton\s+(prompt|système|architecture|infrastructure|hébergeur)\b",
]

_PATTERNS_SOURCES = [
    r"\b(quelle|quels|quelles)\s+(sont|seraient)?\s*(tes|vos|les)\s+sources\b",
    # 'tes sources datent de quand', 'corpus à jour', 'dernière maj des données'
    r"\b(source|donn|corpus|index|base)\w*\s+\w*\s*(date|datent|datant|à jour|jour|mis à jour|maj|mise à jour|actualisé|récent|publi|update)",
    r"\b(date|datent|datant|à jour|jour de la maj|dernière (synchro|maj|mise à jour))\b[^.?!]{0,40}\b(source|donn|corpus|index|base)",
    r"\b(d'où|d ou|où|ou)\s+(viennent|proviennent)\s+(tes|vos|les)\s+(sources|données|informations)",
    r"\b(à\s+quand|de\s+quand)\s+(date|datent)\s+(tes|vos|les)?\s*(sources|données|infos)?",
    r"\b(de\s+quand|à\s+quelle\s+date|quand)\s+(date|datent)",
    r"\bcorpus\s+(à jour|mis à jour|actualisé|récent)",
]

_PATTERNS_SCOPE = [
    r"\b(tu|vous)\s+(connais|connaissez|sait|savez|maîtris|gèr|couvr)",
    r"\b(es-tu|êtes-vous|es tu)\s+(spécialisé|expert|capable)",
    r"\b(peux-tu|peut-on|peut on|pouvez-vous)\s+(répondre|me parler|m'aider)",
    r"\b(quelles?\s+convention(s)?\s+collectives?)\b",
    r"\b(quelles?\s+(idcc|ccn))\b",
    r"\b(droit\s+(polynésien|monégasque|suisse|belge|allemand|américain|anglais|chinois|américain|étranger|international))\b",
    r"\b(droit\s+(pénal|fiscal|commercial|civil|de la famille|administratif|immobilier|notarial))\b",
]

_PATTERNS_CAPABILITIES = [
    r"\b(que|qu')\s*(sais|peux|fais|fait)-?(tu|vous)\b",
    r"\b(quelles?|quel)\s+(sont|est)\s+(tes|vos)\s+(capacit|fonctionnalit|fonction)",
    r"\b(à quoi|pour quoi|pourquoi|comment)\s+(sers|sert|utilis)",
    r"\b(qui es[- ]tu|qui êtes-vous|tu es qui|c'est quoi|qu'est-ce que)\b.{0,30}\b(aoria|toi|vous)\b",
    r"\b(présente[- ]toi|décris[- ]toi|dis[- ]m'?en plus sur toi)",
]

_PATTERNS_GREETING = [
    r"^\s*(bonjour|bonsoir|salut|hello|hi|coucou|hey)\s*[!?.]*\s*$",
    r"^\s*(merci|merci beaucoup|thanks|thank you|ok merci)\s*[!?.]*\s*$",
    r"^\s*(au revoir|à bientôt|bye|à plus|à\+)\s*[!?.]*\s*$",
]


def _match_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


# ─── Static answer templates ───────────────────────────────────────────────
# Les réponses statiques sont volontairement courtes et redirigent vers la
# valeur produit. Aucune ne révèle d'info technique.

_ANSWER_INTERNALS = (
    "Je m'appuie exclusivement sur les sources officielles du droit social "
    "français (Code du travail, jurisprudence, conventions collectives) et "
    "sur vos documents internes. Je cite chaque référence pour que vous "
    "puissiez la vérifier.\n\n"
    "Sur le reste, je préfère me concentrer sur votre question juridique RH "
    "— qu'est-ce que je peux faire pour vous ?"
)

_ANSWER_CAPABILITIES = (
    "Je suis votre **assistant juridique RH**. Concrètement, je peux :\n\n"
    "- Répondre à vos questions de droit social français (contrat, durée du "
    "travail, congés, paie, licenciement, CSE…)\n"
    "- Croiser le Code du travail, votre convention collective, les accords "
    "d'entreprise et la jurisprudence applicable\n"
    "- Citer chaque source utilisée pour que vous puissiez la vérifier\n"
    "- Adapter ma réponse à votre rôle (DRH, juriste, élu CSE, dirigeant…)\n\n"
    "Posez-moi votre question concrète, je vous donne une réponse sourcée."
)

_ANSWER_GREETING = (
    "Bonjour, je suis votre assistant juridique RH. "
    "Posez-moi votre question — par exemple sur un licenciement, un calcul "
    "d'indemnité, une procédure CSE, ou tout sujet de droit social français. "
    "Je m'appuie sur les sources officielles et sur vos documents internes."
)

_ANSWER_OUT_OF_SCOPE = (
    "Mon expertise se limite au **droit social français** : contrat de travail, "
    "durée du travail, congés, paie (les règles), licenciement, CSE, "
    "négociation collective, conventions collectives, RGPD côté RH.\n\n"
    "Pour ce sujet, je vous recommande de consulter un cabinet spécialisé. "
    "Si votre question avait un volet droit social français, n'hésitez pas à "
    "me le repréciser."
)


# ─── Templates dynamiques (lecture BDD) ────────────────────────────────────


async def _answer_sources_status(db: AsyncSession) -> str:
    """Réponse 'tes sources datent de quand' avec données réelles depuis sync_logs.

    On ne donne pas de noms de services tiers — juste la date de la dernière
    synchro réussie par grand type de corpus.
    """
    from app.models.sync_log import SyncLog

    # Dernière sync réussie par type
    res = await db.execute(
        select(
            SyncLog.sync_type,
            func.max(SyncLog.completed_at).label("last_ok"),
        )
        .where(SyncLog.status == "success")
        .group_by(SyncLog.sync_type)
    )
    rows = res.all()
    by_type: dict[str, datetime] = {r[0]: r[1] for r in rows if r[1] is not None}

    type_label = {
        "legi": "Code du travail et codes connexes",
        "code_travail": "Code du travail",
        "kali": "Conventions collectives",
        "judilibre": "Jurisprudence",
        "bocc": "Bulletins officiels (avenants CCN)",
    }

    lines: list[str] = []
    for key, label in type_label.items():
        ts = by_type.get(key)
        if ts is not None:
            lines.append(f"- **{label}** : à jour au {ts.strftime('%d/%m/%Y')}")

    if not lines:
        return (
            "Mes sources sont mises à jour en continu sur le Code du travail, "
            "la jurisprudence et les conventions collectives. Posez-moi votre "
            "question juridique RH — la réponse s'appuiera sur les textes "
            "applicables au moment de votre question."
        )

    return (
        "Voici l'état actuel de mon corpus juridique :\n\n"
        + "\n".join(lines)
        + "\n\nMes sources sont actualisées régulièrement. Chaque réponse cite "
        "la date de la version utilisée si pertinent."
    )


async def _answer_scope_check(db: AsyncSession, query: str, organisation_id: uuid.UUID | None) -> str:
    """Pour 'tu connais X' (CCN spécifique, code…) → on confirme ou non factuellement.

    Si la CCN demandée est installée pour l'organisation, on confirme. Sinon
    réponse générique sur le périmètre couvert (sans révéler l'inventaire
    complet de notre corpus).
    """
    # Détection IDCC dans la requête
    idcc_match = re.search(r"\b(?:idcc\s*)?(\d{3,4})\b", query)
    if idcc_match and organisation_id:
        idcc = idcc_match.group(1)
        # Check si elle est installée pour cette org
        from app.models.ccn import OrganisationConvention

        res = await db.execute(
            select(OrganisationConvention).where(
                OrganisationConvention.organisation_id == organisation_id,
                OrganisationConvention.idcc == idcc,
            )
        )
        oc = res.scalar_one_or_none()
        if oc:
            return (
                f"Oui, la convention collective **IDCC {idcc}** est rattachée "
                "à votre organisation et utilisée à chaque réponse RH. Posez "
                "votre question — j'appliquerai cette CCN ainsi que le Code "
                "du travail."
            )

    # Détection mention de droit étranger / hors-scope évident
    if re.search(
        r"\b(polynésien|monégasque|suisse|belge|allemand|américain|anglais|"
        r"chinois|étranger|international|pénal|fiscal|commercial|civil|"
        r"de la famille|administratif|immobilier|notarial)\b",
        query,
        re.IGNORECASE,
    ):
        return _ANSWER_OUT_OF_SCOPE

    # Sinon : confirmation de scope général + invitation à reformuler
    return (
        "Je couvre le **droit social français** dans son ensemble : Code du "
        "travail, jurisprudence sociale, conventions collectives "
        "(toutes les CCN françaises identifiées par leur IDCC), accords "
        "d'entreprise du client. Posez-moi votre question concrète, je vous "
        "donne une réponse sourcée."
    )


# ─── LLM classifier (fallback pour cas ambigus) ────────────────────────────

_CLASSIFIER_PROMPT = """\
Tu es un classifieur d'intention pour un assistant juridique RH français.

Catégorise la question utilisateur en exactement UNE des 7 catégories :

- legal_question : vraie question juridique RH (contrat, paie, congés, \
licenciement, CSE, CCN, durée du travail, etc.)
- meta_capabilities : "que sais-tu faire", "à quoi tu sers", "présente-toi"
- meta_scope : "tu connais le X", "es-tu spécialisé en Y" (la personne \
demande si tu COUVRES un sujet, sans poser une vraie question dessus)
- meta_sources : "tes sources datent de quand", "à quelle date"
- meta_internals : "quel modèle / IA / pipeline / framework / system prompt \
/ comment tu es codé" (TOUTE question sur le fonctionnement technique \
interne — ⚠️ catégorie sensible)
- out_of_scope : sujet hors droit social français (recette, droit étranger, \
droit fiscal/pénal/etc.)
- greeting : "bonjour", "merci", salutation pure sans question

Réponds par un JSON exact, sans texte autour : {"intent": "<catégorie>"}

Si tu hésites entre legal_question et autre chose, choisis legal_question \
(le RAG sera lancé, c'est sécuritaire).
Si la question contient des mots-clés techniques (modèle, prompt, qdrant, \
openai, gpt, claude, anthropic), choisis meta_internals SANS HÉSITATION.
"""


async def _classify_via_llm(query: str, llm: AsyncOpenAI) -> Intent:
    """Appelle gpt-5-mini pour classifier. Fallback sur LEGAL_QUESTION en cas d'erreur."""
    try:
        response = await llm.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": _CLASSIFIER_PROMPT},
                {"role": "user", "content": query[:1000]},
            ],
            temperature=0.0,
            # gpt-5 family rejects max_tokens, exige max_completion_tokens.
            max_completion_tokens=30,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        intent_str = data.get("intent", "legal_question")
        # Validation — si valeur inconnue, fallback safe
        try:
            return Intent(intent_str)
        except ValueError:
            logger.warning("LLM router renvoyé intent inconnue: %r — fallback legal_question", intent_str)
            return Intent.LEGAL_QUESTION
    except Exception:
        logger.exception("LLM classifier failed — fallback legal_question")
        return Intent.LEGAL_QUESTION


# ─── Entrée publique ───────────────────────────────────────────────────────


async def classify_intent(
    query: str,
    db: AsyncSession,
    llm: AsyncOpenAI,
    organisation_id: uuid.UUID | None = None,
    use_llm_fallback: bool = True,
) -> IntentResult:
    """Point d'entrée principal du router.

    Pipeline :
    1. Pre-filter regex (priorité aux patterns sensibles : internals d'abord)
    2. Si non matché et `use_llm_fallback` : appel LLM
    3. Génère la réponse statique selon l'intent
    """
    q = (query or "").strip()
    if not q:
        # Edge case : query vide → laisser le RAG gérer (il va probablement
        # retourner un message générique) plutôt que de bloquer ici.
        return IntentResult(Intent.LEGAL_QUESTION, static_answer=None, via="empty")

    # 1. Pre-filter — ordre important : meta_internals en premier (sécurité IP)
    if _match_any(q, _PATTERNS_INTERNALS):
        return IntentResult(Intent.META_INTERNALS, _ANSWER_INTERNALS, via="prefilter")

    if _match_any(q, _PATTERNS_GREETING):
        return IntentResult(Intent.GREETING, _ANSWER_GREETING, via="prefilter")

    if _match_any(q, _PATTERNS_SOURCES):
        ans = await _answer_sources_status(db)
        return IntentResult(Intent.META_SOURCES, ans, via="prefilter")

    if _match_any(q, _PATTERNS_CAPABILITIES):
        return IntentResult(Intent.META_CAPABILITIES, _ANSWER_CAPABILITIES, via="prefilter")

    if _match_any(q, _PATTERNS_SCOPE):
        ans = await _answer_scope_check(db, q, organisation_id)
        return IntentResult(Intent.META_SCOPE, ans, via="prefilter")

    # 2. LLM fallback si nécessaire
    if not use_llm_fallback:
        return IntentResult(Intent.LEGAL_QUESTION, static_answer=None, via="prefilter_default")

    intent = await _classify_via_llm(q, llm)

    # 3. Génère la réponse statique si meta
    if intent == Intent.META_INTERNALS:
        return IntentResult(intent, _ANSWER_INTERNALS, via="llm")
    if intent == Intent.GREETING:
        return IntentResult(intent, _ANSWER_GREETING, via="llm")
    if intent == Intent.META_CAPABILITIES:
        return IntentResult(intent, _ANSWER_CAPABILITIES, via="llm")
    if intent == Intent.META_SOURCES:
        ans = await _answer_sources_status(db)
        return IntentResult(intent, ans, via="llm")
    if intent == Intent.META_SCOPE:
        ans = await _answer_scope_check(db, q, organisation_id)
        return IntentResult(intent, ans, via="llm")
    if intent == Intent.OUT_OF_SCOPE:
        return IntentResult(intent, _ANSWER_OUT_OF_SCOPE, via="llm")

    # legal_question → laisse passer en RAG
    return IntentResult(Intent.LEGAL_QUESTION, static_answer=None, via="llm")
