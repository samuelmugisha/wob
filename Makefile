COMPOSE = docker compose --env-file .env -f infrastructure/docker/compose.yaml

.PHONY: db-up db-down db-reset migrate test lint api api-local benchmark user invite encrypt-storage rotate-file-key verify-storage purge-expired auto-accept-research web worker worker-logs

db-up:        ## Start Postgres + pgvector
	$(COMPOSE) up -d --wait db

db-down:
	$(COMPOSE) down

db-reset:     ## Destroy the local database volume and start fresh
	$(COMPOSE) down -v
	$(COMPOSE) up -d --wait db

migrate:
	cd backend && uv run alembic upgrade head

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .

api:          ## Build and run the API in Docker (has the embedding/reranking models)
	$(COMPOSE) up -d --build api

api-local:    ## Run the API on the host with reload; no local models, so search is keyword-only
	cd backend && EMBEDDING_PROVIDER=fake RERANKER_PROVIDER=none uv run uvicorn app.main:app --reload

benchmark:    ## Run the retrieval recall benchmark (BENCHMARK=ai/evaluation/<file>.json)
	$(COMPOSE) run --rm --no-deps -v "$$PWD/ai/evaluation:/benchmarks" worker \
		python -m app.evaluation.retrieval /benchmarks/$$(basename $${BENCHMARK:-demo-benchmark.json})

user:         ## Create an account: make user EMAIL=a@b.org NAME="A B" ROLE=admin (prints invite link)
	cd backend && uv run python -m app.cli create-user "$(EMAIL)" "$(NAME)" "$(ROLE)"

invite:       ## New set-password link: make invite EMAIL=a@b.org
	cd backend && uv run python -m app.cli invite "$(EMAIL)"

web:          ## Run the coordinator UI on http://localhost:3000
	cd frontend && npm run dev

worker:       ## Build and start ClamAV + the ingestion worker in the background
	$(COMPOSE) --profile scan up -d --build clamav worker

worker-logs:
	$(COMPOSE) logs -f worker

encrypt-storage:  ## Encrypt any legacy plaintext files in place
	cd backend && uv run python -m app.cli encrypt-storage

rotate-file-key:  ## Re-wrap all files to FILE_ENCRYPTION_ACTIVE_KEY
	cd backend && uv run python -m app.cli rotate-file-key

verify-storage:   ## Decrypt every file and check it against the database SHA-256
	cd backend && uv run python -m app.cli verify-storage

purge-expired:    ## Destroy personal data of categories past their retention date (run daily)
	cd backend && uv run python -m app.cli purge-expired

auto-accept-research:  ## Apply automatic acceptance to findings from earlier research
	cd backend && uv run python -m app.cli auto-accept-research
