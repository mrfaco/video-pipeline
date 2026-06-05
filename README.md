# brainrot

An automated, config-driven pipeline that turns **a preset song + a theme** into a finished vertical
(9:16) video, delivered to **Telegram** for manual review and posting. It produces one of three kinds
of video, chosen per-preset by a `mode:` field:

- **`dance`** — a scroll-stopping dance clip: an attractive woman *and* her environment are generated
  together as one integrated, photoreal scene, animated with a high-motion model. No lip-sync. Layered
  with auto karaoke captions, a hook/title overlay, beat-synced scene cuts, a kinetic camera, and a
  seamless loop.
- **`closeup`** — an invented, ultra-realistic AI singing head lip-synced to the song, matted and
  composited over a generated background with small side characters, captioned.
- **`vibe`** — a clean cinematic "digital window" loop: a gorgeous scene (no people, no text) with a
  slow travelling/flythrough camera and a seamless loop. **Mute** (no song needed — add the sound at
  post). Built for replay/save/share.

Designed to run on a **Raspberry Pi 5** as a thin always-on orchestrator — every heavy stage is a
cloud API call; the Pi only fires HTTP requests and runs `ffmpeg`.

> **Why these choices:** an *invented* synthetic human has no rights holder (no strikes,
> monetizable); *manual posting* skips the TikTok API audit and lets you attach TikTok's licensed
> in-app sound at post time (the embedded song is a **guide track only**, muted on post); *cloud
> APIs* mean the Pi never runs a GPU model. See `docs/superpowers/specs/` for the full design.

---

## How it works

A job is `(song + theme [+ character]) × mode`. It runs as a Celery **chain** of seven idempotent
stages, each receiving and returning one `ctx` (`core.context.JobContext`) that carries job state +
artifact paths. Three stages branch on `mode`. All artifacts for a job live under `media/jobs/<job_id>/`.

```
prepare_assets → separate_vocals → align_captions → generate_visuals
  → lipsync_render → compose_video → deliver_telegram
```

| # | Stage | `dance` | `closeup` | `vibe` |
|---|-------|---------|-----------|--------|
| 1 | `prepare_assets`   | fetch + normalize audio | same | **skipped** (mute, no song) |
| 2 | `separate_vocals`  | stem (only to caption) | clean vocal stem for lip-sync | skipped |
| 3 | `align_captions`   | auto-transcribe stem → captions | full mix + preset lyrics | skipped |
| 4 | `generate_visuals` | scene-gen → Kling animate (×N for cuts) | FLUX bg loop + portrait(s) | scene-gen → Kling travelling cam |
| 5 | `lipsync_render`   | **skipped** | Hedra/OmniHuman (or Kling+resync) → matte | skipped |
| 6 | `compose_video`    | beat-cut + captions + hook + kinetic + loop | trio composite + captions + kinetic + loop | clean compose + loop, **mute** |
| 7 | `deliver_telegram` | send mp4 + caption | same | send mute mp4 |

### Viral levers (dance mode, all toggleable in settings)

- **Hook overlay** — a bold `hook:` title pinned at the top (e.g. "POV: …"), burned stable above the
  kinetic pass.
- **Beat-synced scene cuts** — `DANCE_SCENE_CUTS=N` generates N scenes and hard-cuts between them on
  the detected beat grid (N× generation cost).
- **Kinetic camera** — a per-frame `zoompan` pulsing the zoom on every beat + a subtle handheld shake.
- **Seamless loop** — dance via the Kling end-frame (or a compose crossfade); closeup via crossfade —
  so the platform's loop has no visible seam (boosts replays).
- **Platform-safe wardrobe** — the scene prompt enforces a fitted-but-clothed look; revealing outfits
  get age-restricted to ~0 views.

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

### Preset shapes

```yaml
# dance — no character needed; the scene model invents her
mode: dance
hook: "POV: when your song comes on in public"   # optional title overlay
song: { source: "https://vt.tiktok.com/…" }
theme: "a cozy modern home kitchen, warm golden light, cinematic"
```

```yaml
# closeup — a locked character (+ optional backup → trio) sings the song
mode: closeup
song: { source: "https://vt.tiktok.com/…" }
theme: "a swirling psychedelic dreamscape, no people"
character: { image: presets/characters/statue_man_closeup.png }
backup:    { image: presets/characters/chrome_man.png }
```

```yaml
# vibe — cinematic no-people loop; mute, so no song needed
mode: vibe
theme: "Hong Kong harbour at twilight, neon skyline reflected in rippling water"
```

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
4. **Lip-sync last** (`closeup` only) — it carries the singing-quality uncertainty. Pick
   `LIPSYNC_PROVIDER` (`hedra` | `omnihuman` | `sync` | `magic_hour`), set its key, and **test on real
   sung audio** before committing. `dance` mode has no lip-sync; its heavy spend is scene-gen + Kling
   (both on `FAL_KEY`), so a dance video only needs `FAL_KEY` (+ Replicate for captions).

> `PROVIDER_MODE` is currently global. To run, say, only background-video live while keeping the
> rest fake, the cleanest path is per-stage overrides — a documented extension point, not yet wired.

---

## Posting workflow (manual)

1. Receive the clip in Telegram.
2. Upload to TikTok, add the official **in-app licensed sound** (set the clip's volume to 0;
   `vibe` clips are already mute).
3. For `closeup` videos, because the lips were generated against that exact vocal, nudge the two
   waveforms into alignment (~10 seconds). `dance`/`vibe` have no lip-sync, so just line up the start.
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
core/        JobContext (the ctx schema) + job_id storage + audio/beat helpers.
jobs/        Job + Artifact models, preset loader (mode/hook parsing), run_job() orchestrator, admin.
stages/      The 7 Celery @shared_task stages; the dance/closeup branch logic lives here.
providers/   Cloud clients with Real + Fake backends + base Protocols/factories:
             replicate (Demucs, WhisperX), fal (FLUX still/portrait/scene-gen),
             motion (Kling animate + end-frame), matting (BiRefNet), lipsync (Hedra/OmniHuman/Sync/MagicHour).
compose/     ffmpeg: compose_final (trio), compose_scene (dance), beat_cut_concat, loop_seamless,
             crop/composite_window (resync), kinetic filter, + .ass caption/hook builders.
delivery/    Telegram Bot API delivery.
api/         DRF: Bearer-key auth, trigger job, job status.
fixtures/    Tiny bundled media the Fake providers return (song, stem, portrait, bg loop, captions).
presets/     Job definitions (mode + song + theme [+ character/backup/hook]); characters/ holds portraits.
scripts/     Hook helpers (exception discipline, coverage ratchet, migration sync).
```

## Conventions

This repo is deliberately AI-coded; the hooks keep the review burden low. Read **`AGENTS.md`**
before writing code — the headline rule is **loud failures: never swallow an exception, never
fall back to a default**. Plus: every change tested, coverage ratchets up-only, absolute
module-level imports, mypy clean, secrets never committed (gitleaks), schema versioning on
structured artifacts.

## Cost (real mode, approximate, mid-2026)

Per usable video ≈ **under ~$1**, dominated by the video-gen step — `closeup`: lip-sync + background
video; `dance`: the Kling scene animate (× `DANCE_SCENE_CUTS` for beat cuts); `vibe` is the cheapest
(one scene-gen + one Kling, no audio/lip-sync). Apply a ~1.4× reroll buffer on generative steps.
Vocal sep / captions / FLUX stills are cents. See the design doc for the full table.
