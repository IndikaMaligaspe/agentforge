.PHONY: help install run test lint format clean db-up db-down db-migrate db-revision test-benchmarks
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install project dependencies
	uv sync --extra dev

# --env-file .env is required so that bare os.environ.get() consumers (e.g. JWT
# secrets read at module-import time) see .env values. pydantic-settings loads
# .env automatically, but os.environ does not — omitting this flag causes 401s
# on every request.
run: ## Start the API server
	uv run --env-file .env uvicorn backend.main:app --reload

test: ## Run the test suite
	uv run pytest -v

lint: ## Lint code with ruff
	uv run ruff check .

format: ## Format code with ruff
	uv run ruff format .

clean: ## Remove cache and build artefacts
	find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache dist build *.egg-info
db-up: ## Start the database via docker-compose
	docker compose up -d db

db-down: ## Stop the database via docker-compose
	docker compose down

db-migrate: ## Apply all pending Alembic migrations
	uv run alembic upgrade head

db-revision: ## Generate a new Alembic migration (autogenerate)
	uv run alembic revision --autogenerate -m "$(MSG)"

test-benchmarks: ## Run DeepEval benchmark suite
	uv run pytest -m benchmarks -v