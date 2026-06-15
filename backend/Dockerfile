FROM python:3.12-slim

WORKDIR /app

# Libs système requises par WeasyPrint (rendu PDF des fiches pratiques) :
# pango/cairo/gdk-pixbuf pour le rendu, fonts-dejavu pour le texte.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
        libgdk-pixbuf-2.0-0 libffi8 libcairo2 shared-mime-info fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

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
