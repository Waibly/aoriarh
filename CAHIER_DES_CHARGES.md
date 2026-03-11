# Cahier des charges — AORIA RH

## 1. Présentation du projet

### 1.1 Description générale

AORIA RH est une application web SaaS multi-tenant d'**assistance juridique RH par intelligence artificielle**. Elle permet aux utilisateurs de poser des questions juridiques liées aux ressources humaines via une interface de chat conversationnel et d'obtenir des réponses sourcées, générées par IA à partir d'une base documentaire juridique (Code du travail, conventions collectives, jurisprudence, documents internes d'entreprise).

### 1.2 Objectifs

- Fournir des réponses juridiques RH fiables et sourcées en temps réel
- Permettre aux entreprises d'alimenter leur propre base documentaire pour des réponses contextualisées
- Garantir un cloisonnement strict des données entre organisations
- Proposer une expérience utilisateur simple, type ChatGPT

### 1.3 Cible utilisateurs

- TPE / PME / ETI souhaitant un accès rapide à l'information juridique RH
- Services RH internes
- Cabinets de conseil RH

---

## 2. Architecture technique

### 2.1 Stack technique

| Couche | Technologie | Rôle |
|---|---|---|
| Frontend | Next.js + React + Tailwind CSS | Interface utilisateur, SSR, thème light/dark |
| Backend / API | Python FastAPI | API REST, orchestration RAG, logique métier |
| RAG Framework | LlamaIndex | Pipeline d'ingestion et de recherche documentaire |
| Base de données | PostgreSQL | Données relationnelles (utilisateurs, organisations, abonnements, conversations) |
| Vector Store | Qdrant | Stockage et recherche des embeddings documentaires |
| Modèle d'embedding | Voyage AI — `voyage-law-2` | Génération des embeddings spécialisés juridiques |
| LLM | OpenAI — `gpt-5-mini` | Génération des réponses conversationnelles |
| Authentification | NextAuth.js ou Clerk | Gestion de l'authentification, rôles, invitations |
| Paiement | Stripe | Gestion des abonnements et plans tarifaires |
| Stockage documents | MinIO (self-hosted, compatible S3) | Stockage des fichiers uploadés avant ingestion RAG |
| Déploiement | Docker + Vercel (front) + Railway/Fly.io (back) | Infrastructure scalable |

### 2.2 Rôle de LlamaIndex

LlamaIndex est le **framework d'orchestration RAG** du projet. Il relie tous les composants IA entre eux et évite de recoder manuellement ~60-70% du pipeline.

#### Ce que LlamaIndex gère

**Pipeline d'ingestion (upload → Qdrant) :**
- **Loaders** : extraction du texte depuis PDF, DOCX, etc. (intégrés nativement)
- **Chunking** : découpage intelligent des documents (configurable pour respecter la structure juridique par article)
- **Embedding** : appel à Voyage AI `voyage-law-2` pour vectoriser chaque chunk (batching automatique)
- **Indexation** : envoi des vecteurs + metadata dans Qdrant

**Pipeline de recherche (question → résultats) :**
- **Query engine** : orchestration de la recherche hybride (sémantique + BM25)
- **Retriever** : connecteur natif Qdrant avec filtrage par metadata (`organisation_id`, `statut`, `norme_niveau`)
- **Reranking** : intégration native des rerankers (Voyage AI `rerank-2`, Cohere)
- **Reciprocal Rank Fusion** : fusion des résultats issus de la query expansion

**Agent structuré :**
- **Agent framework** : agents avec outils (tools) définis, adaptés à notre agent à étapes contraintes (section 6.4)
- **Query transformation** : reformulation et condensation du contexte conversationnel — modules prêts à l'emploi
- **Response synthesizer** : construction du prompt final avec les chunks récupérés + génération via `gpt-5-mini`

**Conversation multi-tours :**
- **Chat engine** : gestion de l'historique conversationnel
- **Condense question** : module natif transformant une question de suivi en question autonome

#### Connecteurs natifs utilisés

| Service | Connecteur LlamaIndex |
|---|---|
| Qdrant | `QdrantVectorStore` |
| Voyage AI | `VoyageEmbedding` |
| OpenAI | `OpenAI` (LLM) |
| MinIO / S3 | Loaders S3 |

#### Ce que LlamaIndex ne gère pas

| Aspect | Géré par |
|---|---|
| Authentification / rôles / invitations | NextAuth.js + FastAPI |
| Multi-tenancy / cloisonnement applicatif | FastAPI + filtrage Qdrant |
| Stockage des fichiers originaux | MinIO |
| Interface utilisateur | Next.js / React |
| Abonnements / paiement | Stripe |
| Base de données relationnelle | PostgreSQL |

### 2.3 Coûts LLM

| Modèle | Input (1M tokens) | Cached (1M tokens) | Output (1M tokens) |
|---|---|---|---|
| `gpt-5-mini` | $0.25 | $0.025 | $2.00 |

### 2.3 Multi-tenancy

Le système repose sur un modèle multi-tenant. Le cloisonnement des données entre organisations est **critique** :

