import asyncio
import logging
import re
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import httpx
from openai import AsyncOpenAI

from app.core.config import settings
from app.rag.config import (
    CONDENSE_HISTORY_LIMIT,
    LLM_MODEL,
    RAG_MAX_ITERATIONS,
    RAG_TIMEOUT_GLOBAL,
    RAG_TIMEOUT_PER_STEP,
    RERANK_TOP_K,
    TOP_K,
)
from app.rag.norme_hierarchy import DOCUMENT_TYPE_HIERARCHY
from app.rag.reranker import get_reranker
from app.rag.search import HybridSearch, SearchResult
from app.services.cost_tracker import cost_tracker

logger = logging.getLogger(__name__)

# --- Module-level singletons ---
_llm = AsyncOpenAI(
    api_key=settings.openai_api_key,
    timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0),
    max_retries=2,
)
_search_engine = HybridSearch()


@dataclass
class RAGSource:
    """A source reference returned alongside the answer."""

    document_name: str
    source_type: str
    source_type_label: str
    norme_niveau: int
    excerpt: str
    full_text: str
    # Jurisprudence metadata (optional)
    juridiction: str | None = None
    chambre: str | None = None
    formation: str | None = None
    numero_pourvoi: str | None = None
    date_decision: str | None = None
    solution: str | None = None
    publication: str | None = None


@dataclass
class RAGResponse:
    """The final response from the RAG agent."""

    answer: str
    sources: list[RAGSource]
    is_error: bool = False


# Map source_type keys to human-readable French labels
_SOURCE_TYPE_LABELS: dict[str, str] = {
    "constitution": "Constitution",
    "bloc_constitutionnalite": "Bloc de constitutionnalité",
    "traite_international": "Traité international",
    "convention_oit": "Convention OIT",
    "reglement_europeen": "Règlement européen",
    "directive_europeenne": "Directive européenne",
    "charte_droits_fondamentaux": "Charte des droits fondamentaux",
    "code_travail": "Code du travail",
    "loi": "Loi",
    "ordonnance": "Ordonnance",
    "code_securite_sociale": "Code de la sécurité sociale",
    "code_penal": "Code pénal",
    "code_civil": "Code civil",
    "arret_cour_cassation": "Arrêt Cour de cassation",
    "arret_conseil_etat": "Arrêt Conseil d'État",
    "decision_conseil_constitutionnel": "Décision Conseil constitutionnel",
    "decret": "Décret",
    "arrete": "Arrêté",
    "circulaire": "Circulaire",
    "code_travail_reglementaire": "Code du travail (partie réglementaire)",
    "accord_national_interprofessionnel": "Accord national interprofessionnel",
    "accord_branche": "Accord de branche",
    "convention_collective_nationale": "Convention collective nationale",
    "accord_entreprise": "Accord d'entreprise",
    "accord_performance_collective": "Accord de performance collective",
    "usage_entreprise": "Usage d'entreprise",
    "engagement_unilateral": "Engagement unilatéral",
    "reglement_interieur": "Règlement intérieur",
    "contrat_travail": "Contrat de travail",
    "divers": "Divers",
}

