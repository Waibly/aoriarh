# Pipeline d'ingestion documentaire — AORIA RH

## Vue d'ensemble

Ce document décrit le processus complet depuis l'upload d'un document par l'utilisateur jusqu'à son insertion dans Qdrant (base vectorielle).

## Schéma du pipeline

```
UTILISATEUR                         BACKEND (FastAPI)
     |                                     |
     |  POST /documents (multipart)        |
     |------------------------------------>|
     |                                     |
     |                              1. VALIDATION
     |                              - Format (PDF, DOCX, TXT)
     |                              - Taille (max 10 Mo)
     |                              - Hash SHA-256 anti-doublon
     |                                     |
     |                              2. STOCKAGE FICHIER
     |                              - Upload vers MinIO (S3)
     |                              - Chemin : {org_id}/{uuid}_{filename}
     |                                     |
     |                              3. ENREGISTREMENT DB
     |                              - Document créé en PostgreSQL
     |                              - Status : "pending"
     |                                     |
     |                              4. DISPATCH ASYNC
     |                              - Job envoyé via Redis (ARQ)
     |                              - Réponse HTTP immédiate
     |  <-- 201 Created ------------------|
     |                                     |
     |                                     |
     |  WORKER (ARQ)                       |
     |                                     |
     |                              5. DOWNLOAD
     |                              - Récupération depuis MinIO
     |                              - Progress : 0% -> 5%
     |                                     |
     |                              6. EXTRACTION TEXTE
     |                              - PDF : pymupdf4llm (Markdown)    <-- [OPTI] Fast path > 2 Mo
     |                              - DOCX : python-docx (Markdown)
     |                              - TXT : décodage multi-encodages
     |                              - Progress : 5% -> 10%
     |                                     |
     |                              7. NETTOYAGE
     |                              - Suppression caractères de contrôle
     |                              - Suppression en-têtes/pieds de page
     |                              - Normalisation typographique
     |                              - Fusion lignes coupées
     |                                     |
     |                              8. CHUNKING                       <-- [OPTI] 512 -> 1024 tokens
     |                              - Stratégie 1 : Articles juridiques
     |                              - Stratégie 2 : Headings Markdown
     |                              - Stratégie 3 : Phrases (fallback)
     |                              - Overlap : 100 tokens
     |                              - Progress : 10% -> 15%
     |                                     |
     |                              9. EMBEDDINGS DENSES              <-- [OPTI] 4 requêtes concurrentes
     |                              - API Voyage AI (voyage-law-2)
     |                              - Vecteurs 1024 dimensions
     |                              - Batchs de 128 chunks
     |                              - Progress : 15% -> 80%
     |                                     |
     |                              10. VECTEURS SPARSE (BM25)
     |                              - fastembed local
     |                              - Progress : 80% -> 85%
     |                                     |
     |                              11. UPSERT QDRANT
     |                              - Collection : aoriarh_documents
     |                              - Vecteurs : dense + sparse-bm25
     |                              - Payload : texte, org_id, doc_id,
     |                                source_type, norme_niveau, norme_poids
     |                              - Batchs de 100 points
     |                              - Progress : 85% -> 95%
     |                                     |
     |                              12. NETTOYAGE ANCIENS CHUNKS
     |                              - Suppression des anciens points Qdrant
     |                              - Insert-then-swap (zéro downtime)
     |                                     |
     |                              13. FINALISATION
     |                              - Status : "indexed"
     |                              - chunk_count + durée enregistrés
     |                              - Progress : 100%
     |                                     |
     |  (polling /documents/{id})          |
     |------------------------------------>|
     |  <-- status: "indexed" ------------|
```

