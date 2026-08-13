FROM python:3.12-slim

WORKDIR /app

# Libs système requises par WeasyPrint (rendu PDF des fiches pratiques) :
# pango/cairo/gdk-pixbuf pour le rendu, fonts-dejavu pour le texte.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
        libgdk-pixbuf-2.0-0 libffi8 libcairo2 shared-mime-info fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN python -m pip install --no-cache-dir --upgrade "pip>=26.1.2" "setuptools>=83.0" \
    && pip install --no-cache-dir .

# Pre-download the BM25 model so the worker never depends on HuggingFace
# being reachable at runtime. fastembed caches under ~/.cache/fastembed
# (HOME=/root in this slim image) → the model lives inside the image
# and survives container restarts. If HF goes 503 again, ingestion
# keeps working from the local cache.
RUN python -c "from fastembed import SparseTextEmbedding; SparseTextEmbedding(model_name='Qdrant/bm25')"

COPY . .

RUN useradd --create-home --uid 10001 aoria \
    && mkdir -p /home/aoria/.cache \
    && cp -a /root/.cache/. /home/aoria/.cache/ \
    && chown -R aoria:aoria /app /home/aoria/.cache

USER aoria

# Quatre workers async suffisent sur le VPS 8 vCPU. Le recyclage progressif
# évite qu'un processus conserve indéfiniment les caches accumulés.
CMD ["sh", "-c", "gunicorn app.main:app -w ${WORKERS:-4} -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 120 --graceful-timeout 30 --max-requests ${GUNICORN_MAX_REQUESTS:-1000} --max-requests-jitter ${GUNICORN_MAX_REQUESTS_JITTER:-200}"]
