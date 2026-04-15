import asyncio
import logging
import re
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import httpx
from openai import AsyncOpenAI

from app.core.config import settings
import app.rag.config as rag_config
from app.rag.config import (
    CONDENSE_HISTORY_LIMIT,
    RAG_MAX_ITERATIONS,
    RAG_TIMEOUT_GLOBAL,
    RAG_TIMEOUT_PER_STEP,
    RERANK_TOP_K,
    TOP_K,
)
from app.rag.norme_hierarchy import DOCUMENT_TYPE_HIERARCHY
from app.rag.parent_expansion import (
    detect_identifiers,
    expand_to_parents,
    fetch_by_identifiers,
)
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

    document_id: str
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
    # Structural metadata (optional, from ArticleChunker)
    article_nums: list[str] | None = None
    section_path: str | None = None


@dataclass
class RAGResponse:
    """The final response from the RAG agent."""

    answer: str
    sources: list[RAGSource]
    is_error: bool = False


@dataclass
class RagTrace:
    """Lightweight trace of one RAG pipeline execution.

    Captured during prepare_context / stream_generate and persisted as JSONB
    on the assistant Message. Used by the admin Quality page to inspect any
    past question. Sized to stay under ~15 KB per trace.
    """

    query_original: str = ""
    query_condensed: str | None = None
    variants: list[str] = field(default_factory=list)
    identifiers_detected: dict = field(default_factory=dict)
    boost_injected: int = 0
    # True when an identifier (article, pourvoi) was found in the query but
    # the boost matched 0 chunks. Strong signal of a potential hallucination
    # because the LLM context likely doesn't contain the requested identifier.
    identifier_no_match: bool = False
    # Each chunk = {document_id, doc_name, chunk_index, score, source_type, text_preview}
    hybrid_results: list[dict] = field(default_factory=list)
    rerank_results: list[dict] = field(default_factory=list)
    parent_groups: list[dict] = field(default_factory=list)
    perf_ms: dict[str, float] = field(default_factory=dict)
    model: str | None = None
    out_of_scope: bool = False
    no_results: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "query_original": self.query_original,
            "query_condensed": self.query_condensed,
            "variants": self.variants,
            "identifiers_detected": self.identifiers_detected,
            "boost_injected": self.boost_injected,
            "identifier_no_match": self.identifier_no_match,
            "hybrid_results": self.hybrid_results,
            "rerank_results": self.rerank_results,
            "parent_groups": self.parent_groups,
            "perf_ms": self.perf_ms,
            "model": self.model,
            "out_of_scope": self.out_of_scope,
            "no_results": self.no_results,
            "error": self.error,
        }


def _serialize_chunks(results: list, limit: int = 30, text_chars: int = 250) -> list[dict]:
    """Serialize a list of SearchResult into a compact dict for the trace."""
    out: list[dict] = []
    for r in results[:limit]:
        out.append({
            "document_id": r.document_id,
            "doc_name": (r.doc_name or "")[:120],
            "chunk_index": r.chunk_index,
            "score": round(float(r.score), 4),
            "source_type": r.source_type,
            "text_preview": (r.text or "")[:text_chars],
        })
    return out


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

_OUT_OF_SCOPE_MARKER = "[HORS_SCOPE]"
_OUT_OF_SCOPE_ANSWER = (
    "Je suis spécialisé en droit social et ressources humaines. "
    "Je ne peux pas répondre à cette question. N'hésitez pas à me poser "
    "une question sur le droit du travail, la gestion RH, la paie, les "
    "relations sociales, la formation professionnelle, ou tout autre sujet "
    "lié à la vie en entreprise."
)

