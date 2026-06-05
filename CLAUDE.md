# CLAUDE.md

Guidance for AI agents working in this repo. Read **`AGENTS.md`** first — it holds the hard rules
(loud failures, thin stages, every change tested). This file is the mental model + the gotchas.

## What this is

A config-driven pipeline that turns **(preset song + theme [+ character])** into a finished 9:16
captioned, seamless-looping video delivered to Telegram. Runs on a Raspberry Pi 5 as a thin
orchestrator: every heavy step is a cloud API call; the Pi only runs `ffmpeg` and HTTP. Job state is
**SQLite**. Designs: `docs/superpowers/specs/2026-06-02-brainrot-pipeline-design.md` (original
single-mode) and `2026-06-04-two-mode-pipeline-design.md` (the dance/closeup split below).

## The three modes (most important concept)

A preset's `mode:` field picks one of three pipelines (default `dance`), carried on `Job` +
`JobContext`:

- **`dance`** — a scroll-stopping dance video. The woman AND her environment are generated
  **together as one integrated scene** (`SceneGenerator` → fal FLUX pro ultra), then animated by the
  high-motion Kling animator. **No greenscreen, no matte, no compositing, no lip-sync.** Character is
  "same vibe, not exact face" (a fresh attractive woman each render; lock a winner later). Plays the
  scroll-stop levers: auto karaoke captions, a `hook:` title overlay, beat-synced scene cuts, kinetic
  camera, seamless loop, platform-safe wardrobe (see gotchas).
- **`closeup`** — a singing-head video: a portrait lip-synced (Hedra for a frontal face; or Kling
  `motion_first` + the resync layer for full-body) → BiRefNet matte → trio composite over a
  generated background, with small side characters. This is the original pipeline; all pre-existing
  presets are pinned to `mode: closeup`.
- **`vibe`** — a clean cinematic "digital window" loop (scenery, NO people, NO text). Scene-gen a
  gorgeous scene → Kling with a **slow travelling/flythrough camera** → clean compose (no captions,
  no hook, no kinetic) → seamless loop. **Mute** — `prepare_assets` skips the audio fetch entirely
  (a vibe preset needs no `song:`); the operator adds the sound at post. The cheapest mode (one
  scene-gen + one Kling). Reuses the dance scene-gen plumbing; skips vocals/captions/lipsync.

## Architecture in one breath

Seven idempotent Celery tasks run as a `chain`, passing one `ctx` (`core.context.JobContext`,
serialized to a dict over the wire) from link to link. Three stages branch on `ctx.mode`:

```
prepare_assets → separate_vocals → align_captions → generate_visuals
  → lipsync_render → compose_video → deliver_telegram
   dance:   stem(caption only)  scene-gen+Kling   skip      scene compose (cuts/hook/kinetic/loop)
   closeup: vocal stem          bg+portrait     Hedra+matte  trio composite + loop
   vibe:    (mute: prepare skips audio)  scene-gen+Kling(travel)  skip   clean compose + loop, no audio
```

Each stage is **thin**: mark progress, call ONE provider/compose/delivery function, record an
`Artifact`, return `ctx`. All artifacts live under `media/jobs/<job_id>/` (via `core.storage`).

### The Real/Fake provider split (most important concept)

Every cloud stage calls a client from `providers/` chosen by `settings.PROVIDER_MODE`:
- `fake` (default, and what tests use) → `providers/fakes.py` copies a bundled `fixtures/` artifact.
  No network, no spend. Exercises the whole chain (both modes).
- `real` → `providers/replicate.py` (Demucs, WhisperX), `providers/fal.py` (FLUX still/portrait +
  **scene-gen**), `providers/motion.py` (Kling animate, with `tail_image_url` end-frame),
  `providers/matting.py` (BiRefNet), `providers/lipsync.py` (Hedra/OmniHuman/Sync/MagicHour +
  video-lipsync). Selected via `providers/base.py` `get_*` factories.

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
- **FLUX's safety checker returns an all-BLACK image when it flags a prompt** ("attractive woman
  dancing" trips it), and Kling then hallucinates garbage from the black frame. `RealFalSceneGenerator`
  passes `enable_safety_checker: False` + `safety_tolerance: "6"` — keep it; control modesty via the
  prompt, not the checker.
