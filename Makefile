PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
HOP := $(BIN)/hop
MARKET ?= HK
TIER ?= A
API_PORT ?= 8000
DASHBOARD_PORT ?= 8501
PG_TEST_URL ?= postgresql+psycopg://hop:hop@localhost:5432/postgres

.PHONY: help install lock lint format test test-postgres check validate sandbox-run evaluate schemas cli-docs api dashboard \
	compose-up compose-down clean-data

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

$(BIN)/python:
	$(PYTHON) -m venv $(VENV)

install: $(BIN)/python ## Create .venv and install the platform with dashboard, dev and postgres extras
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dashboard,dev,postgres]"

lock: ## Refresh requirements.lock from the current environment
	$(BIN)/pip freeze --exclude-editable | grep -v '^-e ' > requirements.lock

lint: ## Ruff lint + format check
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format: ## Apply ruff fixes and formatting
	$(BIN)/ruff check --fix .
	$(BIN)/ruff format .

test: ## Run the full pytest suite (offline, sandbox providers, mock model)
	$(BIN)/pytest

test-postgres: ## Run the full suite against Postgres (PG_TEST_URL role needs CREATEDB; one throwaway DB per test)
	HOP_TEST_DATABASE_URL=$(PG_TEST_URL) $(BIN)/pytest

check: lint test ## Lint and test

validate: ## Validate the sports-footwear domain pack and run gap-rule tests
	$(HOP) domain validate sports-footwear
	$(HOP) rule test

sandbox-run: ## End-to-end discovery run on sandbox fixtures (MARKET=HK TIER=A)
	$(HOP) collection estimate-cost --market $(MARKET) --tier $(TIER)
	$(HOP) collection run --market $(MARKET) --tier $(TIER)

evaluate: ## Run golden-set evaluations against the quality ratchet
	$(HOP) evaluation run

schemas: ## Re-export contract JSON Schemas into docs/reference/schemas
	$(HOP) schema export --out docs/reference/schemas

cli-docs: ## Regenerate docs/reference/cli.md from the Typer app
	$(BIN)/typer hop.cli.main utils docs --name hop --title "hop CLI reference" --output docs/reference/cli.md

api: ## Serve the HTTP API on :$(API_PORT)
	$(BIN)/uvicorn --factory hop.api:create_app --host 0.0.0.0 --port $(API_PORT)

dashboard: ## Serve the Streamlit dashboard on :$(DASHBOARD_PORT)
	$(BIN)/streamlit run hop/products/opportunity_intelligence/dashboard/app.py \
		--server.port $(DASHBOARD_PORT) --server.headless true

compose-up: ## Build and start app, dashboard, Postgres and Redis
	docker compose -f infrastructure/docker-compose.yml up --build -d

compose-down: ## Stop the compose stack
	docker compose -f infrastructure/docker-compose.yml down

clean-data: ## Delete the local SQLite database and object store under var/
	rm -rf var
