ENV_FILE ?= .env

ENV_REQUIRED_GOALS := run worker-run test test-pre-push check \
	infra-up infra-down infra-restart infra-logs \
	compose-up compose-down compose-logs \
	compose-runtime-up compose-runtime-down compose-runtime-logs \
	migration psql
ACTIVE_GOALS := $(if $(MAKECMDGOALS),$(MAKECMDGOALS),run)

ifneq ($(strip $(filter $(ENV_REQUIRED_GOALS),$(ACTIVE_GOALS))),)
ifeq ($(strip $(wildcard $(ENV_FILE))),)
$(error ENV_FILE '$(ENV_FILE)' does not exist)
endif
endif

.PHONY: run worker-run test test-pre-push lint format typecheck pre-commit check \
	infra-up infra-down infra-restart infra-logs \
	app-up app-down app-restart app-logs \
	compose-up compose-down compose-logs \
	compose-runtime-up compose-runtime-down compose-runtime-logs \
	migration psql

DOTENV_RUN = poetry run -- dotenv -f $(ENV_FILE) run --
COMPOSE_RUNTIME = docker compose --env-file $(ENV_FILE) -f docker-compose.yml
COMPOSE = $(COMPOSE_RUNTIME) -f docker-compose.dev.yml

run:
	$(DOTENV_RUN) python -m src.run_app

worker-run:
	$(DOTENV_RUN) python -m src.run_quote_worker

test:
	$(DOTENV_RUN) env PYTHONPATH=. poetry run pytest -x tests -v --junitxml=junit.xml --cov=src --cov-branch --cov-report=term --cov-report=xml:coverage.xml --cov-report=html:htmlcov --cov-fail-under=80

test-pre-push:
	$(DOTENV_RUN) env PYTHONPATH=. poetry run pytest -x tests -v --cov=src --cov-branch --cov-report=term --cov-fail-under=80

lint:
	poetry run ruff check . --force-exclude

format:
	poetry run ruff format . --force-exclude
	poetry run ruff check --fix . --force-exclude

typecheck:
	poetry run mypy src --explicit-package-bases

pre-commit:
	poetry run pre-commit run --all-files

check: format lint typecheck test

infra-up:
	$(COMPOSE) up -d postgres redis

infra-down:
	$(COMPOSE) stop postgres redis

infra-restart:
	$(COMPOSE) restart postgres redis

infra-logs:
	$(COMPOSE) logs -f postgres redis

compose-up:
	$(COMPOSE) up -d --build

compose-down:
	$(COMPOSE) down

compose-logs:
	$(COMPOSE) logs -f

compose-runtime-up:
	$(COMPOSE_RUNTIME) up -d --build

compose-runtime-down:
	$(COMPOSE_RUNTIME) down

compose-runtime-logs:
	$(COMPOSE_RUNTIME) logs -f

migration:
	$(COMPOSE) exec app alembic upgrade head

psql:
	$(COMPOSE) exec postgres sh -c 'psql "dbname=$$POSTGRES_DB user=$$POSTGRES_USER password=$$POSTGRES_PASSWORD"'

%:
	@:
