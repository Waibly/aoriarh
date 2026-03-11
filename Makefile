.PHONY: up down infra backend-dev frontend-dev test-backend test-frontend lint

up:
	docker compose up -d

down:
	docker compose down

infra:
	docker compose up -d postgres qdrant minio

backend-dev:
	cd backend && uvicorn app.main:app --reload

frontend-dev:
	cd frontend && npm run dev

test-backend:
	cd backend && pytest

test-frontend:
	cd frontend && npm test

lint:
	cd backend && ruff check .
	cd frontend && npm run lint
