from app.core.config import settings

EMBEDDING_MODEL = settings.voyage_embedding_model

# --- Modèles LLM par étape (centralisés ici pour un changement en une ligne) ---
# Génération de la réponse finale (étape lourde) : piloté par settings.
LLM_MODEL = settings.llm_model
LLM_REASONING_EFFORT = settings.llm_reasoning_effort
# Planificateur compact de recherche (nom conservé pour les consommateurs existants).
EXPAND_MODEL = "gpt-5-mini"

CHUNK_SIZE = 1024
CHUNK_OVERLAP = 100

TOP_K = 20
RERANK_MODEL = "rerank-2"

# Legislation floor: number of "written-law" candidates pulled by the auxiliary
# legislation-only retrieval and injected into the candidate pool, so codified
# articles always reach the reranker even when jurisprudence dominates the main
# hybrid search. The reranker still decides which (if any) make the final cut.
LEGISLATION_FLOOR_TOP = 5

# Candidats CCN supplémentaires soumis au classement commun, sans repêchage.
CCN_FLOOR_TOP = 5

CONDENSE_HISTORY_LIMIT = 6

RAG_TIMEOUT_PER_STEP = 60.0

# Chemin STREAMING (le seul utilisé par le front) : filets de sécurité.
# Principe directeur (Vanessa, 28/07) : ne JAMAIS couper une réponse qui
# avance, même lentement — mieux vaut long et complet que rapide et tronqué.
# On ne coupe que ce qui est réellement MORT (plus rien à attendre).
# - CONTEXT : préparation du contexte (étapes 0-5, normal ~10 s). Chaque
#   étape a déjà sa borne RAG_TIMEOUT_PER_STEP ; cette borne globale ne
#   vise que le blocage franc → erreur propre « réessayez ».
# - STREAM_IDLE : INACTIVITÉ de la génération, réarmée à chaque token reçu.
#   Une réponse lente mais vivante n'est jamais interrompue (l'incident du
#   27/07 — 13 min 39 en continu — serait allé au bout) ; seul un flux
#   silencieux pendant 3 min est abandonné, en conservant le déjà-émis.
RAG_TIMEOUT_CONTEXT = 120.0
RAG_TIMEOUT_STREAM_IDLE = 180.0
# Au-delà de ce délai sans progression (contexte ou génération), on envoie un
# message de patience à l'utilisateur (« ça prend plus de temps que
# d'habitude… ») plutôt que de le laisser devant un écran figé. Purement
# informatif : ne coupe rien.
RAG_SLOW_NOTICE = 15.0