- Chaque document, embedding et conversation est associé à un `organisation_id`
- Les embeddings dans Qdrant sont taggés par metadata (`organisation_id` ou `common`) pour filtrer les résultats au moment de la recherche vectorielle
- Un utilisateur ne peut jamais accéder aux données d'une organisation à laquelle il n'est pas rattaché

---

## 3. Gestion des utilisateurs et des droits

### 3.1 Authentification

- **Inscription** : un utilisateur peut créer un compte (email / mot de passe, OAuth possible)
- **Connexion** : login classique avec gestion de session

### 3.2 Rôles

| Rôle | Description | Périmètre |
|---|---|---|
| **Admin** | Personnel interne AORIA RH | Accès au back-office, gestion des documents communs, supervision globale |
| **Manager** | Utilisateur ayant souscrit un abonnement | Création d'organisations, invitation de membres, gestion des abonnements, gestion documentaire, chat |
| **Utilisateur** | Membre invité par un Manager | Accès au chat, upload de documents dans les organisations auxquelles il est rattaché |

### 3.3 Règles de gestion des droits

- Un utilisateur qui **souscrit** à l'application obtient automatiquement le rôle **Manager**
- Un Manager peut **créer une ou plusieurs organisations**
- Un Manager peut **inviter des membres** dans ses organisations
- Lors de l'invitation, le Manager attribue :
  - Une ou plusieurs **organisations**
  - Un **rôle** par organisation : Manager ou Utilisateur
- Un **Utilisateur** peut uploader des documents dans les organisations auxquelles il est rattaché
- Un **Manager** peut en plus : inviter des membres et gérer l'abonnement

---

## 4. Gestion des organisations

### 4.1 Création et informations

Un Manager peut créer une ou plusieurs organisations. Chaque organisation contient les informations suivantes :

| Champ | Type | Valeurs |
|---|---|---|
| Nom | Texte libre | — |
| Forme juridique | Liste déroulante | SAS, SARL, SA, SASU, EURL, SCI, SNC, Association loi 1901, Auto-entrepreneur / Micro-entreprise, Société coopérative (SCOP), GIE |
| Taille de l'entreprise | Liste déroulante | 1-10 salariés, 11-50 salariés, 51-250 salariés, 251-500 salariés, 501-1 000 salariés, 1 000+ salariés |

### 4.2 Gestion des membres

Chaque organisation dispose d'une section listant les utilisateurs rattachés, avec :

- Nom / email de l'utilisateur
- Rôle dans l'organisation (Manager ou Utilisateur)
- Actions : modifier le rôle, retirer de l'organisation

### 4.3 Sélecteur d'organisation

- Un **sélecteur (listbox)** est situé dans la **sidebar gauche**, juste sous le logo AORIA RH
- Il liste uniquement les organisations auxquelles l'utilisateur a accès
- Le changement d'organisation **switche le contexte global** : documents, conversations, recherche RAG

---

## 5. Gestion documentaire

### 5.1 Types de documents

| Type | Uploadé par | Visible par | Exemples |
|---|---|---|---|
| **Documents communs** | Admin (back-office) | Tous les utilisateurs de toutes les organisations | Code du travail, conventions collectives, jurisprudence |
| **Documents d'organisation** | Managers et Utilisateurs de l'organisation | Tous les membres de l'organisation concernée | Accords d'entreprise, règlement intérieur, contrats types |

### 5.2 Cloisonnement documentaire (règle critique)

- Un utilisateur voit **toujours** les documents communs
- Un utilisateur voit les documents des organisations **auxquelles il est rattaché**
- Un utilisateur ne voit **jamais** les documents d'une organisation à laquelle il n'est pas rattaché
- Ce cloisonnement s'applique aussi bien à l'affichage qu'à la **recherche RAG** (filtrage Qdrant par metadata)

### 5.3 Hiérarchie des normes et typologie documentaire

Lors de l'upload d'un document, l'utilisateur (Admin, Manager ou Utilisateur) doit **obligatoirement sélectionner le type de document**. Ce type détermine automatiquement la **priorité** et le **poids** du document dans le système RAG, conformément à la hiérarchie des normes du droit social français.

#### Tableau de la hiérarchie des normes

| Priorité | Niveau | Types de documents | Poids | Règle de dérogation |
|---|---|---|---|---|
| **1** | Constitution | Constitution | 1.0 | Aucune — s'impose à tout |
| **2** | Normes internationales | Conventions OIT, Directives UE, Traité UE | 0.95 | Aucune — supérieur aux lois nationales |
| **3** | Lois & Ordonnances | Lois, Ordonnances, Code du travail (L), Code de la sécurité sociale (L), Code pénal (L), Code civil (L) | 0.9 | Socle minimal — plancher de droits, dérogation seulement si plus favorable |
| **4** | Jurisprudence | Cour de cassation, Conseil d'État, Conseil constitutionnel | 0.85 | Interprétation — précise l'application des normes |
| **5** | Réglementaire | Décrets, Arrêtés, Code du travail (R, D) | 0.8 | Socle minimal — application et précision des lois |
| **6** | Conventions collectives | ANI, Accord de branche, CCN, Accord d'entreprise, APC | 0.60–0.75 | 3 blocs Macron / Principe de faveur / Moins favorable (APC) |
| **7** | Usages & Engagements | Usages d'entreprise, DUE | 0.6 | Principe de faveur |
| **8** | Règlement intérieur | Règlement intérieur | 0.55 | Application stricte — discipline, sécurité |
| **9** | Contrat de travail | Contrat de travail | 0.5 | Principe de faveur — peut améliorer les normes supérieures |

