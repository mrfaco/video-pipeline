# Mimic Mode — Design

**Status:** approved (brainstorm 2026-06-06)
**Author:** pipeline work session

## What this adds

A **fourth pipeline mode**, `mimic`, that makes one of our **locked characters perform the
exact moves from a driving dance video**. It is true motion transfer (driving clip → the
character's pose), not Kling's loose approximation.

The proof-of-concept (neon girl performing a TikTok dance via `zsxkib/mimic-motion` on Replicate)
already validated the technique: identity and outfit hold, upper-body/arm choreography transfers
cleanly, lower legs go slightly soft on fast motion. This spec turns that manual PoC into a wired,
tested pipeline mode.

`mimic` is the cheapest "character does X" path that preserves a *specific* dance — reserved for
trending dances you want copied exactly. The general "she dances" case stays on `dance` (Kling).

## Where it sits among the modes

| Mode | Generates | Animator | Lip-sync | Audio |
|------|-----------|----------|----------|-------|
| `dance` | integrated scene (character + environment) | Kling (high-motion) | none | song + captions |
| `closeup` | bg + portrait | Hedra / Kling+resync | yes | song + captions |
| `vibe` | scene, no people | Kling (slow travel) | none | **mute** |
| **`mimic`** | **appearance still (locked character, PuLID)** | **MimicMotion (driving video)** | **none** | **mute** |

`mimic` reuses `dance`'s character/scene-gen plumbing (PuLID identity lock) for the appearance
still and reuses `vibe`'s mute-compose path, adding one new provider (motion transfer) and one new
input (the driving video).

## Preset shape

```yaml
mode: mimic
drive:
  source: "<tiktok-or-youtube-url>"   # the dance to copy
character:
  image: presets/characters/neon_girl.png   # REQUIRED — locked identity (PuLID reference)
theme: "neon cyber club, plain dark backdrop"   # the appearance still's setting
style: "metallic holographic crop top and shorts"  # optional; defaults to DANCE_CHARACTER_STYLE
hook: "she ate this 💅"   # optional top-anchored text overlay
# no song: key — mimic is mute
```

Rules (enforced in `jobs/presets.py`, loud at submit):

- `drive.source` is **required** for mimic. It is a URL (auto-downloaded) in practice; a local
  filesystem path is also accepted and used as-is. This mirrors `fetch_audio`, which already accepts
  a URL or a search query through one `source` field — and it is how the offline tests feed a
  bundled fixture clip without hitting the network.
- `character` is **required** for mimic (the appearance needs a locked identity). Same parse rules
  as closeup (`image` / `description` / `identity_asset`).
- `song` is **forbidden** for mimic (it is mute). A `song:` key on a mimic preset is a `PresetError`.
- `theme` is required (as for every mode). `style`, `hook` are optional.

## Data flow through the seven stages

```
prepare_assets → separate_vocals → align_captions → generate_visuals
  → lipsync_render → compose_video → deliver_telegram
   mimic:  (mute; fetch+normalize drive video)  skip  skip
           appearance-still(PuLID) + motion-transfer   skip   mute scene compose + hook + loop
```

1. **`prepare_assets`** — mimic is **mute** (like vibe): no audio fetch/normalize. Instead it
   acquires the **driving video**: `fetch_video(drive_source, drive_raw.mp4)` (yt-dlp), then
   `normalize_video(...)` → `drive.mp4` (scale/center-crop to 9:16, strip audio, cap length).
   Returns a `JobContext` with `mode="mimic"`, `enable_captions=False`, `song_path=""`,
   `drive_video_path` set, `character_image`/`character_ref` carried, `hook`/`style`/`theme` carried.

2. **`separate_vocals`** — skipped. The existing guard
   (`ctx.mode != "closeup" and not (ctx.mode == "dance" and ctx.enable_captions)`) already returns
   early for mimic; no change needed.

3. **`align_captions`** — skipped (`enable_captions=False` returns early). No change needed.

4. **`generate_visuals`** — new mimic branch:
   1. **Appearance still:** `get_scene_generator().generate(prompt, still, reference_image=character_image)`
      where `prompt = MIMIC_SCENE_PROMPT_TEMPLATE.format(theme=…, style=…)` — a full-body, standing,
      neutral-pose figure on a clean backdrop (clean background tracks far better in MimicMotion).
      PuLID locks the character's identity from `character_image`.
   2. **Motion transfer:** `get_motion_transfer().transfer(still, drive_video, motion_clip)` →
      the character performs the driving dance. Stored in `ctx.scene_clip_path` (reusing the dance
      field) so compose treats it like any single scene clip. Records `scene` artifact.

5. **`lipsync_render`** — skipped (`mode != "closeup"` returns early). No change needed.

6. **`compose_video`** — new mimic branch, between the `vibe` and `dance` branches:
   - `audio = None` (mute, like vibe).
   - Optional `hook_captions` from `ctx.hook` (top-anchored `build_hook_ass`).
   - No captions, no kinetic camera (kinetic needs a beat grid, which needs audio).
   - `compose_scene(scene_clip=scene_clip_path, audio=None, captions=None,
     hook_captions=hook_captions, out_path=compose_target)`.
   - Seamless loop: `crossfade_loop = LOOP_SEAMLESS_ENABLED` (mimic falls into the non-dance branch
     of the existing crossfade selection), then `loop_seamless(...)`.

7. **`deliver_telegram`** — unchanged.

## New components

### `providers/motion_transfer.py`

```
MotionTransfer (Protocol):
    transfer(appearance_image: Path, motion_video: Path, out_path: Path) -> Path
```

- **`RealMimicMotion`** — Replicate `MIMICMOTION_MODEL`
  (`zsxkib/mimic-motion:b3edd455f68ec4ccf045da8732be7db837cb8832d1a2459ef057ddcd3ff87dea`).
  Constructor raises `ProviderConfigError` if `REPLICATE_API_TOKEN` is empty.
  **Explicit prediction polling** (not `client.run()`): MimicMotion renders for minutes and the
  blocking call hits an httpx `ReadTimeout` on cold start (observed in the PoC). So: create the
  prediction (`client.predictions.create(version=<hash>, input={...})`), poll `prediction.reload()`
  until a terminal status, raise `ProviderConfigError` on `failed`/`canceled` or an empty output,
  then download `output[0]`. Inputs: `appearance_image` (file), `motion_video` (file),
  `resolution=MIMICMOTION_RESOLUTION`, `output_frames_per_second=MIMICMOTION_FPS`. The `replicate`
  SDK is imported inside the method (deferred, real-mode only), per house rule.
- **`FakeMotionTransfer`** — copies a bundled fixture clip into `out_path` (no network), so the
  whole chain runs in `PROVIDER_MODE=fake`.

`providers/base.py` gains the `MotionTransfer` Protocol and a `get_motion_transfer()` factory
(`fake` → `FakeMotionTransfer`, `real` → `RealMimicMotion`).

### `core/fetch.py` → `fetch_video(source, out_path)`

yt-dlp download of the best progressive mp4 (`-f "bv*+ba/b"` merged to mp4, or `best[ext=mp4]`),
`--no-playlist`, transient-retry like `fetch_audio`. If `source` is **not** a URL and points at an
existing local file, copy it through unchanged (the test path). Raises `VideoFetchError` on failure
or a missing output.

### `compose/ffmpeg.py` → `normalize_video(in_path, out_path, width, height, max_seconds)`

ffmpeg: scale to cover then center-crop to `width`x`height` (9:16), `-an` (strip audio), trim to
`max_seconds`, re-encode H.264. Returns `out_path`.

### Settings (`config/settings.py`)

- `MIMICMOTION_MODEL` — the Replicate `owner/name:version` string.
- `MIMICMOTION_RESOLUTION` — `576` (PoC default; raise to 768 for quality once validated).
- `MIMICMOTION_FPS` — `24`.
- `MIMIC_SCENE_PROMPT_TEMPLATE` — full-body, standing, neutral pose, clean/plain backdrop, with the
  same modesty/safety clause as `SCENE_PROMPT_TEMPLATE`; `{theme}` and `{style}` slots.
- `DRIVE_WIDTH` / `DRIVE_HEIGHT` — `1080` / `1920`.
- `DRIVE_MAX_SECONDS` — cap on the driving clip length (cost control), e.g. `10`.

### `core/context.py`

- Add input `drive_source: str = ""` and artifact `drive_video_path: str | None = None`.
- Reuse `scene_clip_path` for the motion-transfer output.
- Bump `SCHEMA_VERSION` 10 → 11.

### `jobs/models.py` + migration

- `Job.drive_source = models.CharField(max_length=1000, blank=True)`.
- Migration `0011_job_drive_source`.

### `jobs/presets.py`

- Accept `mode == "mimic"` (add to the valid set).
- For `mimic`: require `character` (like closeup) and require `drive.source`; forbid `song`.
- Parse `drive.source` → `drive_source`; pass through to the Job.
- `create_job_from_preset` stores `drive_source` on the Job (no copy — it is a URL or an external
  path resolved at fetch time).

### Preset

`presets/mimic_neon_girl.yaml` — neon girl (`character.image`), a driving dance URL placeholder,
a cyber theme, optional hook.

## Testing

All in `PROVIDER_MODE=fake`, no network, no spend:

1. **End-to-end mimic run** (`tests/test_pipeline.py`): a mimic preset whose `drive.source` is a
   bundled fixture clip path and whose `character.image` is a fixture portrait. Run the chain via
   `.apply()`; assert the appearance still, the motion clip (`scene_clip_path`), and the looped
   `output.mp4` exist, and that the output is mute.
2. **`FakeMotionTransfer`** unit test: `transfer(...)` writes the fixture to `out_path`.
3. **`fetch_video` local passthrough** test: a local path copies through; a malformed/empty source
   raises `VideoFetchError`.
4. **Preset validation** (`tests/test_presets.py`): mimic requires `drive` and `character`; a mimic
   preset with `song:` raises `PresetError`; a valid mimic preset parses with `mode == "mimic"` and
   `drive_source` set.
5. **`normalize_video`** test: produces a file at the target dimensions with no audio stream.

Fixtures: reuse an existing bundled mp4 (e.g. `fixtures/background_loop.mp4`) as both the driving
clip and the `FakeMotionTransfer` output; reuse `fixtures/character_portrait.png` as the appearance
fixture via `FakeSceneGenerator` (already returns `background_still.png`).

## Error handling (loud, no fallbacks — AGENTS.md §1)

- Missing `REPLICATE_API_TOKEN` → `ProviderConfigError` at `RealMimicMotion` construction.
- MimicMotion prediction `failed`/`canceled`/empty output → `ProviderConfigError`.
- yt-dlp failure or missing downloaded file → `VideoFetchError`.
- Missing `drive`/`character`, or a `song:` on a mimic preset → `PresetError` at submit.

## Out of scope (YAGNI)

- UI/screen-recording crop knobs (default is scale-to-fill 9:16 of a clean download).
- Carrying a song / captions / beat-sync kinetic on mimic (it is mute by design).
- Per-stage live/fake overrides (still global `PROVIDER_MODE`).
- Higher-res / longer renders are a settings change (`MIMICMOTION_RESOLUTION`, `DRIVE_MAX_SECONDS`),
  not new code.
