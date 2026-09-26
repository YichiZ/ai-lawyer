.PHONY: up db test psql api

up:  ## start Postgres and wait until healthy
	docker compose up -d --wait db

db: up  ## apply db/schema.sql (idempotent)
	docker compose exec -T db psql -U postgres -d ai_lawyer -v ON_ERROR_STOP=1 -q < db/schema.sql

test: up  ## run the test suite against a fresh ai_lawyer_test database
	uv run pytest -q

psql:
	docker compose exec db psql -U postgres -d ai_lawyer

api: up  ## run the API with reload on http://localhost:8000
	uv run uvicorn app.main:app --reload --port 8000