**26 types de documents** répartis en **9 niveaux de priorité**.

#### Logique de priorisation

- Plus la priorité est basse (1 = plus fort), plus la norme est **contraignante** et s'impose aux niveaux inférieurs
- **Niveaux 1-2** : ordre public absolu — intouchables
- **Niveau 3** : fixe un plancher de droits (socle minimal)
- **Niveau 6** : seul niveau modulé par les **3 blocs Macron** qui déterminent si la branche ou l'entreprise prime
- **Niveaux 7-9** : ne peuvent qu'améliorer les normes supérieures (principe de faveur), sauf l'**APC** qui peut être moins favorable

#### Impact sur le RAG

Le poids et la priorité sont utilisés par le pipeline RAG pour :

- **Pondérer les résultats** : à pertinence sémantique égale, un article du Code du travail (poids 0.9) prime sur un usage d'entreprise (poids 0.6)
- **Résoudre les contradictions** : si deux sources se contredisent, l'agent applique la hiérarchie des normes et le principe de faveur
- **Contextualiser la réponse** : le LLM doit indiquer le niveau de la norme citée et signaler si une norme supérieure pourrait s'appliquer

#### Sélection du type à l'upload

À l'upload d'un document, l'interface affiche une **liste déroulante obligatoire** regroupée par niveau :

```
── Constitution ──
   Constitution

── Normes internationales ──
   Convention OIT
   Directive UE
   Traité UE

── Lois & Ordonnances ──
   Loi
   Ordonnance
   Code du travail (partie législative)
   Code de la sécurité sociale (partie législative)
   Code pénal (partie législative)
   Code civil (partie législative)

── Jurisprudence ──
   Arrêt Cour de cassation
   Arrêt Conseil d'État
   Décision Conseil constitutionnel

── Réglementaire ──
   Décret
   Arrêté
   Code du travail (partie réglementaire)

── Conventions collectives ──
   Accord national interprofessionnel (ANI)
   Accord de branche
   Convention collective nationale (CCN)
   Accord d'entreprise
   Accord de performance collective (APC)

── Usages & Engagements ──
   Usage d'entreprise
   Décision unilatérale de l'employeur (DUE)

── Règlement intérieur ──
   Règlement intérieur

── Contrat de travail ──
   Contrat de travail
```

### 5.4 Interface de gestion documentaire

Chaque organisation dispose d'un espace de gestion documentaire accessible depuis le menu.

#### Tableau de liste des documents

| Colonne | Description |
|---|---|
| **Nom du document** | Nom du fichier ou titre saisi |
| **Type** | Type juridique sélectionné à l'upload (ex : Accord d'entreprise, CCN, Loi…) |
| **Niveau** | Niveau dans la hiérarchie des normes (ex : Conventions collectives, Lois & Ordonnances…) |
| **Statut d'indexation** | État du traitement RAG : `En attente`, `En cours`, `Indexé`, `Erreur` |
| **Uploadé par** | Nom de l'utilisateur ayant ajouté le document |
| **Date d'upload** | Date d'ajout |
| **Taille** | Taille du fichier |
| **Format** | Icône du type de fichier (PDF, DOCX, etc.) |

#### Actions par document

- **Télécharger** le document original
- **Modifier** (remplacer le fichier, modifier les métadonnées / le type)
- **Supprimer** (avec modale de confirmation)

### 5.4 Pipeline d'ingestion RAG

Le pipeline d'ingestion transforme un document uploadé en vecteurs cherchables dans Qdrant. Il est **découplé de l'upload** : le document est d'abord stocké dans MinIO avec le statut `pending`, puis l'indexation se lance en tâche de fond (BackgroundTask FastAPI). L'utilisateur n'attend pas la fin de l'indexation.

#### 5.4.1 Schéma du pipeline complet

