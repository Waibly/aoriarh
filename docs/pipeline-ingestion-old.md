# Pipeline d'Ingestion de Documents

## Vue d'ensemble

Le systeme d'ingestion est concu pour traiter des **documents juridiques francais** (PDF). Il transforme un fichier PDF brut en chunks semantiques indexes dans une base vectorielle, prets pour la recherche hybride (dense + sparse).

L'orchestration des etapes est assuree par **LangGraph** (workflow en graphe).

---

## Schema du processus

```
                         UPLOAD
                    POST /ingest/pdf
                   (fichiers PDF + metadata)
                           |
                           v
              +----------------------------+
              |  ETAPE 1 - SANITIZATION    |
              |  & SAUVEGARDE FICHIER      |
              |                            |
              |  - Nettoyage nom fichier   |
              |  - Ajout horodatage unique |
              |  - Sauvegarde dans         |
              |    /documents/             |
              +----------------------------+
                           |
                           v
              +----------------------------+
              |  ETAPE 2 - EXTRACTION      |
              |  DU CONTENU PDF            |
              |                            |
              |  - Conversion PDF -> MD    |
              |    via Docling             |
              |  - Detection qualite texte |
              |  - Fallback OCR Tesseract  |
              |    si document scanne      |
              |  - Nettoyage cesures       |
              |  - Mapping des pages       |
              +----------------------------+
                           |
                           v
              +----------------------------+
              |  ETAPE 3 - ENRICHISSEMENT  |
              |  METADATA PAR LLM         |
              |                            |
              |  - Identification du nom   |
              |    exact du document       |
              |  - Classification dans la  |
              |    hierarchie juridique    |
              |  - Typage Bloc Macron      |
              |  - Regles de derogation    |
              |  - Calcul poids hierarchie |
              +----------------------------+
                           |
                           v
              +----------------------------+
              |  ETAPE 4 - CHUNKING        |
              |                            |
              |  1. Decoupage par en-tetes |
              |     Markdown (##)          |
              |  2. Sous-decoupage         |
              |     recursif :             |
              |     - Taille : 1024 chars  |
              |     - Overlap : 136 chars  |
              |  3. Propagation metadata   |
              |     sur chaque chunk       |
              +----------------------------+
                           |
                           v
              +----------------------------+
              |  ETAPE 5 - EMBEDDING       |
              |  & STOCKAGE                |
              |                            |
              |  - Embedding dense :       |
              |    VoyageAI (1024 dims)    |
              |  - Embedding sparse :      |
              |    SPLADE legal francais   |
              |  - Stockage dans Qdrant    |
              |    avec metadata enrichies |
              +----------------------------+
                           |
                           v
                  +------------------+
                  |     QDRANT       |
                  |  Base Vectorielle|
                  |                  |
                  |  Collection :    |
                  |  "documents"     |
                  +------------------+
```

---

## Detail des technologies par etape

| Etape | Composant | Technologie | Detail |
|-------|-----------|-------------|--------|
| **Upload** | API | FastAPI | Endpoint `POST /ingest/pdf` (multipart/form-data) |
| **1** | Sanitization | Python stdlib | Normalisation Unicode, suppression caracteres speciaux |
| **2** | Extraction PDF | Docling v2.48 | Conversion PDF vers Markdown structure |
| **2** | OCR (fallback) | Tesseract | Langue francaise, pleine page, GPU si dispo |
| **3** | Enrichissement | Claude Sonnet 4 | Classification juridique via LLM (temp=0.1) |
| **4** | Chunking headers | LangChain `MarkdownHeaderTextSplitter` | Decoupage structurel par titres |
| **4** | Chunking texte | LangChain `RecursiveCharacterTextSplitter` | 1024 chars / 136 overlap |
| **5** | Embedding dense | VoyageAI `voyage-3-large` | Vecteurs 1024 dimensions, distance cosinus |
| **5** | Embedding sparse | SPLADE `maastrichtlawtech/splade-legal-french` | Vecteurs creux specialises juridique FR |
| **5** | Stockage | Qdrant | HNSW index (m=32, ef=256), multi-vecteurs |
| **Orchestration** | Workflow | LangGraph | Graphe sequentiel 5 noeuds |
| **Infra** | Conteneurs | Docker + CUDA 11.8 | GPU pour OCR et SPLADE |