_SYSTEM_PROMPT = """\
Tu es un DRH expérimenté en droit social français. Tu parles à des professionnels \
RH qui veulent des réponses pratiques, complètes et actionnables. \
Ton rôle : les aider à **sécuriser leurs décisions**, pas à leur faire un cours de droit.

## MÉTHODE (applique dans cet ordre, mentalement)

1. **Analyse les sources** : identifie celles qui répondent directement. Ignore le reste.
2. **Identifie le contexte utilisateur** : sa CCN (IDCC), son secteur, sa situation. \
Applique la réponse à SON cas, pas en général.
3. **Si la question décrit une situation avec plusieurs faits** (ex: arrêt maladie + \
courrier + CSE + inaptitude), relie-les dans un **raisonnement d'ensemble**. \
Montre la chaîne causale et ses conséquences juridiques. Ne traite PAS chaque fait \
dans un silo séparé.
4. **Si la question porte sur un risque ou une situation contentieuse**, identifie \
d'abord LE **risque principal** (celui qui pèse le plus lourd juridiquement), puis \
les risques secondaires. Ne liste pas 10 risques au même niveau.
5. **Construis la réponse** selon cette checklist :
   - Règle de principe (Code du travail)
   - Règle conventionnelle (sa CCN si applicable)
   - **Sources internes** : vérifie SYSTÉMATIQUEMENT si un accord d'entreprise, \
règlement intérieur, DUE ou usage interne présent dans les sources prévoit \
des dispositions différentes (plus favorables ou spécifiques). Si oui, mentionne-le. \
Si aucune source interne ne déroge, indique-le brièvement \
(ex: "Aucun accord d'entreprise ne prévoit de disposition différente dans vos sources.").
   - Chiffres concrets (montants, délais, seuils)
   - Exceptions et cas particuliers importants
   - Point d'attention pratique pour l'employeur
6. **Choisis le format** adapté à l'intention :

| Intention | Format |
|---|---|
| Définition ("c'est quoi") | Phrase directe + exemple. Court. |
| Factuel ("quel délai", "combien") | **Tableau** si plusieurs cas. |
| Comparaison ("différence entre") | **Tableau comparatif**. |
| Procédure ("comment faire") | **Liste numérotée** avec délais. |
| Oui/non EXPLICITE ("ai-je le droit de", "est-ce légal de") | **Oui** ou **Non** d'abord. Ne PAS forcer un Oui/Non si la question n'en appelle pas un. |
| Pratique RH (congés, indemnités…) | Complet : principe + CCN + exceptions + conseil. |
| Situation à risque ("est-ce que l'employeur prend un risque", "peut-il aller aux prud'hommes") | **Risque principal** d'abord (en gras), puis risques secondaires. Chaîne causale si plusieurs faits. Position claire. |

## RÈGLES JURIDIQUES

- **Articulation loi / CCN / accord** : depuis 2017, certaines règles légales \
sont d'ordre public (incompressibles), d'autres sont supplétives (la CCN ou \
l'accord peut y déroger). Vérifie dans les sources si la règle est dérogeable \
avant de conclure quelle norme s'applique.
- **Hiérarchie** : Loi > Jurisprudence > CCN > Accord d'entreprise > \
Engagement unilatéral (DUE) > Usage > Contrat.
- **Respecte le type de chaque source** : chaque source porte un champ "Type" \
(accord d'entreprise, engagement unilatéral, convention collective, règlement \
intérieur, arrêt de jurisprudence, etc.). Ces types ont des natures juridiques \
différentes. Ne les confonds JAMAIS. Quand l'utilisateur demande "nos accords \
d'entreprise", ne lui cite que les sources de type "Accord d'entreprise" — pas \
les DUE, pas le règlement intérieur, pas la CCN. Et inversement pour chaque type.
- **RÉCENCE — RÈGLE CRITIQUE** : quand plusieurs textes (avenants, accords, \
grilles) fixent une valeur différente pour la même chose (salaire, indemnité, \
valeur du point, coefficient, durée), retiens TOUJOURS celui dont la **date \
d'effet est la plus récente**. Un avenant de 2021 remplace un avenant de 2017 \
sur le même sujet. Ne cite PAS les valeurs obsolètes sauf pour contexte historique.
- **Jurisprudence** = interprète la loi, ne la remplace pas. Cite avec \
référence complète (Cass. soc., date, n° pourvoi). Privilégie le plus récent.
- **Anti-hallucination** : appuie-toi sur les sources fournies. N'invente PAS \
d'articles, de chiffres ou de jurisprudence. En revanche, si les sources ne couvrent \
pas un aspect, tu peux donner la règle générale de droit du travail que tu connais \
en le signalant brièvement UNE SEULE FOIS en fin de réponse — pas à chaque paragraphe. \
Ne JAMAIS écrire "vos sources ne couvrent pas" ou "vos sources ne permettent pas" \
de façon répétée : le RH attend une position claire, pas des hésitations.

## LISIBILITÉ

- Commence par la réponse directe. Pas de préambule, pas de label \
("Réponse directe :", "Règle de principe :" etc.). Écris naturellement.
- **Paragraphes : 3-4 lignes max.** Phrases courtes.
- **Gras** sur chiffres, délais, montants, mots clés.
- **Tableaux** dès qu'il y a des cas, barèmes ou comparaisons.
- **Items de liste : 1-2 lignes.** Pas de pavé dans une puce.
- **Cite les références légales dans le texte** : articles de loi (art. L.1234-1), \
articles de CCN (art. 33 CCNT66), jurisprudence (Cass. soc., date, n° pourvoi). \
Le RH doit pouvoir copier-coller ta réponse avec ses fondements juridiques. \
En revanche, ne cite PAS les noms des documents sources (affichés séparément dans l'UI). \
Français uniquement.
- **JAMAIS** de "Souhaitez-vous que je…", "Je peux aussi…", "N'hésitez pas…".
- **Termine par 2-3 questions complémentaires** sous ce format exact :

→ *Question pertinente 1 ?*
→ *Question pertinente 2 ?*

## EXEMPLES

Q : "quel est le délai de préavis pour un licenciement"

Le préavis dépend de l'ancienneté (**art. L.1234-1 Code du travail**) :

| Ancienneté | Préavis légal |
|---|---|
| < 6 mois | Selon CCN, contrat ou usage |
| 6 mois à 2 ans | **1 mois** |
| ≥ 2 ans | **2 mois** |

**Dans votre CCN** (IDCC 0413), l'article 16 prévoit les mêmes durées. \
Si votre CCN prévoyait plus long, c'est elle qui s'appliquerait.

**Exceptions** : pas de préavis en cas de faute grave/lourde ou d'inaptitude. \
En cas de dispense par l'employeur, le salaire reste dû pendant la durée du préavis.

→ *Quelle indemnité compensatrice si le préavis n'est pas exécuté ?*
→ *Le salarié peut-il demander à ne pas effectuer son préavis ?*

---

Q : "Quelle est la durée des congés payés selon l'ancienneté"

Tout salarié acquiert **2,5 jours ouvrables par mois** de travail effectif, \
soit **30 jours (5 semaines) par an** (art. L.3141-3 Code du travail).

**Majoration conventionnelle** (CCN IDCC 0413) :

| Ancienneté | Congés annuels |
|---|---|
| < 5 ans | **30 jours** (base légale) |
| 5 à 9 ans | **32 jours** (+2) |
| 10 à 14 ans | **34 jours** (+4) |
| ≥ 15 ans | **36 jours** (+6 max) |

**Congés supplémentaires** : fractionnement (1-2 jours si prise hors \
période légale 1er mai–31 oct.), congés événements familiaux (mariage, \
naissance, décès — durées fixées par la CCN).

**Points d'attention** : les absences maladie ne font pas perdre de droits \
à congés (jurisprudence récente). La période de référence court du \
1er juin au 31 mai.

⚠️ Vérifiez si un accord d'entreprise prévoit des dispositions plus favorables.

→ *Comment calculer l'indemnité compensatrice de congés payés ?*
→ *Quelles sont les règles de report en cas de maladie ?*
→ *Quels sont les congés pour événements familiaux dans ma CCN ?*"""

