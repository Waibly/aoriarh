# AORIA RH — Architecture du pipeline RAG

> Schéma complet du parcours d'une question utilisateur, de la saisie à l'affichage de la réponse.

---

## 1. Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           FRONTEND (Next.js)                            │
│                                                                         │
│  Utilisateur tape sa question                                           │
│       │                                                                 │
│       ▼                                                                 │
│  ChatInput ──► handleSend() ──► streamMessage() ──► POST /chat/stream   │
│                                       SSE ◄─────────────────────────    │
│                                        │                                │
│                          ┌─────────────┼──────────────┐                 │
│                          ▼             ▼              ▼                  │
│                   chat_sources    chat_delta     chat_done               │
│                   (sources)      (tokens LLM)   (message IDs)           │
│                          │             │              │                  │
│                          ▼             ▼              ▼                  │
│                   Affiche les   Streaming en    Sauvegarde              │
│                   sources       temps réel      dans state              │
│                   sous le msg   du texte        React final             │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP POST + SSE
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          BACKEND (FastAPI)                               │
│                                                                         │
│  POST /api/v1/conversations/{id}/chat/stream                            │
│       │                                                                 │
│       ├── 1. Auth (JWT) + vérification accès conversation               │
│       ├── 2. Charge historique (6 derniers messages)                     │
│       ├── 3. RAGAgent.prepare_context()  ←── Steps 0 à 5               │
│       ├── 4. Envoie SSE "chat_sources"                                  │
│       ├── 5. RAGAgent.stream_generate()  ←── Step 6 (streaming)         │
│       ├── 6. Envoie SSE "chat_delta" × N                                │
│       ├── 7. Sauvegarde messages en DB (PostgreSQL)                     │
│       └── 8. Envoie SSE "chat_done"                                     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Pipeline RAG détaillé (RAGAgent)

**Type : Pipeline séquentiel déterministe (PAS un agent autonome)**

L'agent ne "décide" pas quoi faire. Chaque étape s'exécute dans un ordre fixe,
avec des timeouts et des fallbacks. La seule boucle conditionnelle est la
re-recherche (étape 3b) si les résultats sont insuffisants.