---

## Structure de stockage dans Qdrant

Chaque chunk est stocke comme un **point** avec la structure suivante :

```
Point {
  id: UUID unique

  vectors: {
    "dense":  [float x 1024]     // VoyageAI
    "sparse": {indices, values}   // SPLADE
  }

  payload: {
    "page_content": "texte du chunk...",
    "metadata": {
      "document_name":     "Nom exact du document",
      "category":          "loi | accord_branche | ccn | ...",
      "priority":          1-9 (hierarchie juridique),
      "hierarchy_weight":  float (poids pour le ranking),
      "bloc_macron_type":  "bloc_1 | bloc_2 | bloc_3 | null",
      "derogation_rules":  "AUCUNE | SOCLE_MINIMAL | ...",
      "scope":             "common | enterprise",
      "original_filename": "document_original.pdf",
      "saved_filename":    "20241201_143022_document.pdf"
    }
  }
}
```

---

## Classification juridique (9 niveaux)

Le LLM classe chaque document dans la hierarchie suivante :

| Priorite | Categorie | Description |
|----------|-----------|-------------|
| 1 | `loi` | Lois et codes |
| 2 | `jurisprudence` | Decisions de justice |
| 3 | `reglementaire` | Decrets, arretes |
| 4 | `accord_branche` | Accords de branche |
| 5 | `ccn` | Conventions collectives nationales |
| 6 | `accord_entreprise` | Accords d'entreprise |
| 7 | `usage` | Usages et pratiques |
| 8 | `contrat` | Contrats individuels |
| 9 | `autre` | Autres documents |

Les **Blocs Macron** (bloc_1, bloc_2, bloc_3) affinent le classement pour les accords collectifs et determinent les regles de derogation entre niveaux.

---

## Parametres de configuration cles

```
LLM :           claude-sonnet-4-20250514 / temperature=0.1 / max_tokens=4096
Embedding :     voyage-3-large / 1024 dimensions
Chunks :        1024 caracteres / 136 overlap
SPLADE :        max_length=512 tokens
Qdrant HNSW :   m=32 / ef_construct=256
Score seuil :   0.35 (pour la recherche)
Max resultats : 8 documents
```

---

## Infrastructure (Docker Compose)

```
+------------------+       +------------------+
|   api            |       |   qdrant         |
|   (FastAPI)      |<----->|   (Vector DB)    |
|   Port: 8000     |       |   Port: 6333     |
|   GPU: CUDA 11.8 |       |   Port: 6334     |
+------------------+       +------------------+
        |
        v
  /documents/
  (fichiers PDF sauvegardes)
```

**Variables d'environnement requises :**
- `ANTHROPIC_API_KEY` - Cle API pour Claude (enrichissement metadata)
- `VOYAGE_API_KEY` - Cle API pour VoyageAI (embeddings denses)
- `QDRANT_HOST` / `QDRANT_PORT` - Connexion Qdrant

---

## Fichiers source principaux

| Fichier | Role |
|---------|------|
| `api/main.py` | Endpoints API (upload, health, chat) |
| `api/services/ingestion/builder.py` | Construction du graphe LangGraph |
| `api/services/ingestion/nodes.py` | Les 5 etapes de la pipeline |
| `api/services/ingestion/utils.py` | Utilitaires (sanitization, fichiers) |
| `api/services/vector_store_service.py` | Gestion collection Qdrant |
| `api/services/sparse_embedder.py` | Embedding SPLADE custom |
| `api/services/config.py` | Configuration globale |
| `api/docker-compose.yml` | Infrastructure conteneurs |
| `api/Dockerfile` | Image Docker (Python + CUDA + Tesseract) |
