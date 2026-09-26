.PHONY: up db test psql api web e2e e2e-ci eval eval-baseline ci-fixture

up:  ## start Postgres and wait until healthy
	docker compose up -d --wait db

db: up  ## apply db/schema.sql (idempotent)
	docker compose exec -T db psql -U postgres -d ai_lawyer -v ON_ERROR_STOP=1 -q < db/schema.sql

test: up  ## run the test suite against a fresh ai_lawyer_test database
	uv run pytest -q

psql:
	docker compose exec db psql -U postgres -d ai_lawyer

api: up  ## run the API with reload on http://localhost:8000
	uv run --env-file .env uvicorn app.main:app --reload --port 8000

web:  ## run the Next.js app on http://localhost:3000 (needs `make api`)
	npm --prefix web run dev

e2e: up  ## Playwright UI tests (starts its own API with AI_FAKE=1 on :8001 and web on :3001)
	npm --prefix web run e2e

eval: up  ## gold-set experiments in Langfuse; fails on a > 2-point drop vs evals/baseline.json (local only)
	uv run --env-file .env scripts/eval.py gate

eval-baseline: up  ## run the experiments and record evals/baseline.json (deliberate; commit the result)
	uv run --env-file .env scripts/eval.py record

ci-fixture: up  ## re-export the small CI corpus (tests/fixtures/corpus) from the dev DB
	uv run python -c "import psycopg; from evals.ci_fixture import export_fixture; print(export_fixture(psycopg.connect('postgresql://postgres:dev@localhost:5432/ai_lawyer')))"

e2e-ci: up  ## Playwright against a fresh ai_lawyer_ci DB (current schema + CI fixture), like GitHub Actions
	docker compose exec -T db psql -U postgres -qc "DROP DATABASE IF EXISTS ai_lawyer_ci WITH (FORCE)" -c "CREATE DATABASE ai_lawyer_ci"
	docker compose exec -T db psql -U postgres -d ai_lawyer_ci -v ON_ERROR_STOP=1 -q < db/schema.sql
	uv run python -c "import psycopg; from evals.ci_fixture import load_fixture; c = psycopg.connect('postgresql://postgres:dev@localhost:5432/ai_lawyer_ci'); print(load_fixture(c)); c.commit()"
	DATABASE_URL=postgresql://postgres:dev@localhost:5432/ai_lawyer_ci npm --prefix web run e2e
