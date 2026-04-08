FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Pre-download the BM25 model so the worker never depends on HuggingFace
# being reachable at runtime. fastembed caches under ~/.cache/fastembed
# (HOME=/root in this slim image) → the model lives inside the image
# and survives container restarts. If HF goes 503 again, ingestion
# keeps working from the local cache.
RUN python -c "from fastembed import SparseTextEmbedding; SparseTextEmbedding(model_name='Qdrant/bm25')"

COPY . .

# WORKERS configurable via variable d'environnement (défaut: 4)
# Règle : (2 x vCPU) + 1, ajusté selon la RAM disponible
# Voir TODO_PRODUCTION.md section 3 pour le dimensionnement
CMD ["sh", "-c", "gunicorn app.main:app -w ${WORKERS:-4} -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 120 --graceful-timeout 30"]
