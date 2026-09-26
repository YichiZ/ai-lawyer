.PHONY: up db test psql api worker web e2e e2e-ci lighthouse eval eval-suite eval-baseline ci-fixture

up:  ## start Postgres + Redis and wait until healthy
	docker compose up -d --wait db redis

db: up  ## apply db/schema.sql (idempotent)
	docker compose exec -T db psql -U postgres -d ai_lawyer -v ON_ERROR_STOP=1 -q < db/schema.sql

test: up  ## run the test suite against a fresh ai_lawyer_test database
	uv run pytest -q

psql:
	docker compose exec db psql -U postgres -d ai_lawyer

api: up  ## run the API with reload on http://localhost:8000
	uv run --env-file .env uvicorn app.main:app --reload --port 8000

worker: up  ## run the ingest worker (add-to-corpus jobs from Redis)
	uv run --env-file .env -m scripts.worker

web:  ## run the Next.js app on http://localhost:3000 (needs `make api`)
	npm --prefix web run dev

e2e: up  ## Playwright UI tests (starts its own API with AI_FAKE=1 on :8001 and web on :3001)
	npm --prefix web run e2e

eval: up  ## gold-set experiments in Langfuse; fails on a > 2-point drop vs evals/baseline.json (local only)
	uv run --env-file .env -m scripts.eval gate

eval-suite: up  ## production eval suite: pinpoint, search, safety, abstention, robustness, glossary (local; ~$1)
	uv run --env-file .env -m scripts.eval_suite

eval-baseline: up  ## run the experiments and record evals/baseline.json (deliberate; commit the result)
	uv run --env-file .env -m scripts.eval record

ci-fixture: up  ## re-export the small CI corpus (tests/fixtures/corpus) from the dev DB
	uv run python -c "import psycopg; from evals.ci_fixture import export_fixture; print(export_fixture(psycopg.connect('postgresql://postgres:dev@localhost:5432/ai_lawyer')))"

e2e-ci: up  ## Playwright against a fresh ai_lawyer_ci DB (current schema + CI fixture), like GitHub Actions
	docker compose exec -T db psql -U postgres -qc "DROP DATABASE IF EXISTS ai_lawyer_ci WITH (FORCE)" -c "CREATE DATABASE ai_lawyer_ci"
	docker compose exec -T db psql -U postgres -d ai_lawyer_ci -v ON_ERROR_STOP=1 -q < db/schema.sql
	uv run python -c "import psycopg; from evals.ci_fixture import load_fixture; c = psycopg.connect('postgresql://postgres:dev@localhost:5432/ai_lawyer_ci'); print(load_fixture(c)); c.commit()"
	DATABASE_URL=postgresql://postgres:dev@localhost:5432/ai_lawyer_ci npm --prefix web run e2e

lighthouse: up  ## production build + Lighthouse CI budgets (LCP, CLS, JS size, a11y) against the fake-model API
	-pkill -f "next start --port 3002"; pkill -f "uvicorn app.main:app --port 8001"; sleep 1
	cd web && NEXT_DIST_DIR=.next-lh API_URL=http://localhost:8001 npx next build
	AI_FAKE=1 uv run uvicorn app.main:app --port 8001 & \
	(cd web && NEXT_DIST_DIR=.next-lh API_URL=http://localhost:8001 npx next start --port 3002) & \
	trap 'pkill -f "next start --port 3002"; pkill -f "uvicorn app.main:app --port 8001"' EXIT; \
	sleep 6; cd web && npx lhci autorun