- **Wardrobe = reach.** Revealing outfits (bikini/lingerie) get the videos age-restricted and
  suppressed (~0 views). `SCENE_PROMPT_TEMPLATE` deliberately specifies a fitted-but-clothed
  ("subtly sexy, no nudity/lingerie/swimwear") look. Don't loosen it without knowing the cost.
- **The intro zoom-punch fights a seamless loop** (frame 0 zoomed vs the last frame; it re-triggers
  each loop). Dance disables it when looping. Keep that.
- **Dance loop: `crossfade` vs `endframe`.** `endframe` (Kling start==tail frame) is pixel-seamless
  but the motion *settles* into a stationary last ~second. Default `crossfade` keeps full energy and
  dissolves the wrap. See `DANCE_LOOP_MODE`.
- **Caption tooling, by mode.** Closeup transcribes the full mix guided by preset `lyrics:`. Dance
  has no lyrics, so it runs Demucs and transcribes the isolated **vocal stem** (a full music mix
  doesn't transcribe). An untranscribable song raises `EmptyTranscriptionError`, which the stage
  catches and skips captions (never fails the render). The **hook overlay + captions are burned
  AFTER the kinetic pass** so they stay stable, not zoomed.
- **Vibe is mute and song-less.** `prepare_assets` returns early for vibe (no fetch/normalize), and
  `compose_scene`/`loop_seamless` accept `audio=None` to produce a mute mp4. The `song:` preset key
  is optional for vibe only. Don't assume `ctx.song_normalized_path` is set — guard on `mode`.
- **Vibe camera is a travelling flythrough, not a static pan** (`VIBE_MOTION_PROMPT` + a lower
  `VIBE_KLING_CFG` for more movement). The user wanted "like the viewer is travelling."
- **Closeup framing dictates the lip-sync tool.** Full-body → `motion_first` (Kling) + the resync
  layer (crop+upscale the small head, lip-sync that, paste back). Close-up singer → `lipsync` +
  Hedra (frontal). Kling on a close-up makes the face look down/away → broken sync.
- **The trio boss must be NARROW** (full-body or a portrait crop). A wide bust scaled by height
  overflows 1080px and hides the flanks; crop it to portrait and float small companions via the
  `TRIO_FLANK_*` knobs (the "moons"/companions layout).

## Adding things

- **A new provider backend:** implement the Protocol in `providers/base.py`, add `Real*`/`Fake*`
  classes, wire the `get_*` factory. Fake copies a fixture; Real defers its SDK import and raises
  `ProviderConfigError` on a missing key.
- **A new stage:** add a thin `@shared_task(**_TASK_OPTS)` in `stages/tasks.py`, insert it into
  `build_chain` in `jobs/orchestrator.py`, add a `JobContext` field for its artifact (bump
  `SCHEMA_VERSION`), and cover it in `tests/test_pipeline.py`.
- **A new character:** drop a portrait into `presets/characters/` and add a preset (closeup mode).
  A wide bust also wants a portrait crop (`*_closeup.png`) for trio/boss use.
- **A new viral lever:** compose-only effects (hook, beat cuts, kinetic, loop) live in
  `compose/ffmpeg.py` as pure functions and are wired in `compose_video`; they re-compose from cached
  clips, so iterate on the look without re-paying for generation.

## Conventions quick-ref

Exception discipline (no swallow/fallback — `make discipline`), absolute module-level imports,
mypy clean, coverage ratchets up-only, gitleaks on secrets, `JobContext` carries `schema_version`.
The hooks (`.pre-commit-config.yaml`) enforce most of this; `make hooks-install` once per clone.
