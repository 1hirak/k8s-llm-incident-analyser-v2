SERVICES := shared collector processor llm reports orchestrator gateway scenario watcher remediation
PYTEST := .venv/bin/python -m pytest

.PHONY: help install dev test test-services test-root test-cov lint format clean \
        up restart down up-dev external-up logs build e2e eval frontend-install frontend-build frontend-types

help:
	@echo "Available targets:"
	@echo "  install         Install shared package + root dependencies"
	@echo "  dev             Install all dev dependencies"
	@echo "  test            Run ALL tests (root suite + every service)"
	@echo "  test-root       Run root tests only (evaluation, manifests, integration)"
	@echo "  test-services   Run every service test suite"
	@echo "  test-cov        Run tests with coverage report"
	@echo "  lint            Run ruff linter"
	@echo "  format          Auto-format with ruff"
	@echo "  clean           Remove build artifacts and caches"
	@echo "  up              Start minikube, deploy demo-app, and start the platform"
	@echo "  restart         Restart minikube workload and the platform (keeps data)"
	@echo "  up-dev          Start the stack with hot-reload dev override"
	@echo "  external-up     Start against an explicitly configured external cluster"
	@echo "  down            Stop the stack"
	@echo "  logs            Tail platform logs"
	@echo "  build           Build all service images"
	@echo "  e2e             Run the end-to-end smoke test (requires stack up)"
	@echo "  eval            Run the evaluation harness (requires stack up)"
	@echo "  frontend-install  Install frontend dependencies"
	@echo "  frontend-build  Build the frontend for production"
	@echo "  frontend-types  Regenerate TS types from contracts/api/gateway.yaml"
	@echo "  run-scenario    Apply a fault scenario (SCENARIO=05-oom)"

install:
	pip install -e ./services/shared
	pip install -r requirements.txt

dev:
	pip install -e ./services/shared
	pip install -r requirements.txt -r requirements-dev.txt

test: test-services test-root

test-root:
	$(PYTEST) tests -v

test-services:
	@for svc in $(SERVICES); do \
		echo "=== services/$$svc ==="; \
		(cd services/$$svc && ../../$(PYTEST) -q) || exit 1; \
	done

test-cov:
	$(PYTEST) tests --cov=evaluation --cov-report=term-missing
	@for svc in $(SERVICES); do \
		(cd services/$$svc && ../../$(PYTEST) --cov=app --cov-report=term-missing -q) || exit 1; \
	done

lint:
	ruff check . --extend-ignore E501

format:
	ruff check --fix . && ruff format .

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov *.egg-info build dist data
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

up:
	@bash scripts/start_local.sh

restart:
	@bash scripts/restart_system.sh

up-dev:
	@SKIP_COMPOSE=true bash scripts/start_local.sh
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

external-up:
	@test -f .env.external || (echo "Create .env.external from .env.external.example first." && exit 1)
	docker compose -f docker-compose.external.yml --env-file .env.external up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

build:
	docker compose build

e2e:
	@bash scripts/e2e_smoke.sh

eval:
	.venv/bin/python -m evaluation.harness $(ARGS)

run-scenario:
	@bash scripts/run_scenario.sh $(SCENARIO)

frontend-install:
	cd frontend && npm install

frontend-build:
	cd frontend && npm run build

frontend-types:
	cd frontend && npm run generate:types