_QUERY_EXPAND_PROMPT = """\
Tu es un expert RH spécialisé en droit social français. Ta mission : transformer \
la question d'un utilisateur en 5 variantes de recherche pour maximiser la \
récupération des articles pertinents (Code du travail, CCN, jurisprudence, \
règlement intérieur, contrats).

## Règle absolue — anti-hallucination juridique
N'introduis JAMAIS un concept juridique qui n'est pas dans la question d'origine. \
Ne confonds pas :
- prescription ≠ forclusion ≠ déchéance
- licenciement ≠ rupture conventionnelle ≠ démission ≠ résiliation judiciaire
- indemnité ≠ dommages-intérêts ≠ allocation
- préavis ≠ période d'essai ≠ délai de réflexion
- CDI ≠ CDD ≠ intérim ≠ contrat de chantier
- congé ≠ absence ≠ suspension du contrat
En l'absence de synonyme direct et sûr, RÉPÈTE le terme d'origine.

## Génère exactement 5 variantes, numérotées 1. à 5.

1. QUESTION CORRIGÉE : la question de l'utilisateur, avec uniquement les fautes \
d'orthographe et de frappe évidentes corrigées. Ne reformule pas, ne change pas \
le vocabulaire, ne résume pas. Préserve tels quels les identifiants (articles, \
numéros de pourvoi, IDCC).

2. INTENTION RH : reformulation selon ce que cherche un praticien RH au \
quotidien. Désambiguïse les termes courants du métier. Ex: "c'est quoi \
collectif obligatoire" → régime de mutuelle/prévoyance d'entreprise à \
adhésion obligatoire (PAS des négociations collectives). Pas d'identifiants.

3. TERMINOLOGIE JURIDIQUE : reformulation avec les termes techniques du droit \
social français — UNIQUEMENT des synonymes directs et sûrs du vocabulaire de \
la question. N'ajoute pas de concept voisin ni de notion associée. Pas d'identifiants.

Si la question contient un des termes ci-dessous, intègre SON ÉQUIVALENT \
CONVENTIONNEL ANCIEN (utilisé dans les CCN rédigées avant 1980, comme la CCN 66) :
- préavis ↔ délai-congé
- prescription disciplinaire ↔ annulation de sanction, effacement de sanction
- indemnité de licenciement ↔ indemnité conventionnelle de rupture
- congés payés ↔ congés annuels
- salaire ↔ appointements (cadres) / rémunération conventionnelle
- période d'essai ↔ essai probatoire, essai
- rupture du contrat ↔ cessation d'emploi, fin des fonctions
- promotion ↔ avancement
- sanction disciplinaire ↔ mesure disciplinaire (observation, avertissement, mise à pied, licenciement)

Règle stricte : n'ajoute AUCUN autre synonyme que ceux listés ci-dessus. Si le \
terme n'est pas dans la liste, conserve le vocabulaire d'origine.

4. MOTS-CLÉS : 5-8 mots-clés séparés par des espaces, composés des mots de la \
question et de leurs synonymes directs. Pas de concepts associés, pas de termes \
juridiques voisins. Si la question contient un identifiant (ex: "L4121-1", \
"22-18.875"), INCLUS-LE TEL QUEL.

5. VARIANTE CCN : Si le bloc [ORGANISATION] du message utilisateur indique \
une CCN rattachée (ligne "- CCN rattachée : ..."), génère SYSTÉMATIQUEMENT \
une variante au format suivant :
   <IDCC extrait entre parenthèses> convention collective <mots-clés du sujet>
   Exemples :
   - CCN = "CCN Handicapés (IDCC 0413)" + question = "délai de préavis" \
→ "IDCC 0413 convention collective délai préavis"
   - CCN = "Syntec (IDCC 1486)" + question = "télétravail" \
→ "IDCC 1486 convention collective télétravail"
   Si aucune CCN n'est rattachée (bloc [ORGANISATION] absent ou sans ligne \
"- CCN rattachée"), répète la variante 1 à l'identique.

## Format de sortie
- Chaque variante sur une ligne, précédée de son numéro (1. 2. 3. 4. 5.)
- Aucune explication, aucun préambule"""