```
┌─────────────────────────────────────────────────────────────┐
│  UPLOAD (synchrone) — déjà implémenté                       │
│  1. Validation format (PDF, DOCX, TXT)                      │
│  2. Calcul SHA-256 → détection doublon (409 si existe)      │
│  3. Upload fichier vers MinIO                                │
│  4. Création enregistrement PostgreSQL (status = "pending")  │
│  5. Déclenchement indexation en background                   │
└─────────────┬───────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 1 — Extraction du texte                              │
│                                                              │
│  • PDF → Markdown via pymupdf4llm (préserve la structure :  │
│    titres, articles, tableaux, listes numérotées)            │
│  • DOCX → Markdown via python-docx (titres, paragraphes,    │
│    tableaux convertis en Markdown table)                     │
│  • TXT → lecture directe, normalisation des retours à la    │
│    ligne et de l'encodage                                    │
│  • Images ignorées (PDFs non scannés uniquement)             │
│                                                              │
│  Si échec extraction → indexation_status = "error"           │
└─────────────┬───────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 2 — Nettoyage du texte                               │
│                                                              │
│  • Suppression des headers/footers répétés (numéros de      │
│    page, "Page X sur Y", en-têtes d'entreprise)              │
│  • Suppression des sauts de ligne parasites mid-phrase       │
│    (artefact courant de l'extraction PDF)                    │
│  • Normalisation : espaces multiples, tirets, guillemets     │
│    typographiques → guillemets standards                     │
│  • Nettoyage des caractères de contrôle et zero-width chars │
└─────────────┬───────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 3 — Chunking juridique intelligent                   │
│                                                              │
│  Stratégie à 3 niveaux de priorité :                        │
│                                                              │
│  1. ARTICLES DÉTECTÉS (cas idéal)                            │
│     Détection par regex des articles juridiques :            │
│     Article L\d+-\d+, Art. R\d+-\d+, Section \d+,          │
│     Chapitre [IVX]+, etc.                                    │
│     → 1 article = 1 chunk                                    │
│                                                              │
│  2. ARTICLE TROP LONG (> 512 tokens)                         │
│     Sous-découpage par alinéas (retour à la ligne +          │
│     tiret/numéro/lettre). Chaque sous-chunk conserve         │
│     le titre de l'article en header pour le contexte.        │
│     Overlap de 50 tokens entre sous-chunks.                  │
│                                                              │
│  3. TEXTE NON STRUCTURÉ (fallback)                           │
│     Documents sans articles détectables (accords             │
│     d'entreprise mal structurés, etc.)                       │
│     → Découpage par paragraphe Markdown (##, ###)            │
│     → Si pas de structure Markdown : découpage par taille    │
│       ~512 tokens avec overlap 50, coupure en fin de phrase  │
│                                                              │
│  Règles strictes :                                           │
│  • Jamais de coupure au milieu d'un article                  │
│  • Jamais de coupure au milieu d'une phrase                  │
│  • Un chunk court (< 512 tokens) est préférable à un chunk  │
│    long qui mélange plusieurs articles                       │
│  • Plafond à 512 tokens (LLM et embeddings sont plus        │
│    performants sur des chunks précis et focalisés)           │
└─────────────┬───────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 4 — Génération des embeddings                        │
│                                                              │
│  A. Dense vectors (sémantique)                               │
│     • Modèle : Voyage AI voyage-law-2                        │
│     • Batching automatique via LlamaIndex                    │
│     • Retry avec backoff exponentiel sur 429 (rate limit)    │
│                                                              │
│  B. Sparse vectors (lexical / BM25)                          │
│     • Génération des sparse vectors pour chaque chunk        │
│     • Indexation native dans Qdrant (named vectors)          │
│     • Permet la recherche par mots-clés exacts               │
│       (numéros d'articles, noms propres, dates)              │
│                                                              │
│  Recherche hybride : ~70% dense / 30% sparse                │
│  (pondération à affiner selon les résultats)                 │
└─────────────┬───────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 5 — Indexation dans Qdrant                           │
│                                                              │
│  Chaque chunk est stocké comme un point Qdrant avec :        │
│  • Dense vector (voyage-law-2)                               │
│  • Sparse vector (BM25)                                      │
│  • Payload / métadonnées (voir section 5.5)                  │
│                                                              │
│  Collection : une collection unique par environnement        │
│  Le cloisonnement multi-tenant est assuré par le filtrage    │
│  sur organisation_id dans les métadonnées.                   │
│                                                              │
│  Écriture concurrente : Qdrant supporte nativement les       │
│  écritures parallèles — plusieurs utilisateurs peuvent       │
│  indexer des documents en même temps sans conflit.            │
└─────────────┬───────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 6 — Mise à jour du statut en PostgreSQL              │
│                                                              │
│  Succès → indexation_status = "indexed"                      │
│  Échec  → indexation_status = "error"                        │
│                                                              │
│  L'utilisateur voit le statut dans le tableau des documents. │
│  Un bouton "Réindexer" permet de relancer manuellement       │
│  l'indexation en cas d'erreur.                               │
│                                                              │
│  Le document reste téléchargeable depuis MinIO quel que      │
│  soit le statut d'indexation — upload et indexation sont      │
│  découplés.                                                  │
└─────────────────────────────────────────────────────────────┘
```

#### 5.4.2 Formats supportés et extraction

| Format | Bibliothèque | Extraction | Tableaux | Images |
|---|---|---|---|---|
| **PDF** (non scanné) | `pymupdf4llm` | Texte → Markdown (préserve titres, articles, listes) | Convertis en Markdown table | Ignorées |
| **DOCX** | `python-docx` | Texte → Markdown (titres, paragraphes) | Convertis en Markdown table | Ignorées |
| **TXT** | Lecture directe | Texte brut normalisé | N/A | N/A |
| **PDF scanné** | Non supporté (v1) | À ajouter ultérieurement (OCR via Tesseract ou service cloud) | — | — |

#### 5.4.3 Conversion en Markdown — justification

La conversion intermédiaire en Markdown avant le chunking est une **bonne pratique** pour plusieurs raisons :

- **Structure préservée** : les titres (`#`, `##`, `###`), listes numérotées et tableaux sont conservés dans un format lisible
- **Chunking intelligent** : le découpage peut s'appuyer sur les niveaux de titres Markdown pour respecter la structure logique du document
- **Meilleure compréhension** : les LLM et les modèles d'embedding performent mieux sur du Markdown structuré que sur du texte brut sans mise en forme
- **Nettoyage facilité** : les artefacts de formatage (polices, colonnes, mise en page) sont éliminés lors de la conversion

