# Two-mode pipeline: `dance` and `closeup`

**Date:** 2026-06-04
**Status:** Approved (design)
**Supersedes nothing** — extends `2026-06-02-brainrot-pipeline-design.md`.

## Goal

Split the pipeline into two purpose-built modes, each using the right tool for
its job instead of forcing one path to do everything:

- **`dance`** — a scroll-stopping, visually-attractive dancing video. The
  character and environment are generated **together as one integrated scene**
  (no greenscreen, no matting, no compositing seams), then animated with a
  high-motion model. **No lip-sync** ("leave the lipsync alone"). Character is
  *same vibe, not exact face* — an attractive girl consistent within each video,
  not necessarily the locked `pink_girl`. Visual quality is the priority.
- **`closeup`** — the proven singer method: a head-and-shoulders portrait
  lip-synced with **Hedra**, matted, and composited over a themed background with
  small side characters (e.g. moons). This is exactly today's black-hole-video
  flow, unchanged.

## Mode selection

A new optional preset field:

```yaml
mode: dance      # or: closeup. Unset => dance (the new default).
```

Carried through as a field on `Job` (new column + migration) and `JobContext`
(new field; bump `SCHEMA_VERSION` 4 → 5). Validated to the set `{dance, closeup}`
at preset load; unknown values raise `PresetError`.

## The branching chain

The same seven-task Celery chain runs for both modes. Three stages branch on
`ctx.mode`; the rest are identical. Branch logic lives in the **stages** (thin
dispatch to a mode-appropriate collaborator), per the module boundaries in
AGENTS.md §5.

| Stage | `dance` | `closeup` (current) |
|-------|---------|---------------------|
| `prepare_assets` | fetch + normalize audio | identical |
| `separate_vocals` | **skip** (no lip-sync needs the stem) | Demucs → vocal stem |
| `align_captions` | **skip** (dance carries no captions — visuals carry it) | identical |
| `generate_visuals` | **scene** flow (below) | background still+loop + portrait(s) |
| `lipsync_render` | **skip** (no-op passthrough of `ctx`) | Hedra on portrait(s) + side chars + matte |
| `compose_video` | **scene compose** (below) | trio composite over background |
| `deliver_telegram` | identical | identical |

### `dance` generate_visuals

One new collaborator, `SceneGenerator` (image: an attractive girl dancing in the
themed environment, fully integrated), then the **existing Kling animator**
animates that still:

1. `scene_still = SceneGenerator.generate(theme_prompt) -> scene_still.png`
2. `scene_clip  = Animator.animate(scene_still) -> scene_motion.mp4` (Kling)

`scene_clip` is recorded as the `scene` artifact and carried on
`ctx.scene_clip_path`. No portrait, no background loop, no matting.

### `dance` compose_video

`compose_scene(scene_clip, audio, captions?) -> output.mp4`:

- stream nothing / overlay nothing — the scene clip *is* the full frame
- scale/pad to 1080×1920 if the i2v output aspect differs
- optional burned-in karaoke captions (`align_captions` output)
- the existing **kinetic camera** pass (beat-synced zoom + calm shake)
- mux audio, bound duration to `min(audio, scene_clip)` (same rule as today)

This reuses `compose/ffmpeg.py` building blocks (caption burn, zoompan kinetic
pass, duration bound); it is a sibling to `compose_final`, not a rewrite of it.

### `closeup` path

Unchanged. `generate_visuals`, `lipsync_render` (Hedra), and `compose_video`
(trio composite with the `TRIO_*` knobs) behave exactly as in the approved
black-hole render. The `mode` branch simply routes to the existing functions.

## Models (dance mode)

- **Scene still** — the scroll-stopping frame. Best photoreal image model live on
  fal (FLUX 1.1 [pro]/ultra-class), behind a `SCENE_IMAGE_MODEL` setting so it's
  swappable. Regenerate-until-gorgeous is a manual re-run for now (no auto-rank).
- **Motion** — **Kling 2.5 turbo pro** (already integrated and validated), via the
  existing `KLING_MODEL` setting. Swappable, so we can A/B against
  Seedance / Minimax-Hailuo later and keep the winner. This is the high-motion
  lever.

Real/Fake split holds: `SceneGenerator` gets a `Real*` (fal FLUX) and a `Fake*`
(copies a fixture still); the Kling animator already has both.

## New / changed surfaces

- `core/context.py` — add `mode` + `scene_clip_path`; bump `SCHEMA_VERSION` to 5.
- `jobs/models.py` — `Job.mode` column + migration; `jobs/presets.py` parses
  `mode:` and validates it.
- `providers/base.py` — `SceneGenerator` Protocol + `get_scene_generator()`.
- `providers/fal.py` — `RealFalSceneGenerator`; `providers/fakes.py` —
  `FakeSceneGenerator`.
- `compose/ffmpeg.py` — `compose_scene(...)` (single-clip compose: pad + captions
  + kinetic + mux).
- `stages/tasks.py` — `mode` dispatch in `generate_visuals`, `lipsync_render`
  (skip), `compose_video`; `separate_vocals` skips for dance.
- `config/settings.py` — `SCENE_IMAGE_MODEL`, `DEFAULT_MODE=dance`,
  scene prompt template.
- `presets/` — a `dance` example preset; keep the closeup ones.

## Testing

- Fake-mode end-to-end test for `mode: dance` (scene-gen fixture → fake Kling →
  real ffmpeg compose_scene → `output.mp4`), asserting no portrait/matte/lipsync
  artifacts are produced and a video stream exists.
- Existing `closeup`/trio/motion_first tests stay green (mode defaults preserve
  them or are set explicitly).
- `compose_scene` unit test (pad to 1080×1920 + captions + kinetic) like the
  existing `compose_final` tests.
- Coverage ratchet stays ≥ current floor; lint/mypy/exception-discipline clean.

## Out of scope (YAGNI)

- Auto-ranking / auto-regenerating the scene still for "best" frame.
- Per-stage live/fake mode overrides.
- Companions/side-characters in dance mode (the scene model draws any extras into
  the frame via prompt if wanted).
- Benchmarking alternative motion models (deferred; swappable via setting).