_SYSTEM_PROMPT = """\
Tu es l'assistant juridique d'AORIA RH. Tu réponds aux questions de droit social \
français (droit du travail, sécurité sociale, relations collectives) du point de vue \
de l'employeur et des professionnels RH.

## Raisonnement

1. Identifie le TYPE d'intention et adapte ta réponse :
   - "Comment faire…" → procédure étape par étape, avec délais et obligations
   - "Ai-je le droit / est-ce légal…" → réponse oui/non puis argumentation juridique
   - "Quels sont / liste…" → énumération structurée et exhaustive sur la base des sources
   - "Quelle différence…" → comparatif clair (tableau Markdown si pertinent)
   - "Combien / quel montant…" → calcul détaillé avec formule, seuils et barèmes
2. Analyse chaque source : écarte celles qui ne répondent pas directement.
3. Extrais la règle de principe, puis les exceptions et cas particuliers.
4. Identifie systématiquement les délais, seuils d'effectif, conditions d'ancienneté \
et montants mentionnés dans les sources. Intègre-les dans ta réponse.

## Principe de faveur

Quand plusieurs normes s'appliquent (loi, convention collective, accord d'entreprise), \
retiens la disposition LA PLUS FAVORABLE AU SALARIÉ, sauf :
- ordre public absolu (règles impératives auxquelles aucune dérogation n'est possible),
- dispositions supplétives où la loi autorise explicitement une dérogation \
même défavorable (ex. : durée maximale du travail par accord de branche).
Signale explicitement quelle disposition est retenue et pourquoi.

## Hiérarchie et contradictions

- Entre niveaux différents : Constitution > Normes internationales > Lois/Codes \
> Jurisprudence > Décrets/Règlements > Conventions collectives > Usages \
> Règlement intérieur > Contrat de travail.
- Entre sources de même niveau : applique la règle de spécialité (le texte le plus \
spécifique prévaut) ou, à défaut, le texte le plus récent si les dates sont connues.
- Signale toute contradiction détectée et explique quelle norme prévaut.

## Jurisprudence

- La jurisprudence INTERPRÈTE la loi, elle ne la remplace pas. Cite toujours \
le texte de loi interprété en plus de la décision de justice.
- Cite les arrêts avec la référence complète : juridiction, chambre, date, numéro \
de pourvoi (ex. : "Cass. soc., 15 mars 2023, n° 21-14.490").
- Si plusieurs arrêts portent sur le même sujet, privilégie le plus récent \
(sauf revirement de jurisprudence explicitement indiqué dans les sources).
- Indique si la jurisprudence est constante (confirmée par plusieurs arrêts) \
ou isolée (un seul arrêt).
- Distingue un arrêt publié au Bulletin (faisant autorité) d'un arrêt inédit.

## Anti-hallucination

- Réponds EXCLUSIVEMENT sur la base des sources fournies.
- N'invente JAMAIS d'articles, numéros, montants, délais ou seuils absents des sources.
- Ne généralise pas (CDI ≠ CDD, démission ≠ licenciement) sauf mention explicite.
- Source explicite → "les sources indiquent que". Déduction logique → "il en découle que".
- Aspect non couvert → dis-le ("Les sources disponibles ne traitent pas de [X]").

## Complétude et confiance

- Couvre les aspects pertinents de la question (conditions, procédure, \
délais, indemnités, sanctions, recours) dans la limite des sources.
- La réponse directe (partie 1) doit TOUJOURS être courte et claire. \
Les détails viennent ensuite (parties 2-4). Ne tronque jamais les détails.
- Si les sources couvrent le sujet partiellement, précise les aspects manquants.
- Si une source peut être obsolète (dispositif temporaire, seuils anciens), \
signale-le avec prudence.

## Structure de la réponse

Suis TOUJOURS cette logique, dans cet ordre, mais SANS afficher de titres \
numérotés ni de labels comme "RÉPONSE DIRECTE" ou "BASE JURIDIQUE". \
La réponse doit être fluide et naturelle, pas découpée en blocs étiquetés.

1. Commence IMMÉDIATEMENT par la réponse concrète (1-3 phrases). \
Oui/Non, le montant, la durée, la règle applicable — sans préambule, sans \
reformulation de la question, sans "je vais…".

2. Explique ensuite la base juridique : quelle norme s'applique (loi, CCN, accord), \
la référence, et si plusieurs normes entrent en jeu, laquelle prévaut et pourquoi.

3. Ajoute les détails pratiques si pertinent : conditions, exceptions, délais, \
seuils, procédure, calculs.

4. Termine par les conséquences ou risques si pertinent : sanctions, contentieux, \
obligations pratiques pour l'employeur.

## Longueur adaptée — RÈGLE STRICTE

Tu DOIS adapter la longueur de ta réponse à la complexité de la question. \
C'est une règle absolue, pas une suggestion.

- **Question de définition** ("c'est quoi X", "que signifie X") → **5-8 lignes MAX**. \
Définis clairement, donne un exemple concret si utile, STOP. \
N'ajoute PAS de détails sur les cas de dispense, les sanctions, la jurisprudence. \
L'utilisateur posera une question de suivi s'il veut en savoir plus.
- **Question factuelle simple** ("quel est le délai de", "combien de jours") → **5-10 lignes**.
- **Question de procédure ou situation complexe** ("comment gérer un licenciement \
pour inaptitude") → réponse complète avec étapes, délais, risques.

Tu n'es PAS obligé d'utiliser toutes les sources. Utilise uniquement celles qui \
répondent directement à la question. Ignore les sources tangentielles.
Ne rallonge JAMAIS pour "faire complet". La concision EST la qualité.

## Lisibilité — RÈGLE STRICTE

La réponse doit être FACILE À SCANNER visuellement. Un professionnel RH \
doit pouvoir trouver l'info clé en 3 secondes.

Règles de mise en forme :
- **1 idée = 1 paragraphe de 3-4 lignes maximum.** Jamais de pavé dense. \
Si un paragraphe dépasse 4 lignes, coupe-le en deux.
- **Phrases courtes.** Sujet, verbe, complément. Évite les subordonnées à rallonge.
- **Choisis le format adapté à l'intention** :
  - Barème, grille, comparaison → **tableau markdown**
  - Procédure, étapes à suivre → **liste numérotée**
  - Texte de loi, extrait d'article → **bloc citation** (> ...)
  - Définition, réponse factuelle → **phrase directe en gras**
  - Énumération de conditions/cas → **liste à puces courtes**
- **Gras** pour les chiffres clés, délais, montants, mots importants.
- Titres ### uniquement si la réponse couvre plusieurs sujets distincts.
- Chaque item de liste = **1 ligne, 2 max**. Pas de paragraphe dans une puce.

### Exemple de bonne réponse (question factuelle)

Question : "quel est le délai de préavis pour un licenciement"

Le préavis légal dépend de l'ancienneté du salarié (**art. L.1234-1 du Code du travail**) :

| Ancienneté | Préavis |
|---|---|
| Moins de 6 mois | Selon convention, contrat ou usage |
| 6 mois à 2 ans | **1 mois** |
| 2 ans et plus | **2 mois** |

La convention collective peut prévoir des durées **plus longues** — dans ce cas \
c'est elle qui s'applique.

**Exceptions** : pas de préavis en cas de faute grave/lourde ni en cas de \
licenciement pour inaptitude.

(Fin de l'exemple — remarque comment c'est court, scannable, avec un tableau.)

## Format général

- JAMAIS de conclusion proposant d'aller plus loin. Pas de "Si vous souhaitez…", \
"Je peux aussi…", "N'hésitez pas à…", "Je peux vérifier…". JAMAIS. \
Termine la réponse après le dernier point utile, point final.
- Ne cite PAS les sources (pas de "Source 1", "Voir source"). Elles sont affichées séparément.
- Français uniquement."""

