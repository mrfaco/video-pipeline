# CLAUDE.md

Guidance for AI agents working in this repo. Read **`AGENTS.md`** first — it holds the hard rules
(loud failures, thin stages, every change tested). This file is the mental model + the gotchas.

## What this is

A config-driven pipeline that turns **(preset song + theme + locked synthetic character)** into a
finished 9:16 lip-synced, captioned video delivered to Telegram. Runs on a Raspberry Pi 5 as a thin
orchestrator: every heavy step is a cloud API call; the Pi only runs `ffmpeg` and HTTP. Job state is
**SQLite**. See `docs/superpowers/specs/2026-06-02-brainrot-pipeline-design.md` for the full design.

## Architecture in one breath

Seven idempotent Celery tasks run as a `chain`, passing one `ctx` (`core.context.JobContext`,
serialized to a dict over the wire) from link to link:

```
prepare_assets → separate_vocals → align_captions → generate_visuals
  → lipsync_render → compose_video → deliver_telegram
```

Each stage is **thin**: mark progress, call ONE provider/compose/delivery function, record an
`Artifact`, return `ctx`. All artifacts live under `media/jobs/<job_id>/` (via `core.storage`).

### The Real/Fake provider split (most important concept)

Every cloud stage calls a client from `providers/` chosen by `settings.PROVIDER_MODE`:
- `fake` (default, and what tests use) → `providers/fakes.py` copies a bundled `fixtures/` artifact.
  No network, no spend. Exercises the whole chain.
- `real` → `providers/replicate.py` (Demucs, WhisperX), `providers/fal.py` (FLUX still/portrait,
  image→video), `providers/lipsync.py` (Hedra/Sync/MagicHour). Selected via `providers/base.py`
  `get_*` factories.

`compose/` (ffmpeg) and `delivery/` (Telegram) are always real — local/free.

### Module boundaries (enforced by review, see AGENTS.md §5)

| Module | Owns | Never does |
|--------|------|------------|
| `stages/` | progress + artifact bookkeeping, calling one collaborator | vendor HTTP, ffmpeg, fallbacks |
| `providers/` | paths in → file out → path back | touch Django models or `ctx` |
| `compose/` | ffmpeg filtergraph, `.ass` building | know about jobs |
| `delivery/` | Telegram transport | build caption text |
| `jobs/` | `Job`/`Artifact` models, presets, orchestrator, admin | heavy logic |
| `api/` | DRF Bearer-key endpoints | business logic |

Only the orchestrator and stages write `Job`/`Artifact` rows.

## Commands

```bash
make up                                   # full stack (web + worker + beat + redis)
make run-job PRESET=presets/demo.yaml     # trigger a job (admin action / API also work)
./venv/bin/python manage.py run_job presets/demo.yaml --sync   # run inline, no worker
make test  /  make lint  /  make typecheck  /  make discipline
make coverage-ratchet                     # raise the coverage floor (never lowers)
```

## Gotchas (things that cost time)

- **Eager execution uses `.apply()`, not `task_always_eager`.** Celery snapshots
  `CELERY_TASK_ALWAYS_EAGER` into `app.conf` when the app finalizes; mutating the conf later does
  NOT stick (verified). So `run_job(job, eager=True)` calls `build_chain(...).apply()` to run inline
  — that's how the `--sync` command and the whole test suite drive the pipeline without a broker.
  Don't reach for `override_settings(CELERY_TASK_ALWAYS_EAGER=...)` in a test; it won't work.
- **Real-vendor SDKs (`replicate`, `fal_client`) are imported INSIDE the Real client methods**
  (`# noqa: PLC0415`), never at module top, so a fake-only run imports cleanly. Keep it that way.
- **SQLite + two writers (web + worker).** WAL mode + `busy_timeout` are set in
  `config/settings.py` `DATABASES.OPTIONS.init_command` (Django 5.1+ feature). Don't remove them.
- **Real provider request shapes are best-effort and untested live** (you can't hit the vendors in
  CI). When you wire a vendor for real, verify its actual API and fix the client — they're plausible
  guesses, not verified contracts. Lip-sync especially: test on real *sung* audio.
- **Tests need real `ffmpeg`/`ffprobe` on PATH** (the compose + pipeline tests run them on
  `fixtures/`). The Docker image installs ffmpeg; a host venv run needs it too.
- **`PROVIDER_MODE` is global.** Per-stage live/fake overrides aren't wired yet — a documented
  extension point. To go live incrementally, flip the whole mode and supply the keys for the stages
  you've reached (cheap → expensive, lip-sync last).

## Adding things

- **A new provider backend:** implement the Protocol in `providers/base.py`, add `Real*`/`Fake*`
  classes, wire the `get_*` factory. Fake copies a fixture; Real defers its SDK import and raises
  `ProviderConfigError` on a missing key.
- **A new stage:** add a thin `@shared_task(**_TASK_OPTS)` in `stages/tasks.py`, insert it into
  `build_chain` in `jobs/orchestrator.py`, add a `JobContext` field for its artifact (bump
  `SCHEMA_VERSION`), and cover it in `tests/test_pipeline.py`.

## Conventions quick-ref

Exception discipline (no swallow/fallback — `make discipline`), absolute module-level imports,
mypy clean, coverage ratchets up-only, gitleaks on secrets, `JobContext` carries `schema_version`.
The hooks (`.pre-commit-config.yaml`) enforce most of this; `make hooks-install` once per clone.
