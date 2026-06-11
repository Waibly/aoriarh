from app.core.config import settings

EMBEDDING_MODEL = settings.voyage_embedding_model

# --- Modèles LLM par étape (centralisés ici pour un changement en une ligne) ---
# Génération de la réponse finale (étape lourde) : piloté par settings.
LLM_MODEL = settings.llm_model
# Expansion de requête + ancre législative (étapes légères, transformation simple).
EXPAND_MODEL = "gpt-5-mini"
# Condensation des questions de suivi (étape légère et rapide, gardée volontairement
# sur un modèle léger : la qualité dépend surtout des instructions, pas de la taille).
CONDENSE_MODEL = "gpt-5-mini"

# C1 — Plancher de confiance : si le meilleur score de reranking reste sous ce
# seuil, la recherche est jugée faible et l'étape de génération reçoit une
# consigne de rigueur (interdiction d'avancer un chiffre/délai non sourcé).
# Ne se déclenche que sur retrieval faible : n'affecte pas les bonnes réponses.
LOW_CONFIDENCE_RERANK = 0.6

CHUNK_SIZE = 1024
CHUNK_OVERLAP = 100

TOP_K = 20
RERANK_TOP_K = 15
RERANK_MODEL = "rerank-2"

# Plancher de pertinence (étape 3.6) : les groupes parents dont le score de
# rerank est sous ce seuil ne sont ni affichés à l'utilisateur, ni envoyés à la
# génération. Calibré par rejeu des 188 traces prod (juin 2026) : à 0,35 on
# coupe ~17 % des groupes, échantillon vérifié = hors-sujet (décrets pensions
# sur questions BDESE, guides de bonnes pratiques sur opposition CSE…).
# Garde-fou : on conserve toujours les SOURCE_FLOOR_MIN_KEEP mieux notés.
SOURCE_SCORE_FLOOR = 0.35
SOURCE_FLOOR_MIN_KEEP = 3

# Legislation floor: number of "written-law" candidates pulled by the auxiliary
# legislation-only retrieval and injected into the candidate pool, so codified
# articles always reach the reranker even when jurisprudence dominates the main
# hybrid search. The reranker still decides which (if any) make the final cut.
LEGISLATION_FLOOR_TOP = 5

CONDENSE_HISTORY_LIMIT = 6

RAG_TIMEOUT_GLOBAL = 120.0
RAG_TIMEOUT_PER_STEP = 60.0
