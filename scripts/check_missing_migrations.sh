#!/usr/bin/env bash
# Fail if model state diverges from migration files.
#
# Runs ``manage.py makemigrations --check --dry-run``. Uses the docker
# compose ``web`` container when available (same env as CI); otherwise falls
# back to the local interpreter. No db service to wait on — SQLite.
set -euo pipefail

if command -v docker >/dev/null 2>&1 && docker compose config --services >/dev/null 2>&1; then
    exec docker compose run --rm web python manage.py makemigrations --check --dry-run
fi

exec python manage.py makemigrations --check --dry-run
