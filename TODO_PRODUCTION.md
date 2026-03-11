# AORIA RH — Guide de déploiement & Plan de mise en production

> Audit réalisé le 27/02/2026
> Statut global : **NON PRET pour la production**

---

## Table des matières

1. [Configuration de l'environnement](#1-configuration-de-lenvironnement)
2. [Lancer le projet en développement](#2-lancer-le-projet-en-développement)
3. [Déployer en production](#3-déployer-en-production)
4. [Dimensionnement serveur & workers](#4-dimensionnement-serveur--workers)
5. [Corrections par criticité](#5-corrections-par-criticité)
6. [Checklist de déploiement](#6-checklist-de-déploiement)

---

## 1. Configuration de l'environnement

### 1.1 Backend — `backend/.env`

Le backend utilise Pydantic Settings qui charge automatiquement le fichier `.env`.
Un template est disponible dans `backend/.env.example`.

```bash
cp backend/.env.example backend/.env
```

**Variables obligatoires (l'app refuse de démarrer sans) :**

| Variable | Description | Génération |
|----------|-------------|------------|
| `POSTGRES_PASSWORD` | Mot de passe PostgreSQL | Choisir un mot de passe fort (20+ chars) |
| `MINIO_ACCESS_KEY` | Clé d'accès MinIO | Choisir un identifiant (pas `minioadmin`) |
| `MINIO_SECRET_KEY` | Secret MinIO | Choisir un secret fort (20+ chars) |
| `SECRET_KEY` | Clé de signature JWT | `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `OPENAI_API_KEY` | Clé API OpenAI | Depuis [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| `VOYAGE_API_KEY` | Clé API Voyage AI | Depuis [dashboard.voyageai.com](https://dashboard.voyageai.com) |
| `BREVO_API_KEY` | Clé API Brevo (emails) | Depuis le dashboard Brevo |
| `ADMIN_PASSWORD` | Mot de passe du compte admin initial | Min 16 chars, doit contenir majuscule + chiffre + spécial |

**Validations automatiques au démarrage :**

- `SECRET_KEY` : rejeté si < 32 caractères ou si valeur connue faible (`dev-secret-key`, `changeme`, `secret`)
- `ADMIN_PASSWORD` : rejeté si < 16 caractères ou si valeur connue faible (`admin123`, `password`, `changeme`)
- Toute variable obligatoire manquante provoque un crash immédiat avec message explicite

**Variables avec valeurs par défaut (modifiables) :**

| Variable | Défaut | Notes |
|----------|--------|-------|
| `POSTGRES_HOST` | `localhost` | `postgres` en Docker |
| `POSTGRES_PORT` | `5432` | |
| `POSTGRES_DB` | `aoriarh` | |
| `POSTGRES_USER` | `aoriarh` | |
| `QDRANT_HOST` | `localhost` | `qdrant` en Docker |
| `QDRANT_PORT` | `6333` | |
| `MINIO_ENDPOINT` | `localhost:9000` | `minio:9000` en Docker |
| `MINIO_BUCKET` | `aoriarh-documents` | |
| `MINIO_USE_SSL` | `false` | `true` en production |
| `LLM_MODEL` | `gpt-5-mini` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | |
| `ALGORITHM` | `HS256` | |
| `ADMIN_EMAIL` | `hello@aoriarh.fr` | |
| `FRONTEND_URL` | `http://localhost:3000` | URL de prod en production |
| `BACKEND_CORS_ORIGINS` | `["http://localhost:3000"]` | URL de prod en production |
| `STRIPE_SECRET_KEY` | _(vide)_ | Optionnel tant que Stripe n'est pas activé |
| `STRIPE_WEBHOOK_SECRET` | _(vide)_ | Optionnel tant que Stripe n'est pas activé |

### 1.2 Frontend — `frontend/.env.local`

```env
# Développement
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=<générer avec : openssl rand -base64 32>
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

```env
# Production
NEXTAUTH_URL=https://app.aoriarh.fr
NEXTAUTH_SECRET=<valeur forte, différente du SECRET_KEY backend>
NEXT_PUBLIC_API_URL=https://api.aoriarh.fr/api/v1
```

**Important :** `NEXTAUTH_SECRET` doit être une valeur forte (min 32 chars). Ne jamais utiliser `dev-secret-change-in-production`.

### 1.3 Docker Compose — `.env` racine (optionnel)

Le `docker-compose.yml` utilise des variables avec fallback (`${VAR:-default}`).
Pour surcharger les défauts Docker, créer un `.env` à la racine du projet :

```env
POSTGRES_PASSWORD=<même valeur que dans backend/.env>
MINIO_ACCESS_KEY=<même valeur que dans backend/.env>
MINIO_SECRET_KEY=<même valeur que dans backend/.env>
SECRET_KEY=<même valeur que dans backend/.env>
OPENAI_API_KEY=<même valeur que dans backend/.env>
VOYAGE_API_KEY=<même valeur que dans backend/.env>
NEXTAUTH_SECRET=<même valeur que dans frontend/.env.local>
```

Sans ce fichier, Docker Compose utilise les défauts du `docker-compose.yml` (`changeme`, `minioadmin`, etc.) qui ne sont valables qu'en dev local rapide.

---

## 2. Lancer le projet en développement

### 2.1 Avec Docker (recommandé)

```bash
# 1. Configurer les .env (voir section 1)
cp backend/.env.example backend/.env
# Remplir les valeurs dans backend/.env

# 2. Lancer l'infrastructure
docker-compose up -d

# 3. Appliquer les migrations
cd backend && alembic upgrade head

# 4. Vérifier que tout tourne
curl http://localhost:8000/health     # Backend
curl http://localhost:3000            # Frontend
curl http://localhost:6333/readyz     # Qdrant
curl http://localhost:9001            # MinIO Console
```

### 2.2 Sans Docker (services séparés)

```bash
# Terminal 1 — Backend
cd backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Worker ARQ (ingestion documents)
cd backend
python -m arq app.worker.WorkerSettings

# Terminal 3 — Frontend
cd frontend
npm install
npm run dev
```

Prérequis : PostgreSQL, Qdrant, MinIO et Redis doivent tourner localement (ou via Docker).

### 2.3 Compte admin initial

Le seed admin est contrôlé par la variable `SEED_ADMIN` :

- `SEED_ADMIN=true` : un compte admin est créé au démarrage (email + password depuis `.env`)
- `SEED_ADMIN=false` (défaut) : aucun seed, l'app démarre sans créer de compte

**En dev** : mettre `SEED_ADMIN=true` dans `backend/.env` pour avoir un compte admin.
**En prod** : mettre `SEED_ADMIN=true` uniquement au premier déploiement, puis repasser à `false`.

### 2.4 Dev avec Docker vs dev sans Docker

| | Avec Docker | Sans Docker |
|---|---|---|
| **Backend** | Gunicorn multi-worker (mode prod) | `uvicorn --reload` (hot reload) |
| **Frontend** | Next.js build + start (mode prod) | `npm run dev` (hot reload) |
| **Utilisation** | Tester le comportement prod en local | Développer au quotidien |

Le `docker-compose.yml` utilise les Dockerfiles qui sont configurés en mode production. Pour développer au quotidien, utiliser la méthode sans Docker (section 2.2) qui offre le hot reload.

---

## 3. Déployer en production

### 3.1 Prérequis

Avant de déployer en production, **toutes les étapes de criticité 1** (section 5.1) doivent être réalisées.

### 3.2 Différences dev vs production

| Aspect | Développement | Production |
|--------|--------------|------------|
| Backend | `uvicorn --reload` (1 worker) | `gunicorn -w WORKERS -k uvicorn.workers.UvicornWorker` |
| Frontend | `npm run dev` (hot reload) | `npm run build && npm start` |
| PostgreSQL | Mot de passe simple | Mot de passe fort, SSL activé |
| MinIO | `minioadmin` / HTTP | Credentials forts / HTTPS (`MINIO_USE_SSL=true`) |
| JWT `SECRET_KEY` | Peut être simple (min 32 chars) | Généré cryptographiquement, 64+ chars |
| CORS | `http://localhost:3000` | `https://app.aoriarh.fr` |
| `FRONTEND_URL` | `http://localhost:3000` | `https://app.aoriarh.fr` |
| SSL/TLS | Non | Oui (via reverse proxy Caddy/Nginx) |
| Rate limiting | Optionnel | Obligatoire |
| Monitoring | Optionnel | Obligatoire (Sentry, Prometheus, etc.) |

### 3.3 Architecture cible production

```
Internet
   │
   ▼
┌──────────────────┐
│  Caddy / Nginx   │  ← TLS termination, rate limiting
│  (reverse proxy)  │
└──┬──────────┬────┘
   │          │
   ▼          ▼
┌────────┐  ┌──────────┐
│Frontend│  │ Backend  │  ← gunicorn 4 workers
│Next.js │  │ FastAPI  │
└────────┘  └──┬───┬───┘
               │   │
          ┌────┘   └────┐
          ▼             ▼
   ┌───────────┐  ┌─────────┐  ┌─────────┐
   │PostgreSQL │  │ Qdrant  │  │  Redis  │
   │(pool: 15) │  │(vectors)│  │ (queue) │
   └───────────┘  └─────────┘  └────┬────┘
          │                         │
          ▼                         ▼
   ┌───────────┐            ┌───────────┐
   │  MinIO    │            │  Worker   │  ← ARQ (ingestion docs)
   │(documents)│            │  (arq)    │
   └───────────┘            └───────────┘
```

### 3.4 Variables d'environnement production

Créer les fichiers suivants sur le serveur (jamais dans git) :

**`backend/.env` (production) :**

```env
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=aoriarh
POSTGRES_USER=aoriarh
POSTGRES_PASSWORD=<mot de passe fort 20+ chars>

QDRANT_HOST=qdrant
QDRANT_PORT=6333

MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=<identifiant fort>
MINIO_SECRET_KEY=<secret fort 20+ chars>
MINIO_BUCKET=aoriarh-documents
MINIO_USE_SSL=true

SECRET_KEY=<généré avec : python -c "import secrets; print(secrets.token_urlsafe(64))">
ACCESS_TOKEN_EXPIRE_MINUTES=30
ALGORITHM=HS256

SEED_ADMIN=false              # true uniquement au premier déploiement
ADMIN_EMAIL=admin@aoriarh.fr
ADMIN_PASSWORD=<mot de passe fort 16+ chars>

BACKEND_CORS_ORIGINS=["https://app.aoriarh.fr"]

OPENAI_API_KEY=sk-proj-...
VOYAGE_API_KEY=pa-...
LLM_MODEL=gpt-5-mini

BREVO_API_KEY=xkeysib-...
FRONTEND_URL=https://app.aoriarh.fr

STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...

WORKERS=4                     # Voir section 4 pour le dimensionnement
```

**`frontend/.env.local` (production) :**

```env
NEXTAUTH_URL=https://app.aoriarh.fr
NEXTAUTH_SECRET=<généré avec : openssl rand -base64 32>
NEXT_PUBLIC_API_URL=https://api.aoriarh.fr/api/v1
```

---

## 4. Dimensionnement serveur & workers

### 4.1 Comment choisir le nombre de workers

Le nombre de workers Gunicorn se configure via la variable `WORKERS` dans le `.env`.

**Règle de base :**

```
WORKERS = (2 × vCPU disponibles pour le backend) + 1
```

Mais le backend AORIA RH est **async** (FastAPI + asyncpg + httpx). Chaque worker gère déjà plusieurs requêtes en parallèle via l'event loop asyncio. Un seul worker async peut traiter ~50-100 requêtes concurrentes en I/O-bound (attente DB, API OpenAI, Qdrant). On n'a donc pas besoin d'autant de workers qu'une app synchrone.

**Important :** chaque worker consomme ~200-300 Mo de RAM. Plus de workers = plus de RAM utilisée.

### 4.2 Répartition des ressources sur le serveur

Le backend n'est pas seul — tous les services tournent sur la même machine :

| Service | RAM estimée | CPU estimé |
|---------|------------|------------|
| PostgreSQL | ~1-2 Go | 1 vCore |
| Qdrant | ~2-4 Go (selon le volume de vecteurs) | 1 vCore |
| MinIO | ~512 Mo | 0.5 vCore |
| Redis | ~256 Mo | négligeable |
| Worker ARQ | ~512 Mo - 2 Go (selon ingestion) | 1 vCore |
| Frontend (Next.js) | ~512 Mo | 0.5 vCore |
| Caddy (reverse proxy) | ~64 Mo | négligeable |
| OS + système | ~1 Go | - |
| **Reste pour le backend** | **= RAM totale - ~8 Go** | **= vCPU - 4** |

### 4.3 Exemples de dimensionnement

| Serveur | vCPU | RAM | vCPU backend | Workers | Utilisateurs simultanés |
|---------|------|-----|-------------|---------|------------------------|
| VPS-1 (petit) | 2 vCores | 4 Go | ~1 | 2 | ~50-100 |
| VPS-2 (standard) | 4 vCores | 8 Go | ~2 | 2-3 | ~100-200 |
| **VPS-3 (recommandé)** | **8 vCores** | **24 Go** | **~5** | **4** | **~200-400** |
| VPS-4 (large) | 16 vCores | 48 Go | ~10 | 6-8 | ~400-800 |

### 4.4 Recommandation pour le VPS-3 (8 vCores / 24 Go)

```env
WORKERS=4
```

- 4 workers × ~300 Mo = ~1.2 Go de RAM backend — il reste ~16 Go de marge
- 4 workers async sur 5 vCores disponibles = **~200-400 utilisateurs simultanés**
- Largement suffisant pour un SaaS en lancement
- Montable à `WORKERS=6` ou `WORKERS=8` si la charge augmente, sans toucher au code

### 4.5 Comment surveiller et ajuster

Signes qu'il faut **augmenter** les workers :
- Temps de réponse API qui augmente (> 2s pour des requêtes simples)
- Logs `[WARNING] Worker timeout` dans gunicorn
- CPU backend à 100% en permanence

Signes qu'il faut **réduire** les workers :
- RAM du serveur > 80% utilisée
- Swap activé (signe de manque de RAM)

Pour surveiller :
```bash
# RAM par conteneur
docker stats

# Logs gunicorn
docker logs aoriarh-backend-1 --tail 100
```

---

## 5. Corrections par criticité

### 5.1 Criticité 1 — BLOQUANT (avant tout déploiement)

#### C1.1 Révoquer et régénérer toutes les clés API exposées

- **Statut** : EN COURS (`.env.example` créé, `.gitignore` vérifié OK)
- **Fichier** : `backend/.env`
- **Problème** : Les clés OpenAI, Voyage AI et Brevo sont en clair dans le fichier `.env`.
- **Action** :
  - Révoquer les clés depuis les dashboards OpenAI, Voyage AI et Brevo
  - Régénérer de nouvelles clés et les mettre dans `backend/.env`

---

#### C1.2 Supprimer les secrets hardcodés du code source

- **Statut** : FAIT
- **Fichier** : `backend/app/core/config.py`
- **Ce qui a été fait** :
  - 8 variables rendues obligatoires (pas de valeur par défaut) : `postgres_password`, `minio_access_key`, `minio_secret_key`, `openai_api_key`, `voyage_api_key`, `secret_key`, `brevo_api_key`, `admin_password`
  - Validateur `secret_key_must_be_strong` : rejette les valeurs faibles, exige min 32 chars
  - Validateur `admin_password_must_be_strong` : rejette les valeurs faibles, exige min 16 chars
  - L'app crashe au démarrage si un secret est manquant ou faible

---

#### C1.3 Supprimer ou conditionner le seed admin automatique

- **Statut** : FAIT
- **Fichiers** : `backend/app/core/config.py`, `backend/app/main.py`
- **Ce qui a été fait** :
  - Ajout `SEED_ADMIN=false` par défaut dans `config.py` — le seed ne s'exécute plus en production
  - Le lifespan dans `main.py` vérifie `settings.seed_admin` avant d'appeler `seed_admin()`
  - `model_validator` vérifie que `ADMIN_EMAIL` et `ADMIN_PASSWORD` sont valides si `SEED_ADMIN=true`
  - `ADMIN_PASSWORD` devient optionnel (défaut `""`) quand `SEED_ADMIN=false`

---

#### C1.4 Passer le backend en mode production

- **Statut** : FAIT
- **Fichiers** : `backend/Dockerfile`, `backend/pyproject.toml`, `docker-compose.yml`
- **Ce qui a été fait** :
  - Dockerfile utilise maintenant `gunicorn` avec workers `uvicorn.workers.UvicornWorker`
  - Nombre de workers configurable via `WORKERS` (défaut: 4) — voir section 4 pour le dimensionnement
  - `gunicorn>=22.0.0` ajouté dans `pyproject.toml`
  - `WORKERS` passé dans `docker-compose.yml`
  - En dev sans Docker : toujours `uvicorn --reload` (aucun changement)

---

#### C1.5 Passer le frontend en mode production

- **Statut** : FAIT
- **Fichier** : `frontend/Dockerfile`
- **Ce qui a été fait** :
  - Dockerfile exécute `npm run build` puis `npm start` (bundle optimisé, pas de hot reload)
  - En dev sans Docker : toujours `npm run dev` (aucun changement)

---

#### C1.6 Configurer le connection pooling PostgreSQL

- **Statut** : FAIT
- **Fichier** : `backend/app/core/database.py`
- **Ce qui a été fait** :
  - `pool_size=15` — 15 connexions permanentes par worker (× 4 workers = 60 en permanence)
  - `max_overflow=8` — 8 connexions bonus par worker en pic (total max = 92)
  - `pool_timeout=30` — timeout si toutes les connexions sont prises
  - `pool_recycle=1800` — renouvelle les connexions toutes les 30 min
  - Dimensionné pour 4 workers + PostgreSQL max_connections=100 (défaut)

---

#### C1.7 Ajouter du rate limiting sur les endpoints critiques

- **Statut** : FAIT
- **Fichiers** : `backend/app/core/limiter.py` (nouveau), `backend/app/main.py`, `backend/app/api/auth.py`, `backend/app/api/conversations.py`
- **Ce qui a été fait** :
  - `slowapi>=0.1.9` ajouté dans `pyproject.toml`
  - Limiter configuré dans `app/core/limiter.py` (module séparé pour éviter les imports circulaires)
  - Handler 429 avec message en français dans `main.py`
  - Limites appliquées :
    - `/auth/register` : 3 req / min / IP
    - `/auth/login` : 5 req / min / IP
    - `/auth/refresh` : 10 req / min / IP
    - `/conversations/*/chat` : 15 req / min / IP
    - `/conversations/*/chat/stream` : 15 req / min / IP

---

#### C1.8 Ajouter les security headers

- **Statut** : FAIT
- **Fichiers** : `backend/app/main.py`, `frontend/next.config.ts`
- **Ce qui a été fait** :
  - **Backend** — middleware HTTP qui ajoute sur chaque réponse :
    - `X-Content-Type-Options: nosniff`
    - `X-Frame-Options: DENY`
    - `X-XSS-Protection: 1; mode=block`
    - `Referrer-Policy: strict-origin-when-cross-origin`
    - `Strict-Transport-Security` (uniquement si SSL activé via `MINIO_USE_SSL`)
  - **Frontend** — headers configurés dans `next.config.ts` :
    - Mêmes headers + `Content-Security-Policy` (CSP) restrictive
    - `Permissions-Policy` : caméra, micro et géolocalisation désactivés
    - CSP autorise `connect-src` vers l'API backend et Stripe

---

#### C1.9 Restreindre la configuration CORS

- **Statut** : FAIT
- **Fichier** : `backend/app/main.py`
- **Ce qui a été fait** :
  - `allow_methods` restreint à `GET, POST, PATCH, DELETE, OPTIONS` (au lieu de `*`)
  - `allow_headers` restreint à `Content-Type, Authorization` (au lieu de `*`)
  - `max_age=3600` ajouté (cache preflight 1h, réduit les requêtes OPTIONS)

---

#### C1.10 Corriger le bug token dans l'acceptation d'invitation

- **Statut** : FAIT
- **Fichier** : `frontend/src/app/invite/accept/[token]/page.tsx`
- **Ce qui a été fait** :
  - `session.accessToken` remplacé par `session.access_token` (2 occurrences : lignes 60 et 67)
  - Les invitations fonctionnent maintenant pour les utilisateurs connectés

---

#### C1.11 Mettre un reverse proxy avec SSL

- **Statut** : FAIT
- **Fichiers** : `Caddyfile` (nouveau), `docker-compose.prod.yml` (nouveau)
- **Ce qui a été fait** :
  - `Caddyfile` créé — redirige `app.aoriarh.fr` → frontend, `api.aoriarh.fr` → backend
  - `docker-compose.prod.yml` créé — version production complète :
    - Caddy en point d'entrée (ports 80/443 uniquement)
    - Aucun autre port exposé (backend, frontend, DB, Qdrant, MinIO tous cachés)
    - Pas de valeurs par défaut faibles (toutes les variables obligatoires)
    - `restart: unless-stopped` sur tous les services
    - Certificats SSL automatiques via Let's Encrypt
  - `docker-compose.yml` (dev) inchangé — continue de fonctionner comme avant
- **Utilisation** :
  - Dev : `docker-compose up -d` (comme avant)
  - Prod : `docker-compose -f docker-compose.prod.yml up -d`

---

### 5.2 Criticité 2 — HAUTE (premier sprint après déploiement)

#### C2.1 Remplacer BackgroundTasks par une task queue

- **Statut** : FAIT
- **Fichiers** : `backend/app/rag/tasks.py`, `backend/app/worker.py` (nouveau), `backend/app/api/documents.py`, `backend/app/api/admin_documents.py`, `docker-compose.yml`, `docker-compose.prod.yml`
- **Ce qui a été fait** :
  - **ARQ + Redis** choisi comme task queue (léger, 100% async, compatible FastAPI)
  - `arq>=0.26.0` et `redis>=5.0.0` ajoutés dans `pyproject.toml`
  - `REDIS_URL` ajouté dans `config.py` (défaut: `redis://localhost:6379`)
  - `backend/app/worker.py` créé — worker ARQ dédié :
    - Fonction `run_ingestion(ctx, document_id)` exécutée dans un processus séparé
    - Crée son propre engine/session DB (isolé du backend principal)
    - `max_jobs=4`, `job_timeout=300` (5 min max par ingestion)
  - `backend/app/rag/tasks.py` réécrit — `enqueue_ingestion()` envoie le job à Redis
  - `documents.py` et `admin_documents.py` — `BackgroundTasks` supprimé, remplacé par `await enqueue_ingestion()`
  - Redis ajouté dans les deux docker-compose (dev + prod)
  - Service `worker` ajouté dans les deux docker-compose (même image backend, commande `arq app.worker.WorkerSettings`)
  - En prod : worker limité à 1 vCPU / 2 Go RAM
- **Lancer le worker en dev (hors Docker)** :
  ```bash
  cd backend && python -m arq app.worker.WorkerSettings
  ```

---

#### C2.2 Implémenter un vrai health check

- **Statut** : FAIT
- **Fichier** : `backend/app/main.py`
- **Ce qui a été fait** :
  - `/health` vérifie maintenant PostgreSQL (`SELECT 1`), Qdrant (`get_collections`) et MinIO (`head_bucket`)
  - Retourne `200 {"status": "ok", ...}` si tout va bien
  - Retourne `503 {"status": "degraded", ...}` si un service est down
  - Un load balancer peut maintenant router uniquement vers les instances saines

---

#### C2.3 Valider le type de token JWT

- **Statut** : FAIT
- **Fichier** : `backend/app/core/security.py`
- **Ce qui a été fait** :
  - `decode_access_token` vérifie maintenant que `payload["type"] == "access"`
  - Un refresh token utilisé comme access token est rejeté avec `JWTError`
  - `decode_refresh_token` vérifiait déjà le type `"refresh"` (inchangé)

---

#### C2.4 Sécuriser l'endpoint documents communs

- **Statut** : FAIT
- **Fichier** : `backend/app/api/documents.py`
- **Ce qui a été fait** :
  - `get_current_user` remplacé par `require_role(["admin"])` sur `/common/`
  - Seuls les admins peuvent lister les documents communs
  - Les utilisateurs normaux n'y ont plus accès directement (le RAG continue de les utiliser via Qdrant)

---

#### C2.5 Centraliser la gestion des 401 côté frontend

- **Statut** : FAIT
- **Fichiers** : `frontend/src/lib/api.ts`, `frontend/src/lib/chat-api.ts`, `frontend/src/app/(dashboard)/documents/page.tsx`, `frontend/src/app/(dashboard)/admin/documents-communs/page.tsx`, `frontend/src/app/invite/accept/[token]/page.tsx`
- **Ce qui a été fait** :
  - `authFetch()` ajouté dans `api.ts` — wrapper pour les cas FormData/streaming avec gestion 401
  - `API_BASE_URL` exporté depuis `api.ts` — plus de duplication dans chaque fichier
  - `handle401()` factorisé — utilisé par `apiFetch` et `authFetch`
  - 4 `fetch` directs remplacés par `authFetch` :
    - `chat-api.ts` : streaming SSE
    - `documents/page.tsx` : upload FormData
    - `admin/documents-communs/page.tsx` : upload FormData admin
    - `invite/accept/page.tsx` : acceptation d'invitation

---

#### C2.6 Ajouter des limites de ressources Docker

- **Statut** : FAIT
- **Fichier** : `docker-compose.prod.yml`
- **Ce qui a été fait** (dimensionné pour VPS-3 : 8 vCores / 24 Go) :

  | Service | CPU max | RAM max | RAM réservée |
  |---------|---------|---------|-------------|
  | Backend | 4.0 | 4 Go | 512 Mo |
  | Worker ARQ | 1.0 | 2 Go | 256 Mo |
  | PostgreSQL | 1.0 | 2 Go | 256 Mo |
  | Qdrant | 2.0 | 4 Go | 512 Mo |
  | Redis | 0.5 | 256 Mo | 64 Mo |
  | MinIO | 0.5 | 512 Mo | 128 Mo |
  | Frontend | 1.0 | 1 Go | 256 Mo |
  | **Total max** | **10.0** | **13.75 Go** | — |

  Reste ~10 Go pour le système, le cache et les pics

---

#### C2.7 Ajouter des index de base de données manquants

- **Statut** : FAIT
- **Fichier** : `backend/alembic/versions/b7f8e9a0c1d2_add_performance_indexes.py`
- **Ce qui a été fait** — 3 index composites créés :
  - `ix_document_org_status` : `(organisation_id, indexation_status)` — accélère le listing documents filtrés
  - `ix_message_conv_created` : `(conversation_id, created_at)` — accélère le chargement des messages
  - `ix_membership_user_org` : `(user_id, organisation_id)` — accélère les vérifications d'appartenance
- **A exécuter** : `cd backend && alembic upgrade head`

---

#### C2.8 Ajouter du monitoring et logging structuré

- **Statut** : FAIT
- **Fichiers** : `backend/app/core/logging.py` (nouveau), `backend/app/main.py`, `backend/app/worker.py`, `monitoring/` (nouveau), `docker-compose.prod.yml`, `Caddyfile`
- **Ce qui a été fait** :
  - **structlog** — Logging JSON structuré en prod, console colorée en dev
    - Chaque log est un objet JSON avec `timestamp`, `level`, `event`, champs custom
    - Variable `LOG_FORMAT` : `json` (prod/Docker) ou `text` (dev local)
    - Bruit des libs tierces réduit (uvicorn.access, httpx, httpcore)
  - **prometheus-fastapi-instrumentator** — Métriques automatiques
    - Endpoint `/metrics` exposé (Prometheus scrape)
    - Compteurs : requêtes par endpoint/méthode/status, durée, taille
    - `/health` et `/metrics` exclus des métriques
  - **Middleware de logging** — Chaque requête HTTP loguée avec méthode, path, status, durée_ms, IP
  - **Stack monitoring (docker-compose.prod.yml)** :
    - Prometheus : collecte métriques du backend (scrape `/metrics`)
    - Loki : stockage des logs (rétention 30 jours)
    - Promtail : collecte les logs Docker des conteneurs avec label `logging=promtail`
    - Grafana : dashboards + alertes, accessible sur `https://monitoring.aoriarh.fr`
  - **Datasources Grafana** pré-configurées (Prometheus + Loki)
  - **Caddy** — Route `monitoring.aoriarh.fr` ajoutée vers Grafana
- **Configuration Grafana** :
  - User/Password : `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` dans le `.env`
  - DNS : pointer `monitoring.aoriarh.fr` vers le serveur

---

### 5.3 Criticité 3 — MOYENNE (à planifier)

#### C3.1 Sanitiser le rendu Markdown côté frontend

- **Statut** : FAIT
- **Fichiers** : `streaming-bubble.tsx`, `message-bubble.tsx`, `message-sources.tsx`
- **Ce qui a été fait** :
  - `rehype-sanitize` installé et ajouté comme plugin `rehypePlugins={[rehypeSanitize]}` aux 3 composants ReactMarkdown
  - Empêche l'injection HTML/XSS via les réponses IA ou les sources

---

#### C3.2 Ajouter des règles de complexité de mot de passe

- **Statut** : FAIT
- **Fichier** : `backend/app/schemas/auth.py`
- **Ce qui a été fait** — Validateur `password_complexity` sur `RegisterRequest.password` :
  - Min 12 caractères (au lieu de 8)
  - Au moins 1 majuscule
  - Au moins 1 minuscule
  - Au moins 1 chiffre
  - Au moins 1 caractère spécial
  - Messages d'erreur en français
  - Tests existants mis à jour avec mots de passe conformes

---

#### C3.3 Rendre le client Qdrant résilient

- **Statut** : FAIT
- **Fichier** : `backend/app/rag/qdrant_store.py`
- **Ce qui a été fait** :
  - `timeout=10` ajouté à la création du client
  - Auto-reconnexion : `get_qdrant_client()` vérifie la connexion avant de retourner le client
  - Si la connexion est perdue, un nouveau client est créé automatiquement
  - Thread-safe via `threading.Lock`
  - `reset_qdrant_client()` ajouté pour forcer un reset manuel

---

#### C3.4 Réduire la durée du refresh token

- **Statut** : FAIT
- **Fichier** : `backend/app/core/config.py`
- **Ce qui a été fait** : `refresh_token_expire_days` passé de 7 à 3 jours

---

#### C3.5 Stabiliser NextAuth — verrouiller la version

- **Statut** : FAIT
- **Fichier** : `frontend/package.json`
- **Ce qui a été fait** :
  - Version verrouillée à `5.0.0-beta.25` (supprimé le `^` pour empêcher les mises à jour auto)
  - NextAuth v5 stable n'existe pas encore — quand elle sortira, mettre à jour manuellement après test
  - Le `^` sur les beta peut installer une version cassante via `npm install`

---

#### C3.6 Ajouter des Error Boundaries React

- **Statut** : FAIT
- **Fichiers** (nouveaux) :
  - `frontend/src/app/(dashboard)/error.tsx` — Error boundary global du dashboard
  - `frontend/src/app/(dashboard)/chat/error.tsx` — Spécifique au chat
  - `frontend/src/app/(dashboard)/documents/error.tsx` — Spécifique aux documents
  - `frontend/src/app/(dashboard)/organisation/error.tsx` — Spécifique à l'organisation
- **Ce qui a été fait** :
  - Utilise le pattern `error.tsx` natif de Next.js App Router
  - Affiche un message d'erreur avec bouton "Recharger" au lieu d'une page blanche
  - Chaque erreur est loguée dans la console

---

#### C3.7 Implémenter le lazy loading des composants lourds

- **Statut** : FAIT
- **Fichier** : `frontend/src/app/(dashboard)/chat/[conversationId]/page.tsx`
- **Ce qui a été fait** :
  - `MessageList` chargé via `next/dynamic` avec `ssr: false`
  - Ce composant importe ReactMarkdown + remark-gfm + rehype-sanitize (~150 Ko)
  - Le chargement initial de la page est plus rapide, le markdown se charge après

---

#### C3.8 Ajouter un audit trail pour les accès admin

- **Statut** : FAIT
- **Fichiers** :
  - `backend/app/models/audit_log.py` (nouveau) — Modèle SQLAlchemy `AuditLog`
  - `backend/app/services/audit_service.py` (nouveau) — `log_admin_action()`
  - `backend/app/api/admin_documents.py` — Audit sur upload, delete, reindex
  - `backend/alembic/versions/c8d9e0f1a2b3_add_audit_logs_table.py` (nouveau)
- **Ce qui a été fait** :
  - Table `audit_logs` : user_id, action, resource_type, resource_id, organisation_id, ip_address, details, created_at
  - Index sur user_id, action, organisation_id, created_at
  - Chaque action admin d'écriture (upload, delete, reindex) est tracée avec l'IP

---

#### C3.9 Mettre en place un pipeline CI/CD

- **Statut** : FAIT
- **Fichier** : `.github/workflows/ci.yml` (nouveau)
- **Ce qui a été fait** — Pipeline GitHub Actions avec 5 jobs :
  - `backend-lint` : ruff check + ruff format
  - `backend-test` : pytest avec PostgreSQL en service Docker
  - `frontend-lint` : next lint + tsc --noEmit
  - `frontend-test` : jest --ci --coverage
  - `docker-build` : build des images Docker (après lint)
- Se déclenche sur push et PR vers main/master

---

#### C3.10 Monter la couverture de tests à 80%+

- **Statut** : EN COURS
- **Fichier** : `backend/tests/test_security.py` (nouveau)
- **Ce qui a été fait** :
  - Tests de complexité de mot de passe (5 cas : trop court, pas de majuscule, pas de chiffre, pas de spécial, valide)
  - Tests JWT : refresh token rejeté comme access token, et vice-versa
  - Tests multi-tenant : accès interdit aux documents/conversations d'une autre org
  - Tests admin : utilisateur normal ne peut pas accéder aux endpoints admin
  - Test : accès API sans authentification rejeté
  - Mots de passe des fixtures existantes mis à jour pour respecter les nouvelles règles

---

## 6. Checklist de déploiement

```
BLOQUANT
[ ] C1.1  — Clés API révoquées et régénérées
[x] C1.2  — Secrets retirés du code source (config.py sécurisé)
[x] C1.3  — Seed admin conditionné (SEED_ADMIN=false par défaut)
[x] C1.4  — Backend en mode production (gunicorn multi-worker, WORKERS configurable)
[x] C1.5  — Frontend en mode production (build + start)
[x] C1.6  — Connection pooling PostgreSQL configuré (pool_size=15, max_overflow=8)
[x] C1.7  — Rate limiting activé (auth + RAG)
[x] C1.8  — Security headers ajoutés (backend + frontend)
[x] C1.9  — CORS restreint
[x] C1.10 — Bug token invitation corrigé
[x] C1.11 — Reverse proxy + SSL en place

HAUTE
[x] C2.1 — Task queue ARQ + Redis pour l'ingestion
[x] C2.2 — Health check avec vérification des dépendances
[x] C2.3 — Validation type JWT
[x] C2.4 — Endpoint /common/ sécurisé
[x] C2.5 — Gestion centralisée des 401 frontend
[x] C2.6 — Limites ressources Docker
[x] C2.7 — Index DB manquants
[x] C2.8 — Monitoring + logging structuré (structlog + Prometheus + Grafana + Loki)

MOYENNE
[x] C3.1  — Markdown sanitisé (rehype-sanitize sur 3 composants)
[x] C3.2  — Complexité mot de passe (12 chars + majuscule + chiffre + spécial)
[x] C3.3  — Client Qdrant résilient (auto-reconnexion + timeout)
[x] C3.4  — Refresh token réduit (7j → 3j)
[x] C3.5  — NextAuth version verrouillée (5.0.0-beta.25 sans ^)
[x] C3.6  — Error Boundaries React (4 error.tsx)
[x] C3.7  — Lazy loading composants (MessageList dynamic)
[x] C3.8  — Audit trail admin (table audit_logs + logging upload/delete/reindex)
[x] C3.9  — Pipeline CI/CD (GitHub Actions : lint + test + build)
[~] C3.10 — Tests sécurité ajoutés (multi-tenant, JWT, passwords, admin) — couverture à mesurer
```
