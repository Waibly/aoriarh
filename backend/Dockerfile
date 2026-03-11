FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

# WORKERS configurable via variable d'environnement (défaut: 4)
# Règle : (2 x vCPU) + 1, ajusté selon la RAM disponible
# Voir TODO_PRODUCTION.md section 3 pour le dimensionnement
CMD ["sh", "-c", "gunicorn app.main:app -w ${WORKERS:-4} -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 120 --graceful-timeout 30"]
