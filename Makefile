.PHONY: help up down build migrate makemigrations shell test coverage coverage-ratchet lint format typecheck check-migrations hooks-install hooks-run discipline dev-install createsuperuser run-job logs ps clean

# Override with `make COMPOSE=docker-compose up` if you prefer the legacy binary.
COMPOSE ?= docker compose

# Run the docker containers as the host user so anything they write to the
# bind-mounted /app (the SQLite db, migrations, media artifacts, caches,
# coverage.xml…) lands owned by *you*, not root. Exported so
# docker-compose.yml's ${HOST_UID}/${HOST_GID} interpolation picks them up.
export HOST_UID := $(shell id -u)
export HOST_GID := $(shell id -g)

# Host-side tooling — picks up ./venv/bin/* when a project venv exists,
# falls back to whatever's on PATH. Lint / format / pre-commit run against
# the host interpreter so they don't pollute the bind-mount with root-owned
# files from the docker container.
PYTHON ?= $(shell test -x venv/bin/python && echo venv/bin/python || command -v python3 || echo python)
PRECOMMIT ?= $(shell test -x venv/bin/pre-commit && echo venv/bin/pre-commit || echo pre-commit)
RUFF ?= $(shell test -x venv/bin/ruff && echo venv/bin/ruff || command -v ruff || echo ruff)

help:
	@echo "Common targets:"
	@echo "  build           Build the Docker images"
	@echo "  up              Start all services"
	@echo "  down            Stop all services"
	@echo "  migrate         Apply database migrations"
	@echo "  makemigrations  Generate new migrations"
	@echo "  shell           Open a Django shell in the web container"
	@echo "  test            Run the pytest suite"
	@echo "  coverage        Run the pytest suite with coverage report"
	@echo "  coverage-ratchet Raise the coverage gate to the current floor (never lowers)"
	@echo "  lint            Run ruff over the codebase"
	@echo "  format          Auto-format the codebase with ruff"
	@echo "  typecheck       Run mypy over the codebase"
	@echo "  discipline      Run the exception-discipline checker"
	@echo "  check-migrations Verify models are in sync with migration files"
	@echo "  dev-install     Install dev dependencies into ./venv"
	@echo "  hooks-install   Install pre-commit + pre-push hooks (once per clone)"
	@echo "  hooks-run       Run all configured hooks against every file"
	@echo "  createsuperuser Create an admin user"
	@echo "  run-job         Trigger a pipeline job from a preset: make run-job PRESET=presets/demo.yaml"
	@echo "  logs            Tail the docker-compose logs"
	@echo "  ps              Show running services"
	@echo "  clean           Remove containers, volumes, and caches"

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up

down:
	$(COMPOSE) down

migrate:
	$(COMPOSE) run --rm web python manage.py migrate

makemigrations:
	$(COMPOSE) run --rm web python manage.py makemigrations

shell:
	$(COMPOSE) run --rm web python manage.py shell

test:
	$(COMPOSE) run --rm web pytest -v

coverage:
	$(COMPOSE) run --rm web pytest --cov --cov-report=term-missing --cov-report=xml

coverage-ratchet: coverage
	python3 scripts/coverage_ratchet.py

lint:
	$(RUFF) check .

format:
	$(RUFF) format .
	$(RUFF) check --fix .

discipline:
	python3 scripts/check_exception_discipline.py

typecheck:
	$(COMPOSE) run --rm web mypy .

check-migrations:
	$(COMPOSE) run --rm web python manage.py makemigrations --check --dry-run

dev-install:
	$(PYTHON) -m pip install --upgrade -e ".[dev]"

hooks-install:
	$(PYTHON) -m pip install --upgrade pre-commit
	$(PRECOMMIT) install --install-hooks --hook-type pre-commit --hook-type pre-push

hooks-run:
	$(PRECOMMIT) run --all-files --hook-stage pre-commit
	$(PRECOMMIT) run --all-files --hook-stage pre-push

createsuperuser:
	$(COMPOSE) run --rm web python manage.py createsuperuser

# Kick off a pipeline run from a preset YAML. Override PRESET to point at
# your own: ``make run-job PRESET=presets/my_song.yaml``.
PRESET ?= presets/demo.yaml
run-job:
	$(COMPOSE) run --rm web python manage.py run_job $(PRESET)

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

clean:
	$(COMPOSE) down -v
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache .coverage coverage.xml htmlcov