#### 5.4.4 Détection de doublons

Chaque document uploadé fait l'objet d'un **hash SHA-256** calculé sur le contenu brut du fichier. Ce hash est stocké en base de données et vérifié à chaque nouvel upload :

- Scope **organisation** : un doublon est détecté si un document avec le même hash existe dans la même organisation
- Scope **commun** : un doublon est détecté parmi les documents communs (organisation_id = NULL)
- En cas de doublon → erreur HTTP 409 avec le nom du document existant
- Un même fichier peut exister dans deux organisations différentes (pas de doublon cross-org)

#### 5.4.5 Gestion des erreurs et résilience

| Scénario | Comportement |
|---|---|
| Extraction de texte échoue (PDF corrompu, format non supporté) | `indexation_status = "error"`, document reste dans MinIO |
| API Voyage AI rate limit (429) | Retry avec backoff exponentiel (3 tentatives max) |
| Qdrant indisponible | `indexation_status = "error"`, retry possible via bouton "Réindexer" |
| Upload concurrent par plusieurs utilisateurs | Pas de conflit — chaque indexation est indépendante (paths MinIO uniques, IDs Qdrant uniques, transactions PostgreSQL séparées) |
| Document déjà indexé puis supprimé | Suppression des chunks Qdrant associés (filtre sur `document_id`) + suppression MinIO + suppression PostgreSQL |

#### 5.4.6 Exécution en tâche de fond

L'indexation est déclenchée automatiquement après chaque upload réussi via **BackgroundTask** de FastAPI. Ce choix est adapté au volume initial (quelques dizaines de documents par jour). Si le volume augmente significativement, migration vers un **worker asynchrone** (Celery ou ARQ avec Redis) pour :

- File d'attente persistante (survit aux redémarrages)
- Parallélisme configurable
- Monitoring et retry automatique
- Priorisation des tâches

### 5.5 Métadonnées obligatoires dans Qdrant

Chaque vecteur indexé dans Qdrant doit porter les métadonnées suivantes pour garantir le cloisonnement, la pertinence et la fiabilité juridique :

