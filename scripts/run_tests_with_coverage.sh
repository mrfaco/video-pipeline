#!/usr/bin/env bash
# Run the test suite through Docker if available (same environment as CI),
# otherwise fall back to the local interpreter. The coverage threshold lives
# in pyproject.toml's pytest addopts so there is one source of truth.
#
# No db service to wait on — job state is SQLite, created on first migrate.
set -euo pipefail

if command -v docker >/dev/null 2>&1 && docker compose config --services >/dev/null 2>&1; then
    exec docker compose run --rm web pytest
fi

exec pytest