```
Question utilisateur
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 0 — CONDENSATION (si multi-turn)                            │
│                                                                  │
│  Entrée : question + historique (6 derniers messages)             │
│  LLM    : gpt-4o-mini (rapide, pas cher)                        │
│  Sortie : question autonome reformulée                           │
│                                                                  │
│  Ex: Historique = "Parlez-moi du licenciement économique"        │
│      Question  = "Et pour les indemnités ?"                      │
│      Résultat  = "Quelles sont les indemnités de licenciement    │
│                   économique ?"                                   │
│                                                                  │
│  ⚡ Sauté si c'est le 1er message de la conversation             │
└──────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 1 — EXPANSION DE REQUÊTE                                    │
│                                                                  │
│  LLM : gpt-4o-mini                                               │
│  Génère 3 variantes de recherche :                               │
│                                                                  │
│  1. Langage naturel :                                            │
│     "Quelles indemnités touche un salarié licencié pour          │
│      motif économique ?"                                         │
│                                                                  │
│  2. Terminologie juridique :                                     │
│     "Indemnité légale de licenciement motif économique           │
│      L1234-9 droit du travail calcul ancienneté"                 │
│                                                                  │
│  3. Mots-clés :                                                  │
│     "indemnité licenciement économique calcul ancienneté         │
│      convention collective seuil"                                │
└──────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 2 — RECHERCHE HYBRIDE PARALLÈLE                             │
│                                                                  │
│  Les 3 variantes sont recherchées EN PARALLÈLE (asyncio.gather)  │
│                                                                  │
│  Pour chaque variante :                                          │
│  ┌────────────────────────────────────────────────┐              │
│  │                                                │              │
│  │  ┌──────────────┐     ┌──────────────────┐     │              │
│  │  │ Dense Vector  │     │ Sparse BM25      │     │              │
│  │  │ (Voyage AI    │     │ (mots-clés       │     │              │
│  │  │  voyage-law-2)│     │  exact match)    │     │              │
│  │  │ 1024 dims     │     │                  │     │              │
│  │  └──────┬───────┘     └────────┬─────────┘     │              │
│  │         │                      │                │              │
│  │         └──────┐   ┌──────────┘                │              │
│  │                ▼   ▼                            │              │
│  │         ┌─────────────┐                         │              │
│  │         │ Qdrant RRF   │ ← filtre OBLIGATOIRE:  │              │
│  │         │ (fusion       │   organisation_id =    │              │
│  │         │  hybride)     │   user_org OR "common" │              │
│  │         └──────┬──────┘                         │              │
│  │                │                                │              │
│  │         Top 20 résultats                        │              │
│  └────────────────┼───────────────────────────────┘              │
│                   │ × 3 variantes                                │
│                   ▼                                               │
│  ┌─────────────────────────────────────┐                         │
│  │ RECIPROCAL RANK FUSION (RRF)        │                         │
│  │                                     │                         │
│  │ score = Σ 1/(60 + rank)             │                         │
│  │ pour chaque liste de résultats      │                         │
│  │                                     │                         │
│  │ → Fusionne ~60 résultats en top 20  │                         │
│  └─────────────────────────────────────┘                         │
└──────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 3 — RERANKING (Cross-Encoder)                               │
│                                                                  │
│  Service : Voyage AI rerank-2                                    │
│  Entrée  : top 20 résultats + question originale                 │
│  Sortie  : top 5 résultats les plus pertinents                   │
│                                                                  │
│  Le cross-encoder évalue chaque paire (question, chunk)          │
│  indépendamment → bien plus précis que la similarité vectorielle │
│                                                                  │
│  ⚠ Retry avec backoff exponentiel si erreur 429 (rate limit)    │
└──────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 3b — RE-RECHERCHE CONDITIONNELLE                            │
│                                                                  │
│  SI résultats < 2 après reranking :                              │
│     → Relance une recherche directe (sans expansion)             │
│     → Fusionne avec les résultats existants                      │
│     → Max 2 itérations                                           │
│                                                                  │
│  C'est la SEULE boucle du pipeline.                              │
│  Si toujours 0 résultat → retourne "pas de documents trouvés"   │
└──────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 4 — RÉFÉRENCES CROISÉES                                     │
│                                                                  │
│  Si un document apparaît plusieurs fois dans les résultats :     │
│  score *= 1.0 + 0.05 × (nb_citations - 1)                       │
│                                                                  │
│  Ex: Un article cité 3 fois → score × 1.10                      │
│  → Les documents fréquemment référencés sont boostés             │
└──────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 5 — VALIDATION HIÉRARCHIE DES NORMES                        │
│                                                                  │
│  Boost de +15% pour les normes du niveau le plus élevé           │
│  présent dans les résultats.                                     │
│                                                                  │
│  Niveau 1 : Constitution                    (poids 1.0)         │
│  Niveau 2 : Traités internationaux          (poids 0.95)        │
│  Niveau 3 : Droit européen                  (poids 0.9)         │
│  Niveau 4 : Code du travail, Lois           (poids 0.85)        │
│  Niveau 5 : Ordonnances                     (poids 0.8)         │
│  Niveau 6 : Décrets, Arrêtés               (poids 0.75)        │
│  Niveau 7 : Conventions collectives         (poids 0.65)        │
│  Niveau 8 : Accords d'entreprise            (poids 0.6)         │
│  Niveau 9 : Usages, Jurisprudence           (poids 0.5)         │
│                                                                  │
│  Tri final : score décroissant, puis niveau croissant            │
│  → Les normes supérieures apparaissent en premier                │
└──────────────────────────────────────────────────────────────────┘
       │
       │ ←── À ce stade, les SOURCES sont envoyées au client (SSE)
       ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 6 — GÉNÉRATION LLM (Streaming)                              │
│                                                                  │
│  LLM : gpt-5-mini (reasoning_effort="low")                      │
│                                                                  │
│  Prompt système (~145 lignes) :                                  │
│  ├── Rôle : assistant juridique RH                               │
│  ├── Types d'intention (procédure, légalité, liste, calcul...)  │
│  ├── Principe de faveur (plus favorable au salarié)             │
│  ├── Hiérarchie des normes (Constitution > ... > Usages)        │
│  ├── Anti-hallucination (JAMAIS inventer, sourcer)              │
│  └── Format (Markdown, actionnable, pas de citation directe)    │
│                                                                  │
│  Prompt utilisateur :                                            │
│  ├── Sources documentaires formatées [Source 1], [Source 2]...   │
│  └── Question reformulée                                         │
│                                                                  │
│  Streaming : tokens envoyés par buffer de 10                     │
│  → SSE "chat_delta" envoyé au frontend à chaque buffer           │
└──────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 7 — SAUVEGARDE & FINALISATION                               │
│                                                                  │
│  1. Sauvegarde message user en DB (PostgreSQL)                   │
│  2. Sauvegarde message assistant + sources en DB                 │
│  3. Auto-génération du titre si 1er message                     │
│  4. Envoi SSE "chat_done" avec les IDs des messages              │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Flux de données complet (séquence)

```
Utilisateur          Frontend              Backend (FastAPI)         Services externes
    │                   │                        │                        │
    │  Tape question    │                        │                        │
    │──────────────────►│                        │                        │
    │                   │                        │                        │
    │                   │  POST /chat/stream      │                        │
    │                   │  {message, JWT}         │                        │
    │                   │───────────────────────►│                        │
    │                   │                        │                        │
    │                   │                        │── Auth + load history   │
    │                   │                        │                        │
    │                   │                        │  Step 0: Condensation   │
    │                   │                        │───────────────────────►│ gpt-4o-mini
    │                   │                        │◄───────────────────────│
    │                   │                        │                        │
    │                   │                        │  Step 1: Expansion      │
    │                   │                        │───────────────────────►│ gpt-4o-mini
    │                   │                        │◄───────────────────────│ (3 variantes)
    │                   │                        │                        │
    │                   │                        │  Step 2: Recherche ×3   │
    │                   │                        │───────────────────────►│ Voyage AI
    │                   │                        │◄───────────────────────│ (embeddings)
    │                   │                        │───────────────────────►│ Qdrant
    │                   │                        │◄───────────────────────│ (hybrid search)
    │                   │                        │                        │
    │                   │                        │  Step 2b: RRF fusion    │
    │                   │                        │  (local, pas d'API)     │
    │                   │                        │                        │
    │                   │                        │  Step 3: Reranking      │
    │                   │                        │───────────────────────►│ Voyage AI
    │                   │                        │◄───────────────────────│ (rerank-2)
    │                   │                        │                        │
    │                   │                        │  Steps 4-5: Cross-ref   │
    │                   │                        │  + Hiérarchie (local)   │
    │                   │                        │                        │
    │                   │  SSE: chat_sources      │                        │
    │                   │◄───────────────────────│                        │
    │  Affiche sources  │                        │                        │
    │◄──────────────────│                        │                        │
    │                   │                        │  Step 6: Génération     │
    │                   │                        │───────────────────────►│ gpt-5-mini
    │                   │                        │                        │ (streaming)
    │                   │  SSE: chat_delta ×N     │◄ ─ ─ ─ token ─ ─ ─ ─│
    │                   │◄───────────────────────│                        │
    │  Texte en direct  │                        │                        │
    │◄──────────────────│                        │                        │
    │  (token par token)│                        │                        │
    │                   │                        │                        │
    │                   │                        │── Save to PostgreSQL    │
    │                   │                        │                        │
    │                   │  SSE: chat_done         │                        │
    │                   │◄───────────────────────│                        │
    │  Réponse finale   │                        │                        │
    │◄──────────────────│                        │                        │
```

---

## 4. Agent ou pas agent ?

### Ce qu'on a : un **pipeline structuré**

```
Question ──► Step 0 ──► Step 1 ──► Step 2 ──► Step 3 ──► ... ──► Réponse
                         (fixe)     (fixe)     (fixe)     (fixe)
```

- Ordre d'exécution **fixe et prédéterminé**
- Pas de prise de décision dynamique par le LLM sur "quoi faire ensuite"
- Pas de sélection d'outils (tools/functions) par le LLM
- Une seule boucle conditionnelle (re-recherche si < 2 résultats)
- Nombre d'appels LLM **prévisible** : 2-3 (condensation + expansion + génération)

### Ce que serait un **vrai agent**

```
Question ──► LLM décide ──┬──► Outil "recherche" ──► LLM évalue
                          │                              │
                          ├──► Outil "calcul"            ├──► Suffisant ?
                          │                              │     Non → re-planifie
                          ├──► Outil "comparaison"       │     Oui → génère
                          │                              │
                          └──► Outil "rédaction"         ▼
                                                     Réponse
```

- Le LLM **choisit** quels outils appeler et dans quel ordre
- Boucle de raisonnement (ReAct, plan-and-execute, etc.)
- Peut s'adapter dynamiquement à la complexité de la question
- Nombre d'appels LLM **variable et imprévisible**

### Verdict

| Critère                        | Pipeline actuel | Agent autonome |
|-------------------------------|----------------|---------------|
| Prédictibilité                | Haute          | Moyenne        |
| Latence                       | ~3-8s          | ~8-30s         |
| Coût par requête             | Fixe (~3 appels LLM) | Variable (3-15+) |
| Auditabilité                 | Excellente     | Moyenne        |
| Gestion questions simples     | Optimal        | Overkill       |
| Gestion questions complexes   | Limité         | Supérieur      |
| Calculs, comparaisons, rédaction | Impossible   | Possible       |
| Risque d'hallucination        | Contrôlé      | Plus élevé    |

**Recommandation** : garder le pipeline actuel pour le Q&A standard,
et ajouter des capacités agentiques **uniquement** pour les cas d'usage
avancés (calcul d'indemnités, rédaction de courriers, audit de conformité).

---

## 5. Services externes impliqués

| Service        | Usage                              | Étape(s)      |
|---------------|-----------------------------------|---------------|
| **OpenAI**     | gpt-4o-mini (condensation, expansion) | 0, 1       |
| **OpenAI**     | gpt-5-mini (génération réponse)    | 6             |
| **Voyage AI**  | voyage-law-2 (embeddings 1024d)    | 2             |
| **Voyage AI**  | rerank-2 (cross-encoder)           | 3             |
| **Qdrant**     | Recherche hybride (dense + BM25)   | 2             |
| **PostgreSQL** | Historique, conversations, messages | 0, 7          |
| **MinIO**      | Stockage fichiers originaux        | (ingestion)   |

---

## 6. Timeouts et garde-fous

| Paramètre              | Valeur  | Rôle                                    |
|------------------------|---------|-----------------------------------------|
| `RAG_TIMEOUT_GLOBAL`   | 120s    | Timeout total du pipeline               |
| `RAG_TIMEOUT_PER_STEP` | 60s     | Timeout par étape individuelle          |
| `RAG_MAX_ITERATIONS`   | 2       | Max re-recherches si résultats < 2      |
| `TOP_K`                | 20      | Résultats par recherche                 |
| `RERANK_TOP_K`         | 5       | Résultats après reranking               |
| `CONDENSE_HISTORY_LIMIT` | 6     | Messages d'historique pour condensation |
| Rate limit API         | 15/min  | Limite par utilisateur                  |
| Buffer streaming       | 10 tokens | Taille du buffer SSE                  |