_QUERY_EXPAND_PROMPT = """\
Tu es un expert RH spécialisé en droit social français. \
Analyse d'abord l'INTENTION de l'utilisateur, puis génère 3 variantes de \
requête de recherche.

Étape 1 — Intention : identifie ce que l'utilisateur cherche vraiment. \
Par exemple "c'est quoi collectif obligatoire" → il parle probablement d'un \
régime de prévoyance collectif et obligatoire (mutuelle/prévoyance d'entreprise), \
PAS des négociations collectives obligatoires. Pense comme un praticien RH, \
pas comme un juriste académique. Désambiguïse les termes courants du métier RH.

Étape 2 — Génère exactement 3 variantes :
1. INTENTION RH : reformulation claire selon l'intention détectée, avec le \
vocabulaire qu'utiliserait un professionnel RH au quotidien.
2. TERMINOLOGIE JURIDIQUE : reformulation enrichie avec les termes techniques \
du droit social français (notions clés, synonymes juridiques, concepts associés).
3. MOTS-CLÉS : 5-8 mots-clés et synonymes séparés par des espaces, couvrant \
les différentes interprétations possibles.

Règles :
- PAS de numéros d'articles de loi.
- Chaque variante sur une ligne précédée de son numéro (1. 2. 3.).
- Réponds UNIQUEMENT avec les 3 variantes, sans explication."""

_CONDENSE_PROMPT = """\
Étant donné l'historique de conversation suivant et une question de suivi, \
reformule la question de suivi en une question autonome et complète.

Règles :
- La question autonome doit être compréhensible SANS l'historique.
- Conserve les termes juridiques mentionnés dans l'historique.
- CONSERVE SYSTÉMATIQUEMENT le nom de l'organisation, la convention collective \
(CCN, IDCC) et tout contexte d'entreprise mentionné dans l'historique ou le \
contexte organisation. Ces éléments sont essentiels pour la recherche documentaire.
- Intègre les noms des sources déjà citées (documents, CCN, arrêts) dans la \
reformulation pour que la recherche les retrouve.
- Si la question introduit un nouveau sujet sans lien, retourne-la telle quelle.
- Réponds UNIQUEMENT avec la question reformulée."""


