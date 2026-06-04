# Two-Mode Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `dance` mode (integrated scene-gen → high-motion Kling → no lip-sync) alongside the existing `closeup` mode (Hedra singer + side characters), selected by a preset `mode:` field.

**Architecture:** A `mode` field on JobContext/Job routes three stages (`generate_visuals`, `lipsync_render`, `compose_video`) to mode-specific collaborators; `separate_vocals` skips for dance. Dance adds one provider (`SceneGenerator`) and one compose function (`compose_scene`), reusing the existing Kling animator and the caption/kinetic compose blocks.

**Tech Stack:** Django + Celery, pydantic JobContext, fal (FLUX scene image + Kling i2v), ffmpeg, pytest.

**Spec:** `docs/superpowers/specs/2026-06-04-two-mode-pipeline-design.md`

---

## Task 1: `mode` on JobContext (schema bump)

**Files:**
- Modify: `core/context.py` (SCHEMA_VERSION, new fields)
- Test: `tests/test_context.py` (create if absent) or extend existing context coverage

- [ ] **Step 1: Write failing test** — in `tests/test_context.py`:

```python
from core.context import JobContext, SCHEMA_VERSION

def test_mode_defaults_to_dance():
    ctx = JobContext(job_id="j", theme="t", character_ref="c", song_path="s")
    assert ctx.mode == "dance"
    assert ctx.scene_clip_path is None
    assert SCHEMA_VERSION >= 5

def test_mode_roundtrips():
    ctx = JobContext(job_id="j", theme="t", character_ref="c", song_path="s", mode="closeup")
    assert JobContext.from_dict(ctx.to_dict()).mode == "closeup"
```

- [ ] **Step 2: Run, expect FAIL** — `venv/bin/python -m pytest tests/test_context.py -q --no-cov` → fails (`mode` unknown / extra forbidden).

- [ ] **Step 3: Implement** — in `core/context.py`: set `SCHEMA_VERSION = 5`; add after `enable_captions`:

```python
    # Pipeline mode: "dance" (integrated scene-gen + high-motion, no lip-sync)
    # or "closeup" (Hedra singer + matte + side characters).
    mode: str = "dance"
```

and add to the `generate_visuals` section:

```python
    # --- generate_visuals (dance mode) ---
    scene_clip_path: str | None = None
```

