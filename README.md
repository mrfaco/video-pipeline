# brainrot

An automated, config-driven pipeline that turns **a preset song + a theme + a locked synthetic
character** into a finished vertical (9:16) video: an invented, ultra-realistic AI talking head
lip-synced to the song, sitting over a looping animated background, with karaoke-style captions.
The finished `.mp4` is delivered to **Telegram** for manual review and posting.

Designed to run on a **Raspberry Pi 5** as a thin always-on orchestrator — every heavy stage is a
cloud API call; the Pi only fires HTTP requests and runs `ffmpeg`.

> **Why these choices:** an *invented* synthetic human has no rights holder (no strikes,
> monetizable); *manual posting* skips the TikTok API audit and lets you attach TikTok's licensed
> in-app sound at post time (the embedded song is a **guide track only**, muted on post); *cloud
> APIs* mean the Pi never runs a GPU model. See `docs/superpowers/specs/` for the full design.

---

## How it works

A job is `(locked character) × (new song + theme)`. It runs as a Celery **chain** of seven
idempotent stages, each receiving and returning one `ctx` (`core.context.JobContext`) that carries
job state + artifact paths. All artifacts for a job live under `media/jobs/<job_id>/`.

```
prepare_assets → separate_vocals → align_captions → generate_visuals
  → lipsync_render → compose_video → deliver_telegram
```

| # | Stage | Runs on | Does |
|---|-------|---------|------|
| 1 | `prepare_assets`   | Pi (CPU)        | Load + validate preset, normalize audio, build `ctx` |
| 2 | `separate_vocals`  | Replicate/Demucs| Extract a clean vocal stem (better lip-sync input) |
| 3 | `align_captions`   | Replicate/WhisperX | Word timestamps → `.ass` captions (skippable) |
| 4 | `generate_visuals` | fal             | FLUX still → image→video bg loop; FLUX greenscreen portrait |
| 5 | `lipsync_render`   | Hedra/Sync/MagicHour | Portrait + vocal stem → talking-head clip |
| 6 | `compose_video`    | Pi/ffmpeg       | Loop bg, chromakey overlay, burn captions, mux guide audio → 1080×1920 mp4 |
| 7 | `deliver_telegram` | Pi              | Send the mp4 + suggested caption/hashtags to Telegram |

### The Real/Fake provider split

Every cloud stage calls a **provider client** (`providers/`) with two interchangeable backends,
selected by `PROVIDER_MODE`:

- **`fake`** (default) — returns bundled fixture artifacts. No network, no spend. This is what runs
  in tests and the default dev loop, and it exercises the *entire* chain (real `ffmpeg` compose,
  Telegram POST mocked in tests).
- **`real`** — HTTP to the cloud vendors. Flip one stage live by setting `PROVIDER_MODE=real` and
  supplying that vendor's key.

This is how you wire vendors **incrementally** (cheap → expensive, lip-sync last) without ever
touching the architecture.

---

## Quickstart

```bash
# 1. Configure
cp .env.example .env          # defaults run everything in PROVIDER_MODE=fake

# 2. Bring up the stack (web + celery worker + beat + redis)
make build
make up

# 3. In another shell: run the demo job through the whole pipeline (fake providers)
make run-job PRESET=presets/demo.yaml
# → produces media/jobs/<id>/output.mp4 and (with a Telegram token) delivers it

# Or trigger from the admin: http://localhost:8000/admin/  → Jobs → "Run pipeline" action
```

Local dev without Docker:

```bash
make dev-install              # install into ./venv
make hooks-install            # one-time: pre-commit + pre-push hooks
./venv/bin/python manage.py migrate
./venv/bin/python manage.py run_job presets/demo.yaml
```

---

## Going live, one stage at a time

The build sequence is intentionally incremental. Each step is a single env change + a key:

1. **Compose + deliver first.** With everything `fake`, confirm `make run-job` produces a real
   `output.mp4` and (with `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`) delivers it. This proves
   stages 6–7 end-to-end for free.
2. **Background visuals (cheapest generative).** `PROVIDER_MODE=real`, set `FAL_KEY`. Validate the
   FLUX still → image→video loop and the greenscreen portrait artifacts before chaining onward.
3. **Vocal separation + captions.** Set `REPLICATE_API_TOKEN` (+ the Demucs/WhisperX model refs).
   Cheap, low-risk.
4. **Lip-sync last** — it carries the singing-quality uncertainty. Pick `LIPSYNC_PROVIDER`
   (`hedra` | `sync` | `magic_hour`), set its key, and **test on real sung audio** before
   committing. Magic Hour if singing fidelity matters most.

> `PROVIDER_MODE` is currently global. To run, say, only background-video live while keeping the
> rest fake, the cleanest path is per-stage overrides — a documented extension point, not yet wired.

---

## Posting workflow (manual)

1. Receive the clip in Telegram.
2. Upload to TikTok, **set the clip's volume to 0**, add the official **in-app licensed sound**.
3. Because the lips were generated against that exact vocal, nudge the two waveforms into
   alignment (~10 seconds).
4. Set the **AI-generated content** disclosure flag (required for synthetic content).

---

## Make targets

| Target | What |
|--------|------|
| `make up` / `down` / `build` | Docker compose lifecycle |
| `make migrate` / `makemigrations` | Django migrations |
| `make run-job PRESET=…` | Trigger a pipeline run from a preset YAML |
| `make test` / `coverage` | pytest (+ coverage) in the web container |
| `make lint` / `format` / `typecheck` | ruff + mypy |
| `make discipline` | exception-discipline checker |
| `make coverage-ratchet` | raise the coverage floor to the current run (never lowers) |
| `make hooks-install` / `hooks-run` | pre-commit / pre-push hooks |

---

## Project layout

```
config/      Django project (settings, celery, urls). SQLite + Redis + Celery.
core/        JobContext (the ctx schema) + job_id-namespaced storage helpers.
jobs/        Job + Artifact models, preset loader, run_job() orchestrator, admin, run_job command.
stages/      The 7 Celery @shared_task stages (the pipeline spine).
providers/   Cloud clients with Real + Fake backends (replicate, fal, lipsync) + base interfaces.
compose/     ffmpeg compose (boomerang loop, chromakey overlay, caption burn-in, mux) + .ass builder.
delivery/    Telegram Bot API delivery.
api/         DRF: Bearer-key auth, trigger job, job status.
fixtures/    Tiny bundled media the Fake providers return (song, stem, portrait, bg loop, captions).
presets/     Job definitions (song + lyrics + theme + character).
scripts/     Hook helpers (exception discipline, coverage ratchet, migration sync).
```

## Conventions

This repo is deliberately AI-coded; the hooks keep the review burden low. Read **`AGENTS.md`**
before writing code — the headline rule is **loud failures: never swallow an exception, never
fall back to a default**. Plus: every change tested, coverage ratchets up-only, absolute
module-level imports, mypy clean, secrets never committed (gitleaks), schema versioning on
structured artifacts.

## Cost (real mode, approximate, mid-2026)

Per usable video ≈ **under ~$1**, dominated by lip-sync + background video. Apply a ~1.4× reroll
buffer on generative steps. Vocal sep / captions / FLUX stills are cents. See the design doc for
the full table.