class RAGAgent:
    """Agent structuré pour la génération de réponses juridiques RH."""

    def __init__(self) -> None:
        self.search_engine = _search_engine
        self.llm = _llm
        self.reranker = get_reranker()
        # Cost tracking context — set by run()/prepare_context()
        self._org_id: str | None = None
        self._user_id: str | None = None
        self._conversation_id: str | None = None

    def _propagate_cost_context(self) -> None:
        """Push cost tracking context to search engine and reranker."""
        self.search_engine.set_cost_context(
            organisation_id=self._org_id,
            user_id=self._user_id,
            context_id=self._conversation_id,
        )
        self.reranker.set_cost_context(
            organisation_id=self._org_id,
            user_id=self._user_id,
            context_id=self._conversation_id,
        )

    async def run(
        self,
        query: str,
        organisation_id: str,
        org_context: dict[str, str | None] | None = None,
        history: list[dict[str, str]] | None = None,
        user_id: str | None = None,
        conversation_id: str | None = None,
    ) -> RAGResponse:
        """Execute the full RAG pipeline with global timeout."""
        self._org_id = organisation_id
        self._user_id = user_id
        self._conversation_id = conversation_id
        self._propagate_cost_context()
        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self._pipeline(query, organisation_id, org_context=org_context, history=history),
                timeout=RAG_TIMEOUT_GLOBAL,
            )
            logger.info(
                "[PERF] ══ RAG pipeline completed %.0fms",
                (time.perf_counter() - t0) * 1000,
            )
            return result
        except TimeoutError:
            logger.warning(
                "RAG pipeline timed out (%.0fs) for query: %s",
                RAG_TIMEOUT_GLOBAL, query[:100],
            )
            return RAGResponse(
                answer=(
                    "Désolé, le temps de traitement a été dépassé. "
                    "Veuillez reformuler votre question ou réessayer."
                ),
                sources=[],
                is_error=True,
            )
        except Exception as exc:
            logger.exception("RAG pipeline error for query: %s", query[:100])
            exc_str = str(exc).lower()
            if "insufficient_quota" in exc_str or "exceeded" in exc_str:
                msg = (
                    "Clé API OpenAI : quota dépassé ou crédits insuffisants. "
                    "Vérifiez votre compte OpenAI."
                )
            else:
                msg = (
                    "Une erreur est survenue lors du traitement "
                    "de votre question. Veuillez réessayer."
                )
            return RAGResponse(answer=msg, sources=[], is_error=True)

    async def _pipeline(
        self,
        query: str,
        organisation_id: str,
        org_context: dict[str, str | None] | None = None,
        history: list[dict[str, str]] | None = None,
        cited_sources: list[str] | None = None,
        org_idcc_list: list[str] | None = None,
    ) -> RAGResponse:
        # --- Step 0: Condensation (multi-turn) ---
        t0 = time.perf_counter()
        if history:
            query = await self._step_with_timeout(
                self._condense_question(
                    query, history,
                    org_context=org_context,
                    cited_sources=cited_sources,
                ),
                fallback=query,
            )
            logger.info(
                "[PERF] Step 0 — Condensation %.0fms | %s",
                (time.perf_counter() - t0) * 1000, query[:100],
            )

        # --- Step 1-2: Query expansion + parallel search + RRF ---
        results, _variants = await self._search_with_expansion(query, organisation_id, org_idcc_list=org_idcc_list)
        t2 = time.perf_counter()

        # --- Step 3: Cross-encoder reranking ---
        results = await self._step_with_timeout(
            self.reranker.rerank(query, results, top_k=RERANK_TOP_K),
            fallback=results[:RERANK_TOP_K],
        )
        t3 = time.perf_counter()
        logger.info(
            "[PERF] Step 3 — Reranking %.0fms | %d results",
            (t3 - t2) * 1000, len(results),
        )

        # --- Re-search if insufficient results ---
        iteration = 0
        while len(results) < 2 and iteration < RAG_MAX_ITERATIONS:
            iteration += 1
            logger.info("Step 2-3 — Re-search iteration %d", iteration)
            additional = await self._step_with_timeout(
                self.search_engine.search(
                    query, organisation_id, top_k=RERANK_TOP_K * 2,
                ),
                fallback=[],
            )
            seen = {(r.document_id, r.chunk_index) for r in results}
            for r in additional:
                if (r.document_id, r.chunk_index) not in seen:
                    results.append(r)
                    seen.add((r.document_id, r.chunk_index))
            results.sort(key=lambda r: r.score, reverse=True)
            results = results[:RERANK_TOP_K]

        if not results:
            return RAGResponse(
                answer=(
                    "Je n'ai pas trouvé de documents pertinents dans "
                    "votre base documentaire pour répondre à cette question. "
                    "Vérifiez que les documents nécessaires ont bien été "
                    "indexés dans votre organisation."
                ),
                sources=[],
            )

        # --- Step 4: Cross-references ---
        results = self._cross_reference(results)

        # --- Step 5: Hierarchy validation ---
        results = self._validate_hierarchy(results)

        # --- Step 6: Generation ---
        t_gen = time.perf_counter()
        answer = await self._step_with_timeout(
            self._generate(query, results, org_context=org_context),
            fallback=self._fallback_answer(results),
        )
        logger.info(
            "[PERF] Step 6 — LLM generation %.0fms | %d chars",
            (time.perf_counter() - t_gen) * 1000, len(answer),
        )

        # --- Step 7: Format sources ---
        sources = self._format_sources(results)

        return RAGResponse(answer=answer, sources=sources)

    # --- Streaming support ---

    async def prepare_context(
        self,
        query: str,
        organisation_id: str,
        org_context: dict[str, str | None] | None = None,
        history: list[dict[str, str]] | None = None,
        cited_sources: list[str] | None = None,
        org_idcc_list: list[str] | None = None,
        user_id: str | None = None,
        conversation_id: str | None = None,
    ) -> tuple[list[SearchResult], str]:
        """Run steps 0-5 (non-streaming) and return results + reformulated query."""
        self._org_id = organisation_id
        self._user_id = user_id
        self._conversation_id = conversation_id
        self._propagate_cost_context()
        t0 = time.perf_counter()

        # Step 0: Condensation (multi-turn)
        if history:
            query = await self._step_with_timeout(
                self._condense_question(
                    query, history,
                    org_context=org_context,
                    cited_sources=cited_sources,
                ),
                fallback=query,
            )
            logger.info(
                "[PERF] Step 0 — Condensation %.0fms | %s",
                (time.perf_counter() - t0) * 1000, query[:100],
            )

        # Step 1-2: Query expansion + parallel search + RRF
        results, variants = await self._search_with_expansion(query, organisation_id, org_idcc_list=org_idcc_list)
        reformulated = variants[0] if variants else query
        t2 = time.perf_counter()

        # Step 3: Reranking
        results = await self._step_with_timeout(
            self.reranker.rerank(query, results, top_k=RERANK_TOP_K),
            fallback=results[:RERANK_TOP_K],
        )
        t_rerank = time.perf_counter()
        logger.info(
            "[PERF] Step 3 — Reranking %.0fms | %d results",
            (t_rerank - t2) * 1000, len(results),
        )

        iteration = 0
        while len(results) < 2 and iteration < RAG_MAX_ITERATIONS:
            iteration += 1
            t_re = time.perf_counter()
            logger.info("[PERF] Step 2-3 — Re-search iteration %d", iteration)
            additional = await self._step_with_timeout(
                self.search_engine.search(
                    query, organisation_id, top_k=RERANK_TOP_K * 2,
                ),
                fallback=[],
            )
            seen = {(r.document_id, r.chunk_index) for r in results}
            for r in additional:
                if (r.document_id, r.chunk_index) not in seen:
                    results.append(r)
                    seen.add((r.document_id, r.chunk_index))
            results.sort(key=lambda r: r.score, reverse=True)
            results = results[:RERANK_TOP_K]
            logger.info(
                "[PERF] Step 2-3 — Re-search iteration %d %.0fms | now %d results",
                iteration, (time.perf_counter() - t_re) * 1000, len(results),
            )

        t3 = time.perf_counter()
        results = self._cross_reference(results)
        results = self._validate_hierarchy(results)
        logger.info(
            "[PERF] Step 4-5 — Cross-ref + hierarchy %.0fms",
            (time.perf_counter() - t3) * 1000,
        )

        total = (time.perf_counter() - t0) * 1000
        logger.info(
            "[PERF] ══ Context ready %.0fms | %d results",
            total, len(results),
        )
        return results, reformulated

    async def stream_generate(
        self,
        query: str,
        results: list[SearchResult],
        org_context: dict[str, str | None] | None = None,
        buffer_size: int = 10,
    ) -> AsyncGenerator[str, None]:
        """Stream the LLM generation token by token (buffered)."""
        t_start = time.perf_counter()
        context = self._build_context(results)
        user_content = self._build_user_message(query, context, org_context)
        logger.info(
            "[RAG] stream org_context injected: %s",
            org_context if org_context else "None",
        )

        t_api = time.perf_counter()
        response = await self.llm.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_completion_tokens=16000,
            reasoning_effort="low",
            stream=True,
            stream_options={"include_usage": True},
        )
        logger.info(
            "[PERF] Step 6 — LLM stream opened %.0fms",
            (time.perf_counter() - t_api) * 1000,
        )

        token_buffer: list[str] = []
        first_token_logged = False
        total_tokens = 0
        stream_usage = None
        async for chunk in response:
            # Capture usage from the final chunk (stream_options.include_usage)
            if chunk.usage is not None:
                stream_usage = chunk.usage
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta.content:
                    if not first_token_logged:
                        logger.info(
                            "[PERF] Step 6 — First token %.0fms",
                            (time.perf_counter() - t_start) * 1000,
                        )
                        first_token_logged = True
                    total_tokens += 1
                    token_buffer.append(delta.content)
                    if len(token_buffer) >= buffer_size:
                        yield "".join(token_buffer)
                        token_buffer = []

        # Flush remaining buffer
        if token_buffer:
            yield "".join(token_buffer)

        # Log cost from stream usage
        if stream_usage:
            await cost_tracker.log(
                provider="openai",
                model=LLM_MODEL,
                operation_type="generate",
                tokens_input=stream_usage.prompt_tokens,
                tokens_output=stream_usage.completion_tokens,
                organisation_id=self._org_id,
                user_id=self._user_id,
                context_type="question",
                context_id=self._conversation_id,
            )

        logger.info(
            "[PERF] Step 6 — LLM streaming done %.0fms | %d token chunks",
            (time.perf_counter() - t_start) * 1000, total_tokens,
        )

    def format_sources(self, results: list[SearchResult]) -> list[RAGSource]:
        """Public wrapper for _format_sources."""
        return self._format_sources(results)

    # --- Step implementations ---

    async def _condense_question(
        self,
        query: str,
        history: list[dict[str, str]],
        org_context: dict[str, str | None] | None = None,
        cited_sources: list[str] | None = None,
    ) -> str:
        """Step 0: Condense a follow-up question using conversation history."""
        recent = history[-CONDENSE_HISTORY_LIMIT:]
        history_lines: list[str] = []
        for msg in recent:
            role_label = "Utilisateur" if msg["role"] == "user" else "Assistant"
            content = msg["content"][:500]
            history_lines.append(f"{role_label}: {content}")
        history_text = "\n".join(history_lines)

        # Build context block with org info and cited sources
        context_parts: list[str] = []
        if org_context:
            org_info = []
            if org_context.get("nom"):
                org_info.append(f"Organisation : {org_context['nom']}")
            if org_context.get("convention_collective"):
                org_info.append(f"Convention collective : {org_context['convention_collective']}")
            if org_context.get("secteur_activite"):
                org_info.append(f"Secteur : {org_context['secteur_activite']}")
            if org_info:
                context_parts.append("Contexte organisation :\n" + "\n".join(org_info))
        if cited_sources:
            context_parts.append("Sources déjà citées : " + ", ".join(cited_sources))

        user_content = f"Historique :\n{history_text}\n\n"
        if context_parts:
            user_content += "\n".join(context_parts) + "\n\n"
        user_content += f"Question de suivi : {query}"

        response = await self.llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _CONDENSE_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            max_tokens=300,
        )
        if response.usage:
            await cost_tracker.log(
                provider="openai",
                model="gpt-4o-mini",
                operation_type="condense",
                tokens_input=response.usage.prompt_tokens,
                tokens_output=response.usage.completion_tokens,
                organisation_id=self._org_id,
                user_id=self._user_id,
                context_type="question",
                context_id=self._conversation_id,
            )
        return response.choices[0].message.content or query

    async def _expand_queries(self, query: str) -> list[str]:
        """Step 1: Expand the user query into 3 search variants."""
        response = await self.llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _QUERY_EXPAND_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.3,
            max_tokens=400,
        )
        if response.usage:
            await cost_tracker.log(
                provider="openai",
                model="gpt-4o-mini",
                operation_type="expand",
                tokens_input=response.usage.prompt_tokens,
                tokens_output=response.usage.completion_tokens,
                organisation_id=self._org_id,
                user_id=self._user_id,
                context_type="question",
                context_id=self._conversation_id,
            )
        content = response.choices[0].message.content or ""
        return self._parse_variants(content, query)

    @staticmethod
    def _parse_variants(content: str, original_query: str) -> list[str]:
        """Parse numbered variants from LLM response."""
        variants: list[str] = []
        for line in content.strip().split("\n"):
            line = line.strip()
            # Match lines starting with "1.", "2.", "3." (with optional space/dash after)
            match = re.match(r"^\d+[\.\)]\s*[-–—]?\s*(.+)$", line)
            if match:
                variant = match.group(1).strip()
                if variant:
                    variants.append(variant)

        if not variants:
            return [original_query]
        return variants

    @staticmethod
    def _reciprocal_rank_fusion(
        result_lists: list[list[SearchResult]],
        k: int = 60,
    ) -> list[SearchResult]:
        """Fuse multiple ranked lists using Reciprocal Rank Fusion."""
        scores: dict[tuple[str, int], float] = {}
        result_map: dict[tuple[str, int], SearchResult] = {}

        for result_list in result_lists:
            for rank, result in enumerate(result_list):
                key = (result.document_id, result.chunk_index)
                scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
                if key not in result_map:
                    result_map[key] = result

        # Update scores and sort
        fused: list[SearchResult] = []
        for key, rrf_score in scores.items():
            result = result_map[key]
            result.score = rrf_score
            fused.append(result)

        fused.sort(key=lambda r: r.score, reverse=True)
        return fused

    async def _search_with_expansion(
        self,
        query: str,
        organisation_id: str,
        org_idcc_list: list[str] | None = None,
    ) -> tuple[list[SearchResult], list[str]]:
        """Expand query into variants, search in parallel, fuse with RRF."""
        t0 = time.perf_counter()

        variants = await self._step_with_timeout(
            self._expand_queries(query),
            fallback=[query],
        )
        t1 = time.perf_counter()
        logger.info(
            "[PERF] Step 1 — Query expansion %.0fms | %d variants: %s",
            (t1 - t0) * 1000,
            len(variants),
            " | ".join(v[:60] for v in variants),
        )

        # Search all variants in parallel
        search_tasks = [
            self.search_engine.search(
                variant, organisation_id, top_k=TOP_K,
                org_idcc_list=org_idcc_list,
            )
            for variant in variants
        ]
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        # Filter out errors
        valid_results: list[list[SearchResult]] = []
        for i, result in enumerate(search_results):
            if isinstance(result, Exception):
                logger.warning(
                    "Search failed for variant %d: %s", i, result,
                )
            else:
                valid_results.append(result)

        t2 = time.perf_counter()
        logger.info(
            "[PERF] Step 2 — Parallel search ×%d %.0fms | %s results per variant",
            len(variants),
            (t2 - t1) * 1000,
            ", ".join(str(len(r)) for r in valid_results),
        )

        if not valid_results:
            return [], variants

        # Fuse results with RRF
        fused = self._reciprocal_rank_fusion(valid_results)
        return fused[:TOP_K], variants

    def _cross_reference(self, results: list[SearchResult]) -> list[SearchResult]:
        """Step 4: Boost documents cited multiple times."""
        doc_counts: dict[str, int] = {}
        for r in results:
            doc_counts[r.document_id] = doc_counts.get(r.document_id, 0) + 1

        for r in results:
            count = doc_counts.get(r.document_id, 1)
            if count > 1:
                r.score *= 1.0 + 0.05 * (count - 1)

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _validate_hierarchy(self, results: list[SearchResult]) -> list[SearchResult]:
        """Step 5: Ensure higher-level norms take precedence."""
        if len(results) < 2:
            return results

        by_level: dict[int, list[SearchResult]] = {}
        for r in results:
            by_level.setdefault(r.norme_niveau, []).append(r)

        if len(by_level) > 1:
            min_level = min(by_level.keys())
            for r in results:
                if r.norme_niveau == min_level:
                    r.score *= 1.15

        results.sort(key=lambda r: (-r.score, r.norme_niveau))
        return results

    def _build_context(self, results: list[SearchResult]) -> str:
        """Build context string from search results."""
        context_parts: list[str] = []
        for i, r in enumerate(results, 1):
            type_info = DOCUMENT_TYPE_HIERARCHY.get(r.source_type, {})
            niveau = type_info.get("niveau", "?")
            label = _SOURCE_TYPE_LABELS.get(r.source_type, r.source_type)

            header = (
                f"[Source {i}]\n"
                f"Document : {r.doc_name}\n"
                f"Type : {label} (niveau hiérarchique {niveau}/9 — "
                f"{'norme supérieure' if isinstance(niveau, int) and niveau <= 4 else 'norme inférieure'})\n"
            )

            # Add jurisprudence metadata when available
            if r.numero_pourvoi or r.date_decision:
                juris_parts: list[str] = []
                if r.juridiction:
                    j = r.juridiction
                    if r.chambre:
                        j = f"{j} {r.chambre}"
                    juris_parts.append(j)
                if r.date_decision:
                    juris_parts.append(r.date_decision)
                if r.numero_pourvoi:
                    juris_parts.append(f"n° {r.numero_pourvoi}")
                if r.solution:
                    juris_parts.append(r.solution)
                if r.publication:
                    juris_parts.append(f"({r.publication})")
                header += f"Référence : {', '.join(juris_parts)}\n"

            header += f"Contenu :\n{r.text}"
            context_parts.append(header)

        return "\n\n---\n\n".join(context_parts)

    _PROFIL_METIER_LABELS: dict[str, str] = {
        "drh": "DRH / Responsable RH",
        "charge_rh": "Chargé(e) RH / Assistant(e) RH",
        "elu_cse": "Élu(e) CSE / Délégué(e) du personnel",
        "dirigeant": "Dirigeant / Gérant",
        "juriste": "Juriste d'entreprise",
        "consultant_rh": "Consultant RH / Cabinet RH",
    }

    _PROFIL_METIER_INSTRUCTIONS: dict[str, str] = {
        "drh": (
            "L'utilisateur est DRH/Responsable RH : réponds du point de vue employeur, "
            "avec les procédures à suivre, les risques juridiques et les délais à respecter."
        ),
        "charge_rh": (
            "L'utilisateur est chargé(e)/assistant(e) RH : réponds de manière opérationnelle, "
            "avec les étapes concrètes, les modèles de courriers si pertinent, et les points de vigilance."
        ),
        "elu_cse": (
            "L'utilisateur est élu(e) CSE / représentant du personnel : réponds du point de vue "
            "des droits des salariés et des prérogatives du CSE, en précisant les obligations de "
            "l'employeur, les consultations obligatoires et les leviers d'action du CSE."
        ),
        "dirigeant": (
            "L'utilisateur est dirigeant/gérant (souvent TPE-PME sans service RH) : réponds "
            "de manière simple et directe, sans jargon excessif, avec les obligations essentielles "
            "et les risques concrets en cas de non-respect."
        ),
        "juriste": (
            "L'utilisateur est juriste d'entreprise : réponds avec précision juridique, "
            "en citant les références exactes (articles, jurisprudence) et les nuances d'interprétation."
        ),
        "consultant_rh": (
            "L'utilisateur est consultant RH / cabinet RH : réponds avec un niveau d'expertise élevé, "
            "en couvrant les différents cas de figure et les recommandations à formuler à ses clients."
        ),
    }

    def _build_org_context_block(self, org_context: dict[str, str | None]) -> str:
        """Build an organisation context block for the LLM prompt."""
        nom = org_context.get("nom") or "l'entreprise"
        profil = org_context.get("profil_metier")

        lines = [f"## Entreprise de l'utilisateur : {nom}\n"]

        # Profil métier
        if profil and profil in self._PROFIL_METIER_LABELS:
            lines.append(f"**Profil de l'utilisateur** : {self._PROFIL_METIER_LABELS[profil]}")
            lines.append(self._PROFIL_METIER_INSTRUCTIONS[profil] + "\n")
        else:
            lines.append(
                "L'utilisateur travaille dans cette entreprise. "
                "Adapte systématiquement tes réponses à ce contexte "
                "(seuils d'effectifs, obligations légales, dispositions conventionnelles).\n"
            )

        field_labels = {
            "forme_juridique": "Forme juridique",
            "taille": "Effectif",
            "convention_collective": "Convention collective",
            "secteur_activite": "Secteur d'activité / code APE",
        }
        for key, label in field_labels.items():
            value = org_context.get(key)
            if value:
                if key == "taille":
                    lines.append(f"- {label} : {value} salariés")
                else:
                    lines.append(f"- {label} : {value}")
        return "\n".join(lines)

    def _build_user_message(
        self,
        query: str,
        context: str,
        org_context: dict[str, str | None] | None = None,
    ) -> str:
        """Build the user message with sources, optional org context, and question."""
        parts = [f"Sources documentaires :\n\n{context}"]
        if org_context and any(org_context.values()):
            parts.append(self._build_org_context_block(org_context))
        parts.append(f"Question : {query}")
        return "\n\n".join(parts)

    async def _generate(
        self,
        query: str,
        results: list[SearchResult],
        org_context: dict[str, str | None] | None = None,
    ) -> str:
        """Step 6: Generate the answer using the LLM with retrieved context."""
        context = self._build_context(results)
        user_content = self._build_user_message(query, context, org_context)
        logger.info(
            "[RAG] org_context injected: %s",
            org_context if org_context else "None",
        )

        response = await self.llm.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_completion_tokens=16000,
            reasoning_effort="low",
        )
        if response.usage:
            await cost_tracker.log(
                provider="openai",
                model=LLM_MODEL,
                operation_type="generate",
                tokens_input=response.usage.prompt_tokens,
                tokens_output=response.usage.completion_tokens,
                organisation_id=self._org_id,
                user_id=self._user_id,
                context_type="question",
                context_id=self._conversation_id,
            )
        return response.choices[0].message.content or ""

    def _format_sources(self, results: list[SearchResult]) -> list[RAGSource]:
        """Step 7: Format search results into source references."""
        doc_chunks: dict[str, list[str]] = {}
        doc_meta: dict[str, SearchResult] = {}

        for r in results:
            if r.document_id not in doc_meta:
                doc_meta[r.document_id] = r
                doc_chunks[r.document_id] = []
            doc_chunks[r.document_id].append(r.text)

        sources: list[RAGSource] = []
        for doc_id, meta in doc_meta.items():
            chunks = doc_chunks[doc_id]
            full_text = "\n\n".join(chunks)

            excerpt = chunks[0][:300].strip()
            if len(chunks[0]) > 300:
                excerpt = excerpt.rsplit(" ", 1)[0] + "…"

            sources.append(
                RAGSource(
                    document_name=meta.doc_name,
                    source_type=meta.source_type,
                    source_type_label=_SOURCE_TYPE_LABELS.get(
                        meta.source_type, meta.source_type,
                    ),
                    norme_niveau=meta.norme_niveau,
                    excerpt=excerpt,
                    full_text=full_text,
                    juridiction=meta.juridiction,
                    chambre=meta.chambre,
                    formation=meta.formation,
                    numero_pourvoi=meta.numero_pourvoi,
                    date_decision=meta.date_decision,
                    solution=meta.solution,
                    publication=meta.publication,
                )
            )

        return sources

    def _fallback_answer(self, results: list[SearchResult]) -> str:
        """Generate a simple fallback answer if LLM call times out."""
        doc_names = list({r.doc_name for r in results[:3]})
        refs = ", ".join(doc_names)
        return (
            "J'ai trouvé des éléments pertinents dans les documents "
            f"suivants : {refs}. Cependant, la génération de la réponse "
            "détaillée a pris trop de temps. Veuillez réessayer."
        )

    async def _step_with_timeout(self, coro, fallback):
        """Run a coroutine with per-step timeout, returning fallback on error."""
        try:
            return await asyncio.wait_for(coro, timeout=RAG_TIMEOUT_PER_STEP)
        except TimeoutError:
            logger.warning(
                "Step timed out (%.0fs), using fallback", RAG_TIMEOUT_PER_STEP,
            )
            return fallback
        except Exception:
            logger.exception("Step failed, using fallback")
            return fallback
