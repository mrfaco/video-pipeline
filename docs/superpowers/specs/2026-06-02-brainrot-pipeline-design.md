# Brainrot — Automated TikTok Video Pipeline (Design)

**Date:** 2026-06-02
**Status:** Approved, in build

## Concept

Config-driven pipeline turning **(preset song + theme + a locked synthetic character)** into a
finished 9:16 video: an invented ultra-realistic talking head lip-synced to the song, over a
looping animated background, with karaoke captions. The `.mp4` is delivered to **Telegram** for
manual review/posting. Runs on a **Raspberry Pi 5** as a thin orchestrator — every heavy stage is
a cloud API call.

## Locked decisions

- **Subject:** invented synthetic human (no rights holder → monetizable, no strikes).
- **Posting:** manual via Telegram. Embedded song is a **guide track only** (muted on post).
- **Hosting:** cloud APIs only; the Pi fires HTTP and runs ffmpeg.
- **Job state:** **SQLite** (WAL mode). No Postgres, no `db` container.
- **Stack:** inherited from `opportunity-finder` — Django 5 + DRF + django-unfold, Celery + Redis,
  `django-celery-beat`/`-results`, pydantic, httpx. Python 3.13.

## Architecture

### The Real/Fake provider split (the key decision)

"End-to-end with tests" cannot mean "every cloud vendor live." Each cloud stage calls a **provider
client** with two interchangeable backends selected by `settings.PROVIDER_MODE`:

- **`real`** — HTTP to Replicate / fal / lip-sync vendor.
- **`fake`** — returns bundled fixture artifacts, no network, no spend.

The **ffmpeg compose** and **Telegram delivery** stages are real (free/local). The test suite runs
the *entire chain* with `PROVIDER_MODE=fake`, producing a real (tiny) `output.mp4`, with only the
outbound Telegram POST mocked. Turning a stage live = set env var + drop in a key. This is how
vendors get wired incrementally (cheap → expensive, lip-sync last) without touching architecture.

### Django apps

- **`core`** — `JobContext` (pydantic, `schema_version`'d, the `ctx` passed between tasks),
  `job_id`-namespaced storage helpers.
- **`jobs`** — `Job` + `Artifact` models, preset loading/validation, `run_job()` orchestrator
  (Celery `chain` + error callback), unfold admin + "Run job" action.
- **`stages`** — the 7 idempotent `@shared_task`s. Each: validate `ctx` → call a
  provider/compose/delivery → return `ctx`. `max_retries=3`, `retry_backoff=True`.
- **`providers`** — `base.py` (Protocols + `get_providers()` factory), `replicate.py`
  (Demucs, WhisperX), `fal.py` (FLUX still/portrait, image→video), `lipsync.py`
  (Hedra/Sync/MagicHour). Each: `Real*` + `Fake*`. Pydantic-typed I/O. Loud failures.
- **`compose`** — `ffmpeg.py` (boomerang loop + final 1080×1920 chromakey overlay + burned
  captions + guide-track mux), `captions.py` (build `.ass` from word timestamps).
- **`delivery`** — `telegram.py` (Bot API `sendVideo` via httpx).
- **`api`** — DRF: Bearer-key auth, `POST` trigger job, `GET` job status.

### Pipeline (Celery chain)

```
prepare_assets → separate_vocals → align_captions → generate_visuals
  → lipsync_render → compose_video → deliver_telegram
```

`ctx` (a `JobContext` serialized to dict) flows through, accumulating artifact paths under
`media/jobs/<job_id>/`. On final failure, an error callback delivers a Telegram message naming the
stage that died.

### The 7 stages

1. **prepare_assets** (Pi) — load preset, validate, normalize audio, build initial `ctx`.
2. **separate_vocals** (Replicate/Demucs) — clean vocal stem for the lip-sync input.
3. **align_captions** (Replicate/WhisperX) — word timestamps → `.ass`. Skippable if captions off.
4. **generate_visuals** (fal) — FLUX still → image→video bg loop; FLUX greenscreen portrait.
5. **lipsync_render** (Hedra/Sync/MagicHour) — portrait + vocal stem → talking head.
6. **compose_video** (Pi/ffmpeg) — boomerang-loop bg, chromakey overlay, burn captions, mux guide.
7. **deliver_telegram** (Pi) — send mp4 + suggested caption/hashtags.

## Testing

Bundled fixtures (tiny song clip, lyrics, green-matte portrait png, short bg mp4). Full-chain test
with `PROVIDER_MODE=fake` → real ffmpeg composes a real `output.mp4` → Telegram POST mocked. Plus
unit tests per Real provider (request shape via httpx mock), per ffmpeg filter builder, per preset
validator. Coverage ratchet starts at the suite's first floor.

## Conventions (inherited, enforced by hooks)

Exception discipline (loud failures, no fallbacks), absolute module-level imports, every change
tested, coverage ratchet up-only, mypy clean, gitleaks, schema versioning on structured artifacts.

## Deferred (seams left in place)

Real vendor keys/calls, LoRA/InstantID identity-locking, render-API offload (Shotstack/Creatomate),
Celery-beat scheduled batches.
