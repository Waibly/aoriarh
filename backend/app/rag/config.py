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

# Plancher de confiance dédié aux conventions collectives. Les articles de CCN
# rerankent structurellement plus bas que le Code du travail (articles longs,
# question souvent cadrée « selon le Code du travail… »). Avec le seuil général
# de 0,6, une question portant explicitement sur la convention de l'org (filtre
# d'intention restreint aux CCN) basculait à tort en « faible confiance » et la
# génération bottait en touche. Un match CCN de l'org au-dessus de ce seuil est
# une vraie réponse : c'est littéralement sa convention installée.
CCN_LOW_CONFIDENCE_RERANK = 0.30

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

# Repêchage CCN : la convention installée de l'org reranke plus bas que le Code
# du travail, et tombait donc sous le plancher général (0,35) sur les questions
# cadrées « Code du travail » — la CCN disparaissait de la réponse alors que
# l'utilisateur attend justement ce que dit SA convention. Tout résultat CCN
# présent dans le pool a, par construction, passé le filtre IDCC : c'est la
# convention de l'org. On repêche donc jusqu'à CCN_FLOOR_RESCUE groupes CCN
# tombés sous le plancher général, à condition de rester pertinents (≥ ce seuil
# plancher dédié). Borné, donc pas de réintroduction massive de bruit.
CCN_SCORE_FLOOR = 0.15
CCN_FLOOR_RESCUE = 2

# Legislation floor: number of "written-law" candidates pulled by the auxiliary
# legislation-only retrieval and injected into the candidate pool, so codified
# articles always reach the reranker even when jurisprudence dominates the main
# hybrid search. The reranker still decides which (if any) make the final cut.
LEGISLATION_FLOOR_TOP = 5

# Plancher CCN : symétrique au plancher législation. Sur une question cadrée
# « selon le Code du travail… », la recherche principale remonte surtout des
# articles du Code et la convention de l'org n'atteint même pas le top-15 du
# reranker (elle ne peut donc pas être repêchée par le plancher de pertinence).
# On lance donc une recherche auxiliaire restreinte à la CCN installée de l'org
# et on injecte ses meilleurs candidats dans le pool, pour que la convention de
# l'org soit TOUJOURS soumise au reranker. Le reranker reste seul juge de
# l'ordre final ; le repêchage CCN (CCN_FLOOR_RESCUE) prend ensuite le relais
# si elle reranke sous le plancher général.
CCN_FLOOR_TOP = 5

CONDENSE_HISTORY_LIMIT = 6

RAG_TIMEOUT_GLOBAL = 120.0
RAG_TIMEOUT_PER_STEP = 60.0
