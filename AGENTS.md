# AGENTS.md

Working rules for AI agents (Claude Code, Codex, Cursor, etc.) and the humans reviewing their
changes. This repo is deliberately AI-coded — the hooks and gates exist so the review burden stays
minimal. **Read this before writing code.**

## 1. Exception discipline — never swallow, never fall back

The project's first rule. Failures must be **loud**.

### Forbidden

- **Bare `except:`** or `except Exception:` that catches and does not re-raise. Ruff `BLE001`
  catches the syntax; `scripts/check_exception_discipline.py` catches the semantics (an `except`
  block that neither raises nor unconditionally exits).
- **Log and continue.** `logger.error(...)` with no `raise` after it. Either re-raise
  (`logger.exception(...)` if you want the traceback), or don't catch.
- **Fallback values on error.** `except X: return None` / `return []` / `return DEFAULT`. If the
  caller can't tell whether you got real data or a default, the bug got harder to find. Raise.
- **`try` blocks wider than the one statement that can fail.** Wrap precisely what raises.
- **Bare `raise Exception(...)`.** Use a specific type (ruff `TRY002`).

This matters doubly here: a provider returning a fallback artifact on a failed API call would
produce a *silently broken video* — the worst failure mode for this pipeline. A missing key or a
non-200 from Replicate/fal/the lip-sync vendor must raise.

### Required

- **Re-raise preserves traceback.** Plain `raise` to log + propagate.
- **Translate with `from`.** `raise NewError(...) from exc` (ruff `B904`).
- **`logger.exception(...)`** when logging inside an `except` (ruff `TRY400`).
- **`# allow: suppress-exception`** on the rare `except` line where suppression is the design. We
  grep for these in review.

Validate locally: `make discipline` and `make lint`.

## 2. Test discipline — every change has a test

- New behavior gets a test in the same commit; a bug fix gets a regression test that fails on the
  pre-fix code.
- Tests run with `PROVIDER_MODE=fake` so they never spend money or need keys. The full-chain test
  exercises real `ffmpeg` on bundled fixtures; only the outbound Telegram POST is mocked.
- Don't monkey-patch around the pipeline boundaries you're testing.

## 3. Coverage gate — ratchet up, never down

- Threshold lives in `pyproject.toml` → `[tool.pytest.ini_options].addopts` as `--cov-fail-under=N`.
- Raise it with `make coverage-ratchet` (reads `coverage.xml`, only moves up). Never lower by hand.

## 4. Format & lint

- `ruff format` owns formatting. `ruff check` runs the ruleset in `pyproject.toml`.
- **Imports are absolute and module-level** — `from jobs.models import Job`, never `from .models`
  (`TID252`); keep them top-of-file (`PLC0415`). A genuinely-deferred import (circular break, an
  optional heavy SDK behind `PROVIDER_MODE=real`) needs an explicit `# noqa: PLC0415` with a reason.
- `mypy .` must be clean before push.

## 5. Boundaries between modules

- **Stages are thin.** A `@shared_task` validates `ctx`, calls exactly one provider/compose/delivery
  function, records its artifact, and returns `ctx`. No vendor HTTP or ffmpeg logic inside a stage.
- **Providers don't know about Django models or `ctx`.** They take paths in, write a file, return
  the path. The stage owns persistence.
- **The Real/Fake split is load-bearing.** Heavy SDKs (`replicate`, `fal_client`) import *inside*
  the Real client, never at module top — a fake-only run must import cleanly without them.
- **Only the orchestrator and stages write `Job`/`Artifact` rows.** Providers/compose/delivery never
  touch the DB.

## 6. Migrations stay in sync with models

- Editing a model without `makemigrations` is a footgun. `make check-migrations` and the pre-push
  hook run `makemigrations --check --dry-run`.

## 7. Secrets never land in git

- `gitleaks` runs pre-commit. The Replicate / fal / lip-sync / Telegram keys all live in `.env`
  (gitignored). If you commit a real secret, rotate it *immediately*, then rewrite history.

## 8. Don't add scope

- Bug fixes don't get surrounding refactors. New features come with the minimum surface they need —
  tests yes, speculative abstraction no. No "just in case" fallbacks (see rule 1).
- Comments explain *why*, not *what*. If removing the comment loses nothing, delete it.

## 9. Don't bypass the hooks

- `git commit --no-verify` is for genuine emergencies (a broken hook itself), never for "the tests
  fail."

## 10. Schema versioning

- `JobContext` carries `schema_version` (`core.context.SCHEMA_VERSION`). Bump it when the shape
  changes; structured fixtures (word-timestamps JSON, captions) follow the same discipline.

## 11. Logging is structured

- Job state lives in the DB (`Job`/`Artifact`), not stdout. No `print()` in business logic.
  `logger.info` for lifecycle, `logger.exception` only inside an `except` that also re-raises.