## Architecture des composants

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Frontend    │────>│  FastAPI     │────>│  Redis      │
│  (Next.js)  │     │  (API)       │     │  (Queue)    │
└─────────────┘     └──────┬───────┘     └──────┬──────┘
                           │                     │
                    ┌──────┴───────┐     ┌──────┴──────┐
                    │  MinIO       │     │  ARQ Worker  │
                    │  (Stockage)  │     │  (Ingestion) │
                    └──────────────┘     └──────┬──────┘
                                                │
                    ┌──────────────┐     ┌──────┴──────┐
                    │  PostgreSQL  │<────│  Voyage AI  │
                    │  (Metadata)  │     │  (Embeddings)│
                    └──────────────┘     └──────┬──────┘
                                                │
                                         ┌──────┴──────┐
                                         │  Qdrant     │
                                         │  (Vecteurs) │
                                         └─────────────┘
```

## Détail des étapes

### 1-4. Upload et dispatch (synchrone)

**Fichiers** : `api/documents.py`, `services/document_service.py`, `rag/tasks.py`

L'API reçoit le fichier, le valide, le stocke dans MinIO, crée l'enregistrement en base PostgreSQL avec le status `pending`, puis envoie un job d'ingestion dans la queue Redis via ARQ. La réponse HTTP est renvoyée immédiatement — l'indexation est asynchrone.

**Contrôles** :
- Formats acceptés : PDF, DOCX, TXT
- Taille max : 10 Mo
- Dédoublonnage par hash SHA-256 (par organisation)
- Type de source validé contre la hiérarchie des normes

### 5-6. Download et extraction (worker)

**Fichiers** : `worker.py`, `rag/ingestion.py`, `rag/text_extractor.py`

Le worker télécharge le fichier depuis MinIO et extrait le texte selon le format :

| Format | Méthode | Sortie |
|--------|---------|--------|
| PDF (< 2 Mo) | `pymupdf4llm.to_markdown()` | Markdown structuré |
| PDF (> 2 Mo) | `pymupdf.page.get_text("text")` | Texte brut (rapide) |
| DOCX | `python-docx` avec parsing styles | Markdown (headings, listes, tableaux) |
| TXT | Décodage UTF-8 / Latin-1 / CP1252 | Texte brut |

### 7. Nettoyage

**Fichier** : `rag/text_cleaner.py`

- Suppression caractères de contrôle et zero-width
- Suppression headers/footers répétés ("Page X sur Y", numéros de page isolés)
- Normalisation typographique (guillemets, tirets, espaces insécables)
- Fusion lignes cassées (word wrap PDF)
- Normalisation espaces multiples et lignes vides

### 8. Chunking

**Fichiers** : `rag/chunker.py`, `rag/config.py`

Le `LegalChunker` applique 3 stratégies en cascade :

1. **Articles juridiques** (prioritaire) : découpe sur les patterns `Article L1234-5`, `Section 1`, `Chapitre IV`, `Titre II`. Adapté au Code du travail et textes réglementaires.
2. **Headings Markdown** : découpe sur `#`, `##`, `###`, `####`. Adapté aux documents structurés.
3. **Phrases** (fallback) : découpe par paragraphes puis phrases.

Si une section dépasse `CHUNK_SIZE` tokens, elle est re-découpée par phrases. L'en-tête de la section (titre d'article) est répété dans chaque sous-chunk pour conserver le contexte.

**Paramètres** :
- `CHUNK_SIZE` : 1024 tokens
- `CHUNK_OVERLAP` : 100 tokens
- Tokenizer : `cl100k_base` (tiktoken)

### 9. Embeddings denses

**Fichier** : `rag/ingestion.py`

Appel à l'API Voyage AI avec le modèle `voyage-law-2` (spécialisé juridique) :
- Vecteurs de 1024 dimensions
- Batchs de 128 chunks (max API)
- 4 requêtes concurrentes (semaphore)
- Retry automatique sur rate limit (429) avec backoff exponentiel

### 10. Vecteurs sparse (BM25)

**Fichier** : `rag/ingestion.py`

Génération locale de vecteurs sparse via `fastembed` pour la recherche hybride (dense + BM25). Pas d'appel API — calcul CPU local.

### 11. Upsert Qdrant

