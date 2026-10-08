#!/bin/sh
# Isolated development only; no production deployment or outbound email.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
# Use the project's key rather than an unrelated key inherited from the terminal.
OPENAI_API_KEY=$("$project_dir/backend/.venv/bin/python" -c 'import sys; from dotenv import dotenv_values; key = dotenv_values(sys.argv[1]).get("OPENAI_API_KEY"); assert key, "OPENAI_API_KEY missing from backend/.env"; print(key)' "$project_dir/backend/.env")
export OPENAI_API_KEY
export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5544 POSTGRES_DB=aoriarh POSTGRES_USER=aoriarh
export POSTGRES_PASSWORD=aoria-local-only
export QDRANT_HOST=127.0.0.1 QDRANT_PORT=6335 QDRANT_API_KEY=
export MINIO_ENDPOINT=127.0.0.1:9100 MINIO_ACCESS_KEY=aoria-local
export MINIO_SECRET_KEY=aoria-local-storage-only MINIO_USE_SSL=false
export MINIO_BUCKET=aoriarh-dossiers-local REDIS_URL=redis://127.0.0.1:6382
export APP_ENV=development BREVO_API_KEY= BREVO_LIST_ID=0 STRIPE_SECRET_KEY=
export FRONTEND_URL=http://localhost:3001 BACKEND_CORS_ORIGINS='["http://localhost:3001","http://127.0.0.1:3001"]'
export NEXT_PUBLIC_API_URL=http://localhost:8001/api/v1 INTERNAL_API_URL=http://127.0.0.1:8001/api/v1
export AUTH_URL=http://localhost:3001 NEXTAUTH_URL=http://localhost:3001 AUTH_TRUST_HOST=true
export SEED_ADMIN=true ADMIN_EMAIL=dossiers-local@example.com ADMIN_PASSWORD=Local-Dossiers-2026!
case "${1:-}" in
  infra) cd "$project_dir"; exec docker compose -p aoria-dossiers-local -f docker-compose.dossiers-local.yml up -d ;;
  migrate) cd "$project_dir/backend"; exec .venv/bin/alembic upgrade head ;;
  seed) cd "$project_dir/backend"; export PYTHONPATH="$project_dir/backend"; exec .venv/bin/python "$project_dir/scripts/dev/seed_dossiers_local.py" ;;
  backend) cd "$project_dir/backend"; exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 ;;
  worker) cd "$project_dir/backend"; exec .venv/bin/python -c 'from arq import run_worker; from app.worker import WorkerSettings; run_worker(type("LocalWorkerSettings", (), {**{k: v for k, v in vars(WorkerSettings).items() if not k.startswith("__")}, "cron_jobs": []}))' ;;
  frontend) cd "$project_dir/frontend"; exec npm run dev -- --port 3001 ;;
  *) echo "Usage: sh scripts/dev/dossiers-local.sh infra|migrate|seed|backend|worker|frontend"; exit 1 ;;
esac