_CONDENSE_PROMPT = """\
Tu reformules une question de suivi en question autonome et complète.

Méthode :
1. Lis l'historique et identifie le SUJET EN COURS (ex: mutation, licenciement, \
congés) et la SITUATION FACTUELLE accumulée (type de contrat, statut du salarié, \
CCN, ce qui a été décidé/proposé dans les échanges précédents).
2. Lis les CONCLUSIONS de l'assistant dans les réponses précédentes — elles \
contiennent des faits établis (ex: "le site ferme", "salarié protégé", \
"autorisation de l'inspection du travail nécessaire").
3. Reformule la question de suivi en intégrant TOUT ce contexte.

Exemple :
- Q1: "Un salarié refuse sa mutation, quelles options ?"
- R1: (explique les cas, salarié protégé, modification du contrat...)
- Q2: "Le site ferme, je peux le licencier ?"
- R2: (oui avec autorisation, obligation de reclassement...)
- Q3: "Je n'ai qu'un seul poste, c'est un élu CSE"
- → Reformulation : "Dans le cas d'une fermeture de site avec un élu CSE \
qui refuse sa mutation, l'employeur ne peut proposer qu'un seul poste de \
reclassement correspondant à ses fonctions actuelles. Quelles sont les options \
et la procédure (autorisation inspection du travail) ?"

Règles :
- La question reformulée doit être compréhensible SANS l'historique.
- RÉSOUS les références pronominales et démonstratifs : "cet accord", "ce texte", \
"cette convention", "ce salarié", "cette procédure" → remplace par le nom exact \
du document, de l'accord ou du sujet identifié dans l'historique ou les sources citées. \
C'est CRITIQUE pour que la recherche trouve le bon document.
- CONSERVE : organisation, CCN/IDCC, statut salarié, type contrat, situation factuelle.
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
        self._is_replay: bool = False

    def _propagate_cost_context(self) -> None:
        """Push cost tracking context to search engine and reranker."""
        self.search_engine.set_cost_context(
            organisation_id=self._org_id,
            user_id=self._user_id,
            context_id=self._conversation_id,
            is_replay=self._is_replay,
        )
        self.reranker.set_cost_context(
            organisation_id=self._org_id,
            user_id=self._user_id,
            context_id=self._conversation_id,
            is_replay=self._is_replay,
        )

    async def run(
        self,
        query: str,
        organisation_id: str,
        org_context: dict[str, str | None] | None = None,
        history: list[dict[str, str]] | None = None,
        user_id: str | None = None,
        conversation_id: str | None = None,
        is_replay: bool = False,
    ) -> RAGResponse:
        """Execute the full RAG pipeline with global timeout."""
        self._org_id = organisation_id
        self._user_id = user_id
        self._conversation_id = conversation_id
        self._is_replay = is_replay
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
            return RAGResponse(
                answer=(
                    "Une erreur est survenue lors du traitement "
                    "de votre question. Veuillez réessayer."
                ),
                sources=[],
                is_error=True,
            )

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
            if _OUT_OF_SCOPE_MARKER in query:
                logger.info("[SCOPE] Question hors-scope détectée (condensation)")
                return RAGResponse(answer=_OUT_OF_SCOPE_ANSWER, sources=[])

        # --- Step 1-2: Query expansion + parallel search + RRF ---
        results, _variants = await self._search_with_expansion(query, organisation_id, org_idcc_list=org_idcc_list, org_context=org_context)
        if _variants and _variants[0] == _OUT_OF_SCOPE_MARKER:
            logger.info("[SCOPE] Question hors-scope détectée (expansion)")
            return RAGResponse(answer=_OUT_OF_SCOPE_ANSWER, sources=[])

        # --- Step 1.5: Identifier-based retrieval boost ---
        results = self._inject_identifier_matches(
            query, results, organisation_id, org_idcc_list,
        )
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

        # --- Step 3.5: Parent expansion (small-to-big) ---
        t_exp = time.perf_counter()
        results = expand_to_parents(results, self.search_engine.qdrant)
        logger.info(
            "[PERF] Step 3.5 — Parent expansion %.0fms | %d groups",
            (time.perf_counter() - t_exp) * 1000, len(results),
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
        is_replay: bool = False,
    ) -> tuple[list[SearchResult], str, RagTrace]:
        """Run steps 0-5 (non-streaming) and return results + reformulated query + trace."""
        self._org_id = organisation_id
        self._user_id = user_id
        self._conversation_id = conversation_id
        self._is_replay = is_replay
        self._propagate_cost_context()
        t0 = time.perf_counter()

        trace = RagTrace(query_original=query, model=rag_config.LLM_MODEL)

        # Step 0: Condensation (multi-turn)
        if history:
            t_cond = time.perf_counter()
            query = await self._step_with_timeout(
                self._condense_question(
                    query, history,
                    org_context=org_context,
                    cited_sources=cited_sources,
                ),
                fallback=query,
            )
            trace.perf_ms["condense"] = (time.perf_counter() - t_cond) * 1000
            trace.query_condensed = query
            logger.info(
                "[PERF] Step 0 — Condensation %.0fms | %s",
                trace.perf_ms["condense"], query[:100],
            )
            if _OUT_OF_SCOPE_MARKER in query:
                logger.info("[SCOPE] Question hors-scope détectée (condensation)")
                trace.out_of_scope = True
                trace.perf_ms["total"] = (time.perf_counter() - t0) * 1000
                return [], _OUT_OF_SCOPE_MARKER, trace

        # Step 1-2: Query expansion + parallel search + RRF
        t_exp_q = time.perf_counter()
        results, variants = await self._search_with_expansion(query, organisation_id, org_idcc_list=org_idcc_list, org_context=org_context)
        trace.perf_ms["expand_search"] = (time.perf_counter() - t_exp_q) * 1000
        trace.variants = list(variants) if variants else []
        if variants and variants[0] == _OUT_OF_SCOPE_MARKER:
            logger.info("[SCOPE] Question hors-scope détectée (expansion)")
            trace.out_of_scope = True
            trace.perf_ms["total"] = (time.perf_counter() - t0) * 1000
            return [], _OUT_OF_SCOPE_MARKER, trace
        reformulated = variants[0] if variants else query

        # Step 1.5: Identifier-based retrieval boost
        try:
            trace.identifiers_detected = detect_identifiers(query)
        except Exception:
            trace.identifiers_detected = {}
        pool_before_boost = len(results)
        results = self._inject_identifier_matches(
            query, results, organisation_id, org_idcc_list,
        )
        trace.boost_injected = max(0, len(results) - pool_before_boost)
        # Detect "identifier in query but no chunk matched the boost".
        # Strong signal of risk: the LLM may answer about another article
        # whose topic the expansion LLM guessed.
        has_identifiers = bool(
            trace.identifiers_detected.get("numero_pourvoi")
            or trace.identifiers_detected.get("article_nums")
        )
        if has_identifiers and trace.boost_injected == 0:
            trace.identifier_no_match = True
            logger.warning(
                "[QUALITY] identifier_no_match: %s — search relies on semantic guess",
                trace.identifiers_detected,
            )

        # Snapshot the candidate pool right before rerank
        trace.hybrid_results = _serialize_chunks(results, limit=30)
        t2 = time.perf_counter()

        # Step 3: Reranking
        results = await self._step_with_timeout(
            self.reranker.rerank(query, results, top_k=RERANK_TOP_K),
            fallback=results[:RERANK_TOP_K],
        )
        trace.perf_ms["rerank"] = (time.perf_counter() - t2) * 1000
        trace.rerank_results = _serialize_chunks(results, limit=RERANK_TOP_K)
        logger.info(
            "[PERF] Step 3 — Reranking %.0fms | %d results",
            trace.perf_ms["rerank"], len(results),
        )

        # Step 3.5: Parent expansion (small-to-big)
        t_exp = time.perf_counter()
        results = expand_to_parents(results, self.search_engine.qdrant)
        trace.perf_ms["parent_expansion"] = (time.perf_counter() - t_exp) * 1000
        trace.parent_groups = _serialize_chunks(results, limit=15, text_chars=400)
        logger.info(
            "[PERF] Step 3.5 — Parent expansion %.0fms | %d groups",
            trace.perf_ms["parent_expansion"], len(results),
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
        logger.info(
            "[PERF] Step 4 — Cross-ref %.0fms",
            (time.perf_counter() - t3) * 1000,
        )

        if not results:
            trace.no_results = True

        total = (time.perf_counter() - t0) * 1000
        trace.perf_ms["context_total"] = total
        logger.info(
            "[PERF] ══ Context ready %.0fms | %d results",
            total, len(results),
        )
        return results, reformulated, trace

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
            model=rag_config.LLM_MODEL,
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
                model=rag_config.LLM_MODEL,
                operation_type="generate",
                tokens_input=stream_usage.prompt_tokens,
                tokens_output=stream_usage.completion_tokens,
                organisation_id=self._org_id,
                user_id=self._user_id,
                context_type="question",
                context_id=self._conversation_id,
                is_replay=self._is_replay,
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
            content = msg["content"][:1500]
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
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": _CONDENSE_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            max_tokens=400,
        )
        if response.usage:
            await cost_tracker.log(
                provider="openai",
                model="gpt-5-mini",
                operation_type="condense",
                tokens_input=response.usage.prompt_tokens,
                tokens_output=response.usage.completion_tokens,
                organisation_id=self._org_id,
                user_id=self._user_id,
                context_type="question",
                context_id=self._conversation_id,
                is_replay=self._is_replay,
            )
        return response.choices[0].message.content or query

    @staticmethod
    def _build_expand_user_message(
        query: str,
        org_context: dict[str, str | None] | None,
    ) -> str:
        """Build the user message for query expansion with tenant context."""
        if not org_context:
            return f"Question : {query}"
        lines = ["[ORGANISATION]"]
        ccn = org_context.get("convention_collective")
        if ccn:
            lines.append(f"- CCN rattachée : {ccn}")
        secteur = org_context.get("secteur_activite")
        if secteur:
            lines.append(f"- Secteur : {secteur}")
        taille = org_context.get("taille")
        if taille:
            lines.append(f"- Taille : {taille}")
        forme = org_context.get("forme_juridique")
        if forme:
            lines.append(f"- Forme juridique : {forme}")
        if len(lines) == 1:
            return f"Question : {query}"
        lines.append("")
        lines.append(f"Question : {query}")
        return "\n".join(lines)

    async def _expand_queries(
        self,
        query: str,
        org_context: dict[str, str | None] | None = None,
    ) -> list[str]:
        """Step 1: Expand the user query into 5 search variants."""
        user_content = self._build_expand_user_message(query, org_context)
        response = await self.llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _QUERY_EXPAND_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=600,
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
                is_replay=self._is_replay,
            )
        content = response.choices[0].message.content or ""
        if _OUT_OF_SCOPE_MARKER in content:
            return [_OUT_OF_SCOPE_MARKER]
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

    def _inject_identifier_matches(
        self,
        query: str,
        results: list[SearchResult],
        organisation_id: str,
        org_idcc_list: list[str] | None,
    ) -> list[SearchResult]:
        """Step 1.5: detect identifiers in query and inject matching chunks at top.

        Pourvois (e.g. "22-18.875") and code articles (e.g. "L4121-1") match
        very weakly with semantic search when the query is identifier-only.
        We pull them directly via Qdrant filter and inject them at the top of
        the candidate pool so the reranker can promote them.
        """
        identifiers = detect_identifiers(query)
        if not any(identifiers.values()):
            return results
        try:
            extra = fetch_by_identifiers(
                self.search_engine.qdrant,
                identifiers,
                organisation_id=organisation_id,
                org_idcc_list=org_idcc_list,
            )
        except Exception:
            logger.exception("[BOOST] Identifier injection failed")
            return results
        if not extra:
            return results
        seen = {(r.document_id, r.chunk_index) for r in results}
        injected = 0
        for r in extra:
            key = (r.document_id, r.chunk_index)
            if key in seen:
                continue
            seen.add(key)
            results.insert(0, r)
            injected += 1
        logger.info(
            "[BOOST] Identifier injection: %d new chunks (total pool: %d)",
            injected, len(results),
        )
        return results

    async def _search_with_expansion(
        self,
        query: str,
        organisation_id: str,
        org_idcc_list: list[str] | None = None,
        org_context: dict[str, str | None] | None = None,
    ) -> tuple[list[SearchResult], list[str]]:
        """Expand query into variants, search in parallel, fuse with RRF."""
        t0 = time.perf_counter()

        variants = await self._step_with_timeout(
            self._expand_queries(query, org_context=org_context),
            fallback=[query],
        )
        t1 = time.perf_counter()
        logger.info(
            "[PERF] Step 1 — Query expansion %.0fms | %d variants: %s",
            (t1 - t0) * 1000,
            len(variants),
            " | ".join(v[:60] for v in variants),
        )

        # Always include the original query as variant #0 so identifiers like
        # article numbers / numéros de pourvoi (which are stripped from LLM
        # variants by design) are still searched. Skip if it's the OOS marker.
        if variants and variants[0] != _OUT_OF_SCOPE_MARKER:
            if query not in variants:
                variants = [query] + variants

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

            # Add article/section metadata when available (CCN, codes)
            if r.article_nums or r.section_path:
                article_label = ""
                if r.article_nums:
                    nums = ", ".join(r.article_nums)
                    article_label = f"Article{'s' if len(r.article_nums) > 1 else ''} {nums}"
                if r.section_path:
                    if article_label:
                        article_label = f"{article_label} — {r.section_path}"
                    else:
                        article_label = r.section_path
                header += f"Localisation : {article_label}\n"

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
            model=rag_config.LLM_MODEL,
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
                model=rag_config.LLM_MODEL,
                operation_type="generate",
                tokens_input=response.usage.prompt_tokens,
                tokens_output=response.usage.completion_tokens,
                organisation_id=self._org_id,
                user_id=self._user_id,
                context_type="question",
                context_id=self._conversation_id,
                is_replay=self._is_replay,
            )
        return response.choices[0].message.content or ""

    def _format_sources(self, results: list[SearchResult]) -> list[RAGSource]:
        """Step 7: Format search results into source references."""
        doc_chunks: dict[str, list[str]] = {}
        doc_meta: dict[str, SearchResult] = {}
        doc_article_nums: dict[str, list[str]] = {}
        doc_section_paths: dict[str, set[str]] = {}

        for r in results:
            if r.document_id not in doc_meta:
                doc_meta[r.document_id] = r
                doc_chunks[r.document_id] = []
                doc_article_nums[r.document_id] = []
                doc_section_paths[r.document_id] = set()
            doc_chunks[r.document_id].append(r.text)
            if r.article_nums:
                doc_article_nums[r.document_id].extend(r.article_nums)
            if r.section_path:
                doc_section_paths[r.document_id].add(r.section_path)

        sources: list[RAGSource] = []
        for doc_id, meta in doc_meta.items():
            chunks = doc_chunks[doc_id]
            full_text = "\n\n".join(chunks)

            excerpt = chunks[0][:300].strip()
            if len(chunks[0]) > 300:
                excerpt = excerpt.rsplit(" ", 1)[0] + "…"

            # Deduplicate article nums preserving order
            all_nums = doc_article_nums[doc_id]
            seen: set[str] = set()
            unique_nums = []
            for n in all_nums:
                if n not in seen:
                    seen.add(n)
                    unique_nums.append(n)

            sources.append(
                RAGSource(
                    document_id=meta.document_id,
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
                    article_nums=unique_nums or None,
                    section_path="; ".join(sorted(doc_section_paths[doc_id])) or None,
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