- [ ] **Step 4: Run, expect PASS** — `venv/bin/python -m pytest tests/test_context.py -q --no-cov`.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "Add mode + scene_clip_path to JobContext (schema v5)"`.

---

## Task 2: `mode` on Job + preset parsing

**Files:**
- Modify: `jobs/models.py` (add `mode` field), new migration `jobs/migrations/0006_job_mode.py`
- Modify: `jobs/presets.py` (parse + validate `mode:`, pass to job creation)
- Test: `tests/test_pipeline.py` (preset-loading tests live here)

- [ ] **Step 1: Write failing test** — in `tests/test_pipeline.py`:

```python
def test_load_preset_mode_defaults_and_parses(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("song:\n  audio: fixtures/song.mp3\ntheme: t\n"
                 "character:\n  image: fixtures/character_portrait.png\n", encoding="utf-8")
    assert load_preset(str(p))["mode"] == "dance"
    p.write_text("song:\n  audio: fixtures/song.mp3\ntheme: t\nmode: closeup\n"
                 "character:\n  image: fixtures/character_portrait.png\n", encoding="utf-8")
    assert load_preset(str(p))["mode"] == "closeup"

def test_load_preset_rejects_bad_mode(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("song:\n  audio: fixtures/song.mp3\ntheme: t\nmode: sideways\n"
                 "character:\n  image: fixtures/character_portrait.png\n", encoding="utf-8")
    with pytest.raises(PresetError):
        load_preset(str(p))
```

- [ ] **Step 2: Run, expect FAIL** — `venv/bin/python -m pytest tests/test_pipeline.py -k mode -q --no-cov`.

- [ ] **Step 3: Implement preset parsing** — in `jobs/presets.py`, in `load_preset`, after theme is read, add:

```python
    mode = str(data.get("mode", "dance")).strip().lower()
    if mode not in {"dance", "closeup"}:
        raise PresetError(f"{path}: mode must be 'dance' or 'closeup', got {mode!r}.")
```

and include `"mode": mode` in the returned dict. In `create_job_from_preset`, pass `mode=preset["mode"]` to `Job.objects.create(...)`.

- [ ] **Step 4: Implement model + migration** — in `jobs/models.py` add to `Job`:

```python
    mode = models.CharField(max_length=16, default="dance")
```

Then: `venv/bin/python manage.py makemigrations jobs -n job_mode`.

- [ ] **Step 5: Run, expect PASS** — `venv/bin/python -m pytest tests/test_pipeline.py -k mode -q --no-cov`; also `venv/bin/python manage.py makemigrations --check`.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "Add Job.mode + preset parsing/validation"`.

---

## Task 3: `SceneGenerator` provider (Real fal FLUX + Fake)

**Files:**
- Modify: `providers/base.py` (Protocol + `get_scene_generator`)
- Modify: `providers/fal.py` (`RealFalSceneGenerator`)
- Modify: `providers/fakes.py` (`FakeSceneGenerator`)
- Modify: `config/settings.py` (`SCENE_IMAGE_MODEL`, `SCENE_PROMPT_TEMPLATE`)
- Test: `tests/test_providers.py`

- [ ] **Step 1: Write failing test** — in `tests/test_providers.py`:

```python
from providers.base import get_scene_generator
from providers.fakes import FakeSceneGenerator

@override_settings(PROVIDER_MODE="fake")
def test_get_scene_generator_fake():
    assert isinstance(get_scene_generator(), FakeSceneGenerator)

def test_fake_scene_generator_writes_image(tmp_path):
    out = FakeSceneGenerator().generate("a girl dancing in a field", tmp_path / "scene.png")
    assert out.is_file()
```

(Add `from django.test import override_settings` if not already imported.)

- [ ] **Step 2: Run, expect FAIL** — `venv/bin/python -m pytest tests/test_providers.py -k scene -q --no-cov`.

- [ ] **Step 3: Implement settings** — in `config/settings.py` near `FAL_FLUX_MODEL`:

```python
SCENE_IMAGE_MODEL = env("SCENE_IMAGE_MODEL", default="fal-ai/flux-pro/v1.1-ultra")
SCENE_PROMPT_TEMPLATE = env(
    "SCENE_PROMPT_TEMPLATE",
    default=(
        "a stunning attractive young woman dancing energetically in {theme}, "
        "full body in frame, dynamic pose, cinematic lighting, photorealistic, "
        "highly detailed, vertical 9:16 composition, scroll-stopping"
    ),
)
DEFAULT_MODE = env("DEFAULT_MODE", default="dance")
```

- [ ] **Step 4: Implement Protocol + factory** — in `providers/base.py` add a `SceneGenerator` Protocol with `generate(self, prompt: str, out_path: Path) -> Path` and a `get_scene_generator()` factory mirroring `get_background_generator` (Real when `PROVIDER_MODE=="real"`, else Fake).

- [ ] **Step 5: Implement Fake** — in `providers/fakes.py`:

```python
class FakeSceneGenerator:
    """Copies a bundled scene still — no network, no spend."""

    def generate(self, prompt: str, out_path: Path) -> Path:
        return _copy_fixture("background_still.png", out_path)
```

(Use whatever fixture-copy helper the other fakes use; `background_still.png` exists.)

- [ ] **Step 6: Implement Real** — in `providers/fal.py`:

```python
class RealFalSceneGenerator:
    """One integrated scene still (character + environment) via FLUX on fal."""

    def __init__(self) -> None:
        if not settings.FAL_KEY:
            raise ProviderConfigError("FAL_KEY is empty; required for RealFalSceneGenerator.")
        self._model = settings.SCENE_IMAGE_MODEL

    def generate(self, prompt: str, out_path: Path) -> Path:
        import fal_client  # noqa: PLC0415

        result = fal_client.subscribe(
            self._model,
            arguments={"prompt": prompt, "aspect_ratio": "9:16"},
        )
        if not isinstance(result, dict):
            raise ProviderConfigError(f"scene-gen result is not a dict: {result!r}")
        images = result.get("images") or []
        url = images[0].get("url") if images and isinstance(images[0], dict) else None
        if not isinstance(url, str) or not url:
            raise ProviderConfigError(f"scene-gen result missing an image URL: {result!r}")
        return _download(url, out_path)
```

(Match the existing `_download` helper signature in `providers/fal.py`.)

- [ ] **Step 7: Run, expect PASS** — `venv/bin/python -m pytest tests/test_providers.py -k scene -q --no-cov`.

- [ ] **Step 8: Commit** — `git add -A && git commit -m "Add SceneGenerator provider (fal FLUX scene still + fake)"`.

---

## Task 4: `compose_scene` (single-clip compose: pad + captions + kinetic + mux)

**Files:**
- Modify: `compose/ffmpeg.py` (`compose_scene`)
- Test: `tests/test_compose.py`

- [ ] **Step 1: Write failing test** — in `tests/test_compose.py`:

```python
from compose.ffmpeg import compose_scene

def test_compose_scene_produces_video(tmp_path):
    out = compose_scene(
        scene_clip=FIXTURES_DIR / "character_lipsync.mp4",
        audio=FIXTURES_DIR / "song.mp3",
        captions=None,
        out_path=tmp_path / "dance.mp4",
        beat_zoom=1.035, beat_period=0.5, beat_offset=0.0, beat_decay=0.18, shake_px=2.5,
    )
    assert out.exists()
    assert probe_dimensions(out) == (1080, 1920)
```

- [ ] **Step 2: Run, expect FAIL** — `venv/bin/python -m pytest tests/test_compose.py -k scene -q --no-cov`.

- [ ] **Step 3: Implement** — in `compose/ffmpeg.py` add `compose_scene` that:
  - scales/pads the scene clip to `width`x`height` (`scale=...:force_original_aspect_ratio=decrease,pad=...,setsar=1`),
  - burns `captions` if given (reuse `_escape_subtitles_path`),
  - applies the same kinetic-camera zoompan block as `compose_final` (intro/beat/shake → factor out the zoompan-expression builder into a private helper `_kinetic_filter(...) -> str` and call it from both),
  - muxes audio, `-t min(audio, scene_clip)` (reuse `_probe_duration`),
  - takes the same kinetic kwargs as `compose_final` plus `intro_zoom/intro_seconds`.

  Refactor note: extract the zoom-term/zoompan string builder currently inline in `compose_final` into `_kinetic_filter(input_label, output_label, *, width, height, intro_zoom, intro_seconds, beat_zoom, beat_period, beat_offset, beat_decay, base_zoom, shake_px) -> str` and use it in both functions (DRY).

- [ ] **Step 4: Run, expect PASS** — `venv/bin/python -m pytest tests/test_compose.py -q --no-cov` (all compose tests, to confirm the refactor didn't break `compose_final`).

- [ ] **Step 5: Commit** — `git add -A && git commit -m "Add compose_scene + factor out kinetic filter builder"`.

---

## Task 5: Stage branching by mode

**Files:**
- Modify: `stages/tasks.py` (`separate_vocals`, `generate_visuals`, `lipsync_render`, `compose_video`)
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing test** — in `tests/test_pipeline.py`:

```python
@pytest.mark.django_db
def test_pipeline_dance_mode(tmp_path):
    p = tmp_path / "dance.yaml"
    p.write_text("song:\n  audio: fixtures/song.mp3\ntheme: a neon city\nmode: dance\n", encoding="utf-8")
    with override_settings(MEDIA_ROOT=tmp_path, PROVIDER_MODE="fake",
                           TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID=""):
        job = create_job_from_preset(str(p))
        run_job(job, eager=True)
        job.refresh_from_db()
        assert job.status == Job.Status.DELIVERED, job.error_detail
        assert _ffprobe_has_video(Path(job.output_path))
        kinds = set(Artifact.objects.filter(job=job).values_list("kind", flat=True))
        assert "scene" in kinds
        assert {"vocal_stem", "portrait", "lipsync"} & kinds == set()  # dance skips these
```

(Dance presets need no `character:` block — confirm `create_job_from_preset` allows a missing character when `mode == "dance"`; if it currently requires one, relax that in `jobs/presets.py` for dance mode and note it here.)

- [ ] **Step 2: Run, expect FAIL** — `venv/bin/python -m pytest tests/test_pipeline.py -k dance -q --no-cov`.

- [ ] **Step 3: Implement branching:**
  - `separate_vocals`: `if ctx.mode == "dance": return ctx.to_dict()` at the top (skip Demucs).
  - `generate_visuals`: `if ctx.mode == "dance":` build prompt from `settings.SCENE_PROMPT_TEMPLATE.format(theme=ctx.theme)`, `get_scene_generator().generate(prompt, scene_still)`, then `get_animator().animate(scene_still, scene_clip)`, set `ctx.scene_clip_path`, record artifact `kind="scene"`, return. Else existing flow.
  - `lipsync_render`: `if ctx.mode == "dance": return ctx.to_dict()` at the top.
  - `compose_video`: `if ctx.mode == "dance":` detect beats (existing `detect_beat_period`), call `compose_scene(scene_clip=..., audio=..., captions=..., kinetic kwargs...)`, set output, record, return. Else existing trio compose.

- [ ] **Step 4: Run, expect PASS** — `venv/bin/python -m pytest tests/test_pipeline.py -k dance -q --no-cov`.

- [ ] **Step 5: Keep closeup tests green** — existing presets (`demo.yaml`, trio/image tests) now default to `dance`. Set `mode: closeup` explicitly in `presets/demo.yaml` and any preset/test that exercises the trio/portrait/lipsync path. Run the full pipeline test file: `venv/bin/python -m pytest tests/test_pipeline.py -q --no-cov`.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "Branch stages by mode; dance skips vocals/lipsync"`.

---

## Task 6: Dance preset + full gates

**Files:**
- Create: `presets/dance_demo.yaml`
- Modify: closeup presets to set `mode: closeup` (if not done in Task 5)

- [ ] **Step 1: Create dance preset** — `presets/dance_demo.yaml`:

```yaml
# Dance mode: one integrated scene (girl + environment generated together) then
# animated with high-motion Kling. No greenscreen, no lip-sync. Same-vibe girl.
mode: dance
song:
  source: "https://vt.tiktok.com/ZSxowC4kY/"
theme: "a vast neon-lit rooftop at night, glowing city skyline, cinematic"
```

- [ ] **Step 2: Set closeup presets explicitly** — add `mode: closeup` to `presets/pink_blackhole_closeup.yaml`, `presets/trio.yaml`, `presets/pink_flower_field.yaml`, `presets/pink_flower_field_2.yaml`, `presets/pink_girl.yaml`, `presets/flower.yaml`, `presets/forest.yaml`, `presets/saturn.yaml`, `presets/brujeria.yaml`, `presets/demo.yaml`, `presets/from_source.yaml` (every existing preset that relies on the singer/composite path).

- [ ] **Step 3: Run full gates** —
  - `venv/bin/ruff check .`
  - `venv/bin/mypy core compose providers stages jobs config`
  - `venv/bin/python scripts/check_exception_discipline.py`
  - `venv/bin/python manage.py makemigrations --check`
  - `venv/bin/python -m pytest -q` (full suite + coverage ratchet)

- [ ] **Step 4: Commit** — `git add -A && git commit -m "Add dance_demo preset; pin existing presets to closeup mode"`.

- [ ] **Step 5: Push** — `git push origin main`.

---

## Self-review notes

- **Spec coverage:** mode field (T1/T2), SceneGenerator + models (T3), compose_scene (T4), stage branching incl. skips (T5), dance preset + closeup pinning + tests (T5/T6). All spec sections covered.
- **Default-mode hazard:** default `dance` flips existing presets' behavior — Task 5 Step 5 + Task 6 Step 2 explicitly pin every existing preset to `mode: closeup`. This is the riskiest change; do it before running the full suite.
- **DRY:** the kinetic zoompan string is factored into `_kinetic_filter` (T4) and shared by `compose_final` and `compose_scene`.