| Métadonnée | Description | Exemple |
|---|---|---|
| `organisation_id` | ID de l'organisation propriétaire (`common` pour les documents communs) | `org_abc123` / `common` |
| `document_id` | Référence au document source dans MinIO / PostgreSQL | `doc_xyz789` |
| `source_type` | Type juridique du document (26 types possibles) | `accord_entreprise`, `ccn`, `code_travail_l` |
| `norme_niveau` | Niveau dans la hiérarchie des normes (1-9) | `3` (Lois & Ordonnances) |
| `norme_poids` | Poids de pondération issu de la hiérarchie | `0.9` |
| `source_reference` | Référence précise (article, numéro d'arrêt, section) | `Article L1234-1`, `Cass. soc. 12/03/2024` |
| `date_entree_vigueur` | Date d'entrée en vigueur du texte | `2024-01-01` |
| `date_abrogation` | Date d'abrogation (null si actif) | `null` / `2023-12-31` |
| `statut` | État du texte juridique | `actif`, `modifié`, `abrogé` |
| `juridiction` | Juridiction applicable | `France`, `EU` |
| `articles_liés` | Liste des articles référencés / liés (renvois croisés) | `["L1234-2", "L1234-5"]` |

---

## 6. Chat — Assistant juridique

### 6.1 Interface conversationnelle

L'interface de chat reproduit le fonctionnement de ChatGPT :

- L'utilisateur ouvre une **nouvelle conversation** ou reprend une **conversation existante**
- Il pose une question en langage naturel
- AORIA RH répond avec une réponse sourcée
- L'utilisateur peut **continuer la conversation** (multi-tours, contexte maintenu)

### 6.2 Historique des conversations

- **Sidebar** listant les conversations passées (triées par date)
- Possibilité de **renommer** une conversation
- Possibilité de **supprimer** une conversation

### 6.3 Réponses sourcées

Chaque réponse générée affiche les **sources** utilisées :

- Nom du document source
- Référence (article de loi, section, page)
- Extrait pertinent le cas échéant

### 6.4 Pipeline de traitement des questions — Agent structuré

Le traitement de chaque question est orchestré par un **agent léger à étapes contraintes** (non autonome). Ce choix garantit des réponses juridiquement complètes tout en maîtrisant la latence et les coûts.

#### Architecture de l'agent

```
┌─────────────────────────────────────────────────────────────┐
│                    QUESTION UTILISATEUR                      │
└─────────────┬───────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 1 — Condensation (si multi-tours)                    │
│  Reformuler la question en intégrant le contexte            │
│  conversationnel → produire une question autonome           │
└─────────────┬───────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 2 — Classification & reformulation                   │
│  • Classifier le type de question (droit du travail,        │
│    convention collective, jurisprudence, etc.)               │
│  • Générer 2-3 variantes de la question :                   │
│    - langage courant                                        │
│    - terminologie juridique                                 │
│    - mots-clés spécifiques                                  │
└─────────────┬───────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 3 — Recherche hybride                                │
│  • Recherche sémantique (voyage-law-2) + BM25 (sparse)     │
│  • Filtrage Qdrant : organisation_id + common               │
│  • Filtrage : statut = actif                                │
│  • Top-k large : 20-30 résultats                            │
│  • Fusion des résultats via Reciprocal Rank Fusion (RRF)    │
└─────────────┬───────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 4 — Reranking                                        │
│  • Cross-encoder (Voyage AI rerank-2 ou Cohere Rerank)      │
│  • Réduction : 20-30 → 5-8 chunks les plus pertinents       │
└─────────────┬───────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 5 — Évaluation de la pertinence                      │
│  • Le LLM évalue si les chunks récupérés couvrent           │
│    suffisamment la question (score de confiance)             │
│  • SI score insuffisant ET itération < 2 :                  │
│    → retour à l'ÉTAPE 2 avec reformulation alternative      │
│  • SI score insuffisant ET itération = 2 :                  │
│    → continuer avec les meilleurs résultats disponibles      │
│    → signaler dans la réponse que l'info est incomplète     │
└─────────────┬───────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 6 — Résolution des références croisées               │
│  • Scanner les chunks pour détecter les renvois             │
│    (regex : article L\d+, R\d+, etc.)                       │
│  • Récupérer les articles référencés depuis Qdrant          │
│  • Ajouter au contexte                                      │
└─────────────┬───────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 7 — Génération de la réponse                         │
│  • Construction du prompt avec : question + chunks +        │
│    références croisées + historique condensé                 │
│  • Génération via gpt-5-mini                                │
│  • Citation obligatoire des sources dans la réponse         │
│  • Si info incomplète : mention explicite dans la réponse   │
└─────────────┬───────────────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────────────┐
│               RÉPONSE SOURCÉE À L'UTILISATEUR               │
└─────────────────────────────────────────────────────────────┘
```

#### Garde-fous de performance

La vitesse de réponse est critique pour l'expérience utilisateur. Les contraintes suivantes sont **non négociables** :

| Contrainte | Valeur | Description |
|---|---|---|
| **Max itérations de re-recherche** | 2 | Si après 2 tentatives le retrieval est insuffisant, l'agent poursuit avec les meilleurs résultats et signale l'incomplétude |
| **Timeout global de l'agent** | 15 secondes | Au-delà, l'agent génère la réponse avec ce qu'il a, sans itération supplémentaire |
| **Timeout par étape** | 3 secondes | Chaque étape individuelle a un timeout strict |
| **Pas de boucle ouverte** | — | L'agent suit un chemin linéaire avec un seul point de branchement conditionnel (étape 5). Aucune boucle libre ou récursion non bornée |
| **Streaming** | Activé | La réponse finale (étape 7) est streamée en temps réel à l'utilisateur pour réduire le temps perçu |

#### Cas nominal vs cas dégradé

| Scénario | Étapes exécutées | Temps estimé |
|---|---|---|
| **Cas nominal** (retrieval pertinent du 1er coup) | 1 → 2 → 3 → 4 → 5 → 6 → 7 | ~5-8 secondes |
| **1 re-recherche** (retrieval initial insuffisant) | 1 → 2 → 3 → 4 → 5 → 2 → 3 → 4 → 5 → 6 → 7 | ~10-13 secondes |
| **Timeout / échec** (aucun résultat pertinent) | Interruption + réponse dégradée | ≤ 15 secondes |

### 6.6 Points d'attention RAG juridique

Le domaine juridique impose des contraintes spécifiques que le pipeline RAG doit impérativement prendre en compte :

#### 6.6.1 Sémantique juridique vs langage courant

Les utilisateurs formulent leurs questions en langage courant, tandis que les textes juridiques utilisent une terminologie technique. Le pipeline doit inclure une étape de **reformulation / enrichissement de la requête** par le LLM avant la recherche vectorielle pour combler cet écart.

> Exemple : « mon patron peut me virer sans raison ? » → recherche sur « rupture du contrat à durée indéterminée », « licenciement sans cause réelle et sérieuse »

#### 6.6.2 Exceptions et règles complémentaires

Une disposition juridique peut énoncer une règle générale, tandis qu'une exception ou limitation est définie dans un autre article. La recherche vectorielle risque de récupérer la règle principale sans l'exception, produisant une réponse **juridiquement incorrecte ou incomplète**.

> Exemple : Article A énonce la règle générale. Article B contient l'exception. Seul l'article A est récupéré → réponse erronée.

**Stratégie** : utiliser les métadonnées `articles_liés` pour récupérer automatiquement les articles référencés en complément du top-k.

#### 6.6.3 Références croisées entre articles

Les textes juridiques comportent de nombreux renvois internes. Un article peut être incompréhensible ou incomplet sans l'article cité. Le pipeline doit détecter et résoudre ces renvois pour fournir un contexte complet au LLM.

> Exemple : « Conformément à l'article 1240 du Code civil… » → l'article cité doit être inclus dans le contexte.

#### 6.6.4 Chunking juridique

Un découpage fixe par nombre de tokens peut séparer des éléments juridiquement liés (alinéas, exceptions, définitions). Le chunking doit respecter la structure logique du droit (détail complet en **section 5.4.1, étape 3**) :

- **Priorité 1 — Chunk par article complet** (méthode privilégiée). Détection par regex : `Article L\d+-\d+`, `Art. R\d+-\d+`, `Section \d+`, `Chapitre [IVX]+`
- **Priorité 2 — Sous-découpage par alinéas** si l'article dépasse 512 tokens. Chaque sous-chunk conserve le titre de l'article en header. Overlap de 50 tokens entre sous-chunks.
- **Priorité 3 — Fallback par paragraphe** pour les documents non structurés. Découpage par titres Markdown ou par taille ~512 tokens avec coupure en fin de phrase.
- **Règles strictes** : jamais de coupure au milieu d'un article ou d'une phrase. Un chunk court est préférable à un chunk qui mélange plusieurs articles. Plafond 512 tokens.

#### 6.6.5 Ranking et reranking

Le top-k retrieval classique peut introduire du bruit. Une réponse juridique dépend souvent de **plusieurs textes complémentaires** (article principal + exceptions + précisions). Le pipeline doit intégrer une étape de **reranking** pour prioriser les résultats les plus pertinents et complémentaires.

#### 6.6.6 Versioning et temporalité du droit

Un même article peut exister sous plusieurs versions (modification, abrogation). Le modèle d'embedding ne distingue pas automatiquement les dates d'application. Le pipeline doit :

- Filtrer par défaut sur les textes au **statut `actif`** (via métadonnées Qdrant)
- Permettre une recherche historique explicite si nécessaire
- Ne jamais retourner un texte abrogé sans avertissement

### 6.7 Optimisations du pipeline RAG

#### 6.7.1 Recherche hybride (sémantique + lexicale)

La recherche vectorielle seule rate les références exactes (numéros d'articles, noms propres, dates). Le pipeline combine deux approches :

- **Recherche sémantique** via embeddings `voyage-law-2` dans Qdrant
- **Recherche lexicale BM25** via sparse vectors (supporté nativement par Qdrant)
- **Pondération** : ~70% sémantique / 30% lexicale (à affiner selon les résultats)

#### 6.7.2 Query expansion / reformulation

Avant la recherche vectorielle, le LLM reformule la question de l'utilisateur en **2-3 variantes complémentaires** :

1. Version en **langage courant** (reformulation clarifiée)
2. Version en **terminologie juridique** (termes techniques, références légales)
3. Version en **mots-clés spécifiques** (concepts, articles connus)

La recherche est lancée sur chaque variante, puis les résultats sont fusionnés via **Reciprocal Rank Fusion (RRF)** pour un classement optimal.

#### 6.7.3 Reranking en 2 passes

- **Passe 1** : retrieval large — top-k élevé (20-30 résultats) depuis Qdrant
- **Passe 2** : reranking par un cross-encoder (Voyage AI `rerank-2` ou Cohere Rerank) pour ne conserver que les **5-8 chunks les plus pertinents**

Ce reranking est particulièrement critique en juridique où la nuance entre un article pertinent et un article voisin mais hors sujet est fine.

#### 6.7.4 Résolution automatique des références croisées

Après le retrieval, le pipeline scanne les chunks récupérés pour détecter les renvois internes :

- Détection par regex des références (ex : `article L\d+-\d+`, `article R\d+-\d+`, `article \d+`)
- Récupération automatique des articles référencés depuis Qdrant (via métadonnée `source_reference`)
- Injection de ces articles complémentaires dans le contexte envoyé au LLM

#### 6.7.5 Condensation du contexte conversationnel

En conversation multi-tours, le pipeline ne renvoie pas tout l'historique au RAG. À chaque nouveau message :

- Le LLM **condense** la dernière question en intégrant le contexte des échanges précédents
- Produit une **question autonome** (standalone question)
- Cette question condensée est utilisée pour la recherche vectorielle

> Exemple :
> - Tour 1 : « Quelles sont les règles du licenciement économique ? »
> - Tour 2 : « Et pour les entreprises de moins de 50 salariés ? »
> - Question condensée : « Quelles sont les règles spécifiques du licenciement économique pour les entreprises de moins de 50 salariés ? »

### 6.8 Feedback et monitoring

#### 6.8.1 Feedback utilisateur

Chaque réponse du chat propose un système de **notation** (pouce haut / pouce bas) permettant :

- D'identifier les réponses insatisfaisantes
- De détecter les lacunes dans la base documentaire
- D'alimenter un dataset d'amélioration continue

#### 6.8.2 Métriques à suivre

| Métrique | Description | Objectif |
|---|---|---|
| **Score de retrieval** | Nombre de chunks récupérés avec un score > seuil par question | Mesurer la couverture de la base documentaire |
| **Taux de satisfaction** | Ratio pouces haut / pouces bas | > 85% de pouces haut |
| **Questions sans résultat** | Questions où le RAG ne trouve aucun chunk pertinent | Identifier les trous documentaires à combler |
| **Coût par question** | Tokens consommés (input + output) par question | Optimisation budgétaire, suivi par plan tarifaire |

### 6.10 Disclaimer juridique

Un avertissement permanent informe l'utilisateur que :

- Les réponses sont générées par intelligence artificielle
- Elles ne constituent pas un avis juridique professionnel
- Elles ne remplacent pas la consultation d'un avocat ou d'un juriste
- AORIA RH ne peut être tenu responsable des décisions prises sur la base de ces réponses

---

## 7. Interface utilisateur

### 7.1 Layout général

```
┌──────────────────────────────────────────────────────┐
│  SIDEBAR GAUCHE          │       ZONE PRINCIPALE     │
│                          │                           │
│  [Logo AORIA RH]        │   (Chat / Documents /     │
│  [Sélecteur orga ▼]     │    Organisation / Compte)  │
│                          │                           │
│  ── Navigation ──        │                           │
│  💬 Chat                 │                           │
│  📄 Documents            │                           │
│  🏢 Organisation         │                           │
│  👤 Mon compte           │                           │
│                          │                           │
│  ── Conversations ──     │                           │
│  Conv. récente 1         │                           │
│  Conv. récente 2         │                           │
│  Conv. récente 3         │                           │
│                          │                           │
│  [🌙 Theme toggle]      │                           │
└──────────────────────────────────────────────────────┘
```

### 7.2 Thème

- **Thème clair** (light) par défaut
- **Thème sombre** (dark)
- Toggle accessible depuis la sidebar ou les paramètres du compte
- Implémentation via Tailwind CSS (`dark:` classes)

### 7.3 Pages principales

| Page | Accès | Description |
|---|---|---|
| **Chat** | Tous les utilisateurs | Interface conversationnelle avec l'assistant IA |
| **Documents** | Tous les utilisateurs | Gestion documentaire de l'organisation en cours |
| **Organisation** | Managers | Informations de l'organisation + gestion des membres |
| **Mon compte** | Tous les utilisateurs | Informations personnelles, email, offre souscrite |
| **Back-office Admin** | Admins uniquement | Upload documents communs, supervision |

---

## 8. Page "Mon compte"

- Informations personnelles (nom, prénom, email)
- Offre / abonnement en cours
- Gestion du mot de passe
- Préférences (thème, langue)
- Historique de facturation

---

## 9. Back-office Admin (AORIA RH)

Espace réservé au personnel AORIA RH (rôle Admin) :

- **Gestion des documents communs** : upload, modification, suppression des documents partagés avec toutes les organisations (Code du travail, conventions collectives, jurisprudence)
- **Supervision** : vue globale sur les organisations, utilisateurs, usage

---

## 10. Monétisation

> **TODO** — À détailler ultérieurement.
>
> Points à définir :
> - Modèle de tarification (freemium, plans payants)
> - Limites par plan (nombre de questions/mois, nombre de documents, nombre d'utilisateurs, nombre d'organisations)
> - Intégration Stripe pour la gestion des abonnements
> - Gestion des dépassements de quota

---

## 11. Tests

### 11.1 Tests unitaires

L'ensemble du projet doit être couvert par des tests unitaires :

**Backend (Python / FastAPI) :**
- Framework : `pytest`
- Couverture cible : > 80%
- Périmètre :
  - Logique métier (droits, cloisonnement, gestion des organisations)
  - API endpoints (authentification, CRUD documents, CRUD organisations, invitations)
  - Pipeline RAG (chunking, enrichissement de requête, filtrage par metadata)
  - Cloisonnement multi-tenant (vérifier qu'un utilisateur ne peut jamais accéder aux données d'une autre organisation)

**Frontend (Next.js / React) :**
- Framework : `Jest` + `React Testing Library`
- Périmètre :
  - Composants UI (sélecteur d'organisation, chat, gestion documentaire)
  - Logique de routage et de gestion des rôles côté client
  - Thème light/dark

---

## 12. Exigences non fonctionnelles

### 11.1 Sécurité

- Authentification sécurisée (JWT, sessions, OAuth)
- Cloisonnement strict des données entre organisations (niveau applicatif ET vectoriel)
- Chiffrement des données sensibles au repos et en transit (HTTPS, chiffrement BDD)
- Conformité RGPD (données hébergées en Europe, droit à l'effacement, export des données)

### 11.2 Performance

- Temps de réponse du chat < 5 secondes (hors latence LLM)
- Recherche vectorielle Qdrant < 500ms
- Support de la montée en charge (architecture stateless, scaling horizontal)

### 11.3 Disponibilité

- SLA cible : 99.5%
- Monitoring et alerting
- Sauvegardes automatiques (BDD PostgreSQL + MinIO + Qdrant)

### 11.4 UX / Accessibilité

- Responsive design (desktop prioritaire, mobile adapté)
- Interface intuitive, onboarding simple
- Accessibilité WCAG 2.1 niveau AA

---

## 13. Récapitulatif des TODO

| # | Sujet | Description |
|---|---|---|
| 1 | **Pipeline d'ingestion RAG** | Définir le processus complet : extraction texte → chunking → embedding (`voyage-law-2`) → indexation Qdrant avec metadata |
| 2 | **Pipeline de traitement des questions** | Définir le processus : question → enrichissement → recherche vectorielle → construction prompt → génération réponse (`gpt-5-mini`) |
| 3 | **Monétisation** | Définir les plans tarifaires, limites, intégration Stripe |

---

*Document généré le 24/02/2026 — Version 1.0*
