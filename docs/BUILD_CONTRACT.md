# Build contract (for parallel implementation)

Exact interfaces every module codes against, so the pieces compose. Read alongside `AGENTS.md`
(loud failures, thin stages, Real/Fake split, absolute imports, every change tested).

## Shared types

- `core.context.JobContext` — the `ctx`. Paths are stored as **strings**; convert with `Path(...)`
  at use sites. Fields are documented in `core/context.py`.
- `core.storage.job_dir(job_id) -> Path` and `artifact_path(job_id, name) -> Path` — the **only**
  way to decide where a file goes. Everything lives under `media/jobs/<job_id>/`.
- `settings.FIXTURES_DIR` — `Path` to the committed fixtures the Fake providers return.
- `settings.PROVIDER_MODE` — `"fake"` | `"real"`.

## Providers (`providers/`)

Implement the Protocols in `providers/base.py`. Class names are referenced by the `get_*` factories
there — match them exactly.

- `providers/fakes.py`: `FakeVocalSeparator`, `FakeCaptionAligner`, `FakeBackgroundGenerator`,
  `FakePortraitGenerator`, `FakeLipSyncer`. Each method **copies** the relevant fixture into the
  given `out_path` and returns `out_path` (use `shutil.copyfile`). Fixture filenames:
  - vocal stem → `vocal_stem.wav`
  - caption word-timestamps → `word_timestamps.json`
  - background still → `background_still.png`; background loop → `background_loop.mp4`
  - portrait → `character_portrait.png`; lip-sync clip → `character_lipsync.mp4`
- `providers/replicate.py`: `RealDemucsSeparator`, `RealWhisperXAligner`. Defer
  `import replicate` to the callsite (`# noqa: PLC0415`). `__init__` raises
  `providers.base.ProviderConfigError` if `settings.REPLICATE_API_TOKEN` is empty.
- `providers/fal.py`: `RealFalBackgroundGenerator`, `RealFalPortraitGenerator`. Defer
  `import fal_client`. `__init__` raises `ProviderConfigError` if `settings.FAL_KEY` is empty.
- `providers/lipsync.py`: `RealHedraLipSyncer`, `RealSyncLipSyncer`, `RealMagicHourLipSyncer`.
  Use `httpx` against each vendor's REST API. `__init__` raises `ProviderConfigError` if the
  matching key is empty.

Real clients: implement request shape best-effort (these can't be tested live). Download the result
artifact to `out_path`. **No fallbacks** — a non-2xx or missing key raises.

WhisperX word-timestamps JSON shape (what the aligner writes / captions reads):
```json
{"language": "en", "word_segments": [{"word": "neon", "start": 0.1, "end": 0.55}, ...]}
```

## Compose (`compose/`)

- `compose/captions.py`:
  `build_ass(word_timestamps_path: Path, out_path: Path, *, width: int = 1080, height: int = 1920) -> Path`
  — read the `word_segments`, emit a karaoke-style `.ass` (one or few words on screen at their
  timestamps, centered low). Return `out_path`.
- `compose/ffmpeg.py`:
  `compose_final(*, background_loop: Path, character_clip: Path, audio: Path, captions: Path | None,
  out_path: Path, width: int = 1080, height: int = 1920, chroma_color: str = "0x00FF00") -> Path`
  — runs **real** ffmpeg: boomerang the bg loop, `-stream_loop` it under the chromakeyed character
  clip scaled to fit, burn `captions` if given, mux `audio` as a guide track, `-shortest`,
  `libx264 -pix_fmt yuv420p -movflags +faststart`. Output 9:16. Shell out via `subprocess.run(...,
  check=True)` — a non-zero ffmpeg exit must raise (`CalledProcessError` is fine, or translate).
  Tests run it on the fixtures and assert the output exists and `ffprobe` reports a video stream.

## Delivery (`delivery/`)

- `delivery/telegram.py`:
  `send_video(video_path: Path, caption: str, *, bot_token: str, chat_id: str) -> dict`
  — POST multipart to `https://api.telegram.org/bot<token>/sendVideo` via `httpx`. Raise if token or
  chat_id is empty, or if the response isn't `ok`. Return the parsed JSON `result`.
  Tests mock the HTTP call (no real network) and assert the URL/fields + the missing-token raise.

## Glue (built in the spine — `jobs/` + `stages/`)

The orchestrator + stages are built after providers/compose/delivery. They will import:
`providers.base.get_*`, `compose.ffmpeg.compose_final`, `compose.captions.build_ass`,
`delivery.telegram.send_video`. The API layer will import `jobs.orchestrator.run_job(job)` and
`jobs.presets.create_job_from_preset(preset_path)`.