**Fichiers** : `rag/ingestion.py`, `rag/qdrant_store.py`

Chaque chunk devient un point Qdrant avec :
- **Vecteurs** : `dense` (Voyage AI 1024d) + `sparse-bm25` (fastembed)
- **Payload** : texte, `organisation_id`, `document_id`, `doc_name`, `source_type`, `norme_niveau`, `norme_poids`, `chunk_index`

**Index Qdrant** pour le filtrage : `organisation_id`, `document_id`, `source_type`.

Upsert par batchs de 100 points.

### 12. Insert-then-swap

Lors d'une ré-indexation, les nouveaux chunks sont insérés **avant** la suppression des anciens. Cela garantit qu'il n'y a jamais de moment où le document n'a aucun chunk dans Qdrant (zéro downtime pour la recherche).

## Optimisations apportées

### 1. Extraction rapide des gros PDFs

**Problème** : `pymupdf4llm.to_markdown()` effectue une analyse de layout coûteuse (détection colonnes, tableaux, etc.). Pour un PDF de 7.5 Mo comme le Code du travail, cette étape prenait plusieurs minutes.

**Solution** : Pour les PDFs > 2 Mo, on utilise `pymupdf.page.get_text("text")` qui extrait le texte brut sans analyse de layout — beaucoup plus rapide.

**Fichier** : `rag/text_extractor.py` — seuil configurable via `_LARGE_PDF_THRESHOLD`.

### 2. Taille des chunks doublée (512 -> 1024 tokens)

**Problème** : Avec `CHUNK_SIZE = 512`, le Code du travail produisait ~15 400 chunks, nécessitant 121 appels API Voyage AI.

**Solution** : `CHUNK_SIZE = 1024` et `CHUNK_OVERLAP = 100` (proportionnel). Cela divise par ~2 le nombre de chunks (~7 700) et donc le nombre d'appels API (~60).

**Impact** : 1024 tokens reste adapté pour le retrieval juridique — la plupart des articles tiennent dans cette taille, et Voyage AI supporte jusqu'à 16K tokens en entrée.

**Fichier** : `rag/config.py`

### 3. Embeddings concurrents (x4)

**Problème** : Les 121 appels API Voyage AI étaient effectués séquentiellement. À ~2s par appel, cela représentait ~240s sur les 312s totales.

**Solution** : Exécution de 4 requêtes Voyage AI en parallèle via `asyncio.Semaphore`. L'ordre des résultats est préservé grâce à un tableau indexé.

**Impact estimé** : Temps embeddings divisé par ~3-4x.

**Fichier** : `rag/ingestion.py` — constante `EMBEDDING_CONCURRENCY`.

### Résultat combiné (estimé)

Pour le Code du travail (7.5 Mo) :

| Métrique | Avant | Après |
|----------|-------|-------|
| Chunks produits | ~15 400 | ~7 700 |
| Appels Voyage AI | 121 (séquentiels) | ~60 (4 en parallèle) |
| Temps extraction PDF | > 60s (layout analysis) | ~5s (texte brut) |
| **Temps total estimé** | **~312s** | **~40-60s** |

## Configuration

| Paramètre | Valeur | Fichier |
|-----------|--------|---------|
| `CHUNK_SIZE` | 1024 tokens | `rag/config.py` |
| `CHUNK_OVERLAP` | 100 tokens | `rag/config.py` |
| `EMBEDDING_BATCH_SIZE` | 128 | `rag/ingestion.py` |
| `EMBEDDING_CONCURRENCY` | 4 | `rag/ingestion.py` |
| `_LARGE_PDF_THRESHOLD` | 2 Mo | `rag/text_extractor.py` |
| `EMBEDDING_MODEL` | `voyage-law-2` | `rag/config.py` |
| `DENSE_VECTOR_SIZE` | 1024 | `rag/qdrant_store.py` |
| `MAX_FILE_SIZE` | 10 Mo | `services/document_service.py` |
| `job_timeout` | 1800s (30 min) | `worker.py` |
