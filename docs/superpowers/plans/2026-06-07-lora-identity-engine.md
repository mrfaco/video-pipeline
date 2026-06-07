# LoRA Identity Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** Render a character's scene-gen stills via her trained Flux LoRA (`fal-ai/flux-lora` + trigger) instead of PuLID, for dance/mimic/glow-up.

**Architecture:** A third, highest-priority identity branch in `RealFalSceneGenerator.generate(lora, trigger)`; `character.lora`/`trigger` flow preset → Job → ctx → `generate_visuals`.

**Spec:** `docs/superpowers/specs/2026-06-07-lora-identity-engine-design.md`

---

### Task 1: Settings
**Files:** `config/settings.py` (near `CHARACTER_SCENE_MODEL`, ~line 188)

- [ ] Add:
```python
# LoRA identity path (highest priority in scene-gen): a character's trained Flux
# LoRA renders her photoreal + consistent via fal-ai/flux-lora, beating PuLID.
LORA_INFERENCE_MODEL = env("LORA_INFERENCE_MODEL", default="fal-ai/flux-lora")
LORA_SCALE = env.float("LORA_SCALE", default=1.0)
```
- [ ] Verify: `./venv/bin/python -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); django.setup(); from django.conf import settings; print(settings.LORA_INFERENCE_MODEL, settings.LORA_SCALE)"` → `fal-ai/flux-lora 1.0`
- [ ] Commit: `feat(settings): LoRA inference model + scale`

---

### Task 2: Context fields (schema 12)
**Files:** `core/context.py`; test `tests/test_context.py`

- [ ] Write failing test in `tests/test_context.py`:
```python
def test_context_carries_lora_fields():
    ctx = JobContext(
        job_id="j", theme="t", character_ref="", song_path="",
        character_lora="https://x/l.safetensors", character_trigger="neongirl",
    )
    rt = JobContext.from_dict(ctx.to_dict())
    assert rt.character_lora == "https://x/l.safetensors"
    assert rt.character_trigger == "neongirl"
    assert rt.schema_version == 12
```
- [ ] Run → FAIL (extra fields forbidden / schema 11).
- [ ] Implement: `SCHEMA_VERSION = 12`; after `character_image` field add:
```python
    # A trained Flux LoRA for the character (URL or local path) + its trigger
    # word. When set, scene-gen renders her via the LoRA (photoreal + consistent)
    # instead of PuLID. None = fall back to reference_image/PuLID.
    character_lora: str | None = None
    character_trigger: str | None = None
```
- [ ] Run → PASS. Commit: `feat(context): character_lora + trigger (schema v12)`

---

### Task 3: SceneGenerator Protocol + Fake
**Files:** `providers/base.py`, `providers/fakes.py`; test `tests/test_providers.py`

- [ ] Write failing test in `tests/test_providers.py`:
```python
def test_fake_scene_generator_accepts_lora(tmp_path):
    from providers.fakes import FakeSceneGenerator
    out = tmp_path / "s.png"
    r = FakeSceneGenerator().generate("p", out, lora="https://x/l.safetensors", trigger="neongirl")
    assert r == out and out.exists()
```
- [ ] Run → FAIL (unexpected kwargs).
- [ ] `providers/base.py`: change the `SceneGenerator` Protocol signature to:
```python
    def generate(
        self, prompt: str, out_path: Path,
        reference_image: Path | None = None,
        lora: str | None = None, trigger: str | None = None,
    ) -> Path:
```
- [ ] `providers/fakes.py`: `FakeSceneGenerator.generate` signature:
```python
    def generate(self, prompt: str, out_path: Path, reference_image: Path | None = None,
                 lora: str | None = None, trigger: str | None = None) -> Path:
        return _copy_fixture("background_still.png", out_path)
```
- [ ] Run → PASS. Commit: `feat(providers): SceneGenerator lora/trigger params + Fake`

---

### Task 4: RealFalSceneGenerator LoRA branch
**Files:** `providers/fal.py`

- [ ] Change `RealFalSceneGenerator.generate` signature to match the Protocol (add `lora`, `trigger`), and add the LoRA branch FIRST:
```python
    def generate(
        self, prompt: str, out_path: Path,
        reference_image: Path | None = None,
        lora: str | None = None, trigger: str | None = None,
    ) -> Path:
        import fal_client  # noqa: PLC0415  (heavy optional SDK, real-mode only)

        # A trained LoRA is the strongest identity path — photoreal + consistent.
        # lora is a URL (used directly) or a local file (uploaded). The trigger
        # word activates the LoRA and must lead the prompt.
        if lora:
            ref = lora if str(lora).startswith("http") else fal_client.upload_file(Path(lora))
            full_prompt = f"{trigger}, {prompt}" if trigger else prompt
            result = fal_client.subscribe(
                settings.LORA_INFERENCE_MODEL,
                arguments={
                    "prompt": full_prompt,
                    "loras": [{"path": ref, "scale": settings.LORA_SCALE}],
                    "image_size": "portrait_16_9",
                    "num_inference_steps": 30,
                    "guidance_scale": 3.5,
                    "num_images": 1,
                    "enable_safety_checker": False,
                },
            )
            return _download(_result_url(result, "images"), out_path)
        if reference_image is not None:
            ...  # (existing PuLID branch unchanged)
        ...  # (existing flux-pro branch unchanged)
```
(Keep the existing PuLID + flux-pro branches exactly as they are, after the new `if lora:` block.)
- [ ] Smoke: `DJANGO_SETTINGS_MODULE=config.settings ./venv/bin/python -c "import django; django.setup(); import providers.fal"` → no error.
- [ ] `./venv/bin/ruff check providers/ && ./venv/bin/mypy providers/fal.py providers/base.py providers/fakes.py`
- [ ] Commit: `feat(providers): RealFalSceneGenerator LoRA identity branch`

---

### Task 5: Job model + migration
**Files:** `jobs/models.py`, migration

- [ ] In `jobs/models.py` after `character_image`:
```python
    # Trained Flux LoRA (URL or local path) + trigger word for the character.
    # When set, scene-gen renders her via the LoRA instead of PuLID.
    character_lora = models.CharField(max_length=1000, blank=True)
    character_trigger = models.CharField(max_length=100, blank=True)
```
- [ ] `./venv/bin/python manage.py makemigrations jobs` → `0012_job_character_lora...`
- [ ] `./venv/bin/python manage.py migrate`
- [ ] Commit: `feat(models): Job.character_lora + character_trigger`

---

### Task 6: Preset parsing
**Files:** `jobs/presets.py`; test `tests/test_pipeline.py`

- [ ] Write failing tests in `tests/test_pipeline.py`:
```python
def test_load_preset_parses_lora(tmp_path):
    p = tmp_path / "l.yaml"
    p.write_text(
        "song:\n  audio: fixtures/song.mp3\ntheme: t\nmode: dance\n"
        "character:\n  image: fixtures/character_portrait.png\n"
        "  lora: https://x/l.safetensors\n  trigger: neongirl\n",
        encoding="utf-8",
    )
    pr = load_preset(str(p))
    assert pr["character_lora"] == "https://x/l.safetensors"
    assert pr["character_trigger"] == "neongirl"


@pytest.mark.django_db
def test_create_job_stores_lora(tmp_path):
    p = tmp_path / "l.yaml"
    p.write_text(
        "song:\n  audio: fixtures/song.mp3\ntheme: t\nmode: dance\n"
        "character:\n  image: fixtures/character_portrait.png\n"
        "  lora: https://x/l.safetensors\n  trigger: neongirl\n",
        encoding="utf-8",
    )
    with override_settings(MEDIA_ROOT=tmp_path):
        job = create_job_from_preset(str(p))
    assert job.character_lora == "https://x/l.safetensors"
    assert job.character_trigger == "neongirl"
```
- [ ] Run → FAIL (KeyError character_lora).
- [ ] In `jobs/presets.py`, change `_parse_character` to return `(ref, image, lora, trigger)`:
  - At the top, read once: `lora = str(block.get("lora")).strip() if block.get("lora") else ""` and `trigger = str(block.get("trigger")).strip() if block.get("trigger") else ""`.
  - Keep the existing `image`/`identity_asset`/`description` logic, but return them WITH lora+trigger appended. The "exactly one of image/description/identity_asset" check stays — `lora`/`trigger` are extra optional keys not counted in that check.
  - Each `return` in `_parse_character` becomes a 4-tuple: e.g. `return str(image_path), str(image_path), lora, trigger`, `return str(identity_path), "", lora, trigger`, `return str(block["description"]).strip(), "", lora, trigger`.
- [ ] Update the two call sites in `load_preset`:
```python
    if character:
        character_ref, character_image, character_lora, character_trigger = _parse_character(character, "character")
    else:
        character_ref, character_image, character_lora, character_trigger = "", "", "", ""
    ...
    backup = data.get("backup")
    if backup:
        backup_ref, backup_image, _, _ = _parse_character(backup, "backup")
```
- [ ] Add to the returned dict: `"character_lora": character_lora, "character_trigger": character_trigger,`
- [ ] In `create_job_from_preset`, add to `Job.objects.create(...)`: `character_lora=preset["character_lora"], character_trigger=preset["character_trigger"],`
- [ ] Run → PASS (new + existing preset tests). Commit: `feat(presets): parse character.lora + trigger`

---

### Task 7: Thread lora through prepare_assets + generate_visuals
**Files:** `stages/tasks.py`

- [ ] In `prepare_assets`, add to BOTH `JobContext(...)` constructions (the dance/closeup path and — if present — others that set character fields) the fields:
```python
        character_lora=(job.character_lora or None),
        character_trigger=(job.character_trigger or None),
```
(The main `ctx = JobContext(...)` near line 153, and the `mimic` branch's `JobContext(...)`.)
- [ ] In `generate_visuals`, the dance/vibe scene-gen loop and the mimic branch: pass the lora to the scene gen. For the dance branch's `get_scene_generator().generate(prompt, still, reference_image=reference)` → add `lora=ctx.character_lora, trigger=ctx.character_trigger`. For the mimic branch's `get_scene_generator().generate(prompt, still, reference_image=reference)` → same.
- [ ] Smoke: `DJANGO_SETTINGS_MODULE=config.settings ./venv/bin/python -c "import django; django.setup(); import stages.tasks"` → ok.
- [ ] Commit: `feat(stages): thread character_lora/trigger into scene-gen`

---

### Task 8: End-to-end test
**Files:** `tests/test_pipeline.py`

- [ ] Add:
```python
@pytest.mark.django_db
def test_pipeline_dance_with_lora(tmp_path):
    p = tmp_path / "l.yaml"
    p.write_text(
        "song:\n  audio: fixtures/song.mp3\ntheme: a neon city\nmode: dance\n"
        "character:\n  image: fixtures/character_portrait.png\n"
        "  lora: https://x/l.safetensors\n  trigger: neongirl\n",
        encoding="utf-8",
    )
    with override_settings(
        MEDIA_ROOT=tmp_path, PROVIDER_MODE="fake", TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID=""
    ):
        job = create_job_from_preset(str(p))
        assert job.character_lora
        run_job(job, eager=True)
        job.refresh_from_db()
        assert job.status == Job.Status.DELIVERED, job.error_detail
        assert _ffprobe_has_video(Path(job.output_path))
        assert "scene" in set(Artifact.objects.filter(job=job).values_list("kind", flat=True))
```
- [ ] Run → PASS. Commit: `test(pipeline): dance with character.lora runs end-to-end`

---

### Task 9: Wire the neon girl presets + full gate
**Files:** her presets (gitignored chars referenced), `CLAUDE.md`

- [ ] Read her LoRA URL: `head -1 presets/characters/neon_girl.lora.txt`.
- [ ] Add `lora:` (that URL) + `trigger: neongirl` under `character:` in `presets/dance_neon_girl.yaml`, the four `presets/dance_neon_girl_*.yaml`, and `presets/mimic_neon_girl.yaml`.
- [ ] Verify each still parses: `load_preset(...)` returns `character_lora` set.
- [ ] Full gate: `./venv/bin/pytest -q` (or targeted: test_context, test_providers, test_pipeline) + `./venv/bin/ruff check . && ./venv/bin/mypy . && python3 scripts/check_exception_discipline.py`.
- [ ] Update `CLAUDE.md`: note the LoRA identity path (scene-gen priority: lora → PuLID → flux-pro).
- [ ] Commit: `feat(presets): neon girl uses her LoRA for scene-gen; docs`

---

## Self-Review
- Spec coverage: settings(T1), context(T2), Protocol+Fake(T3), Real branch(T4), model(T5), presets(T6), stages(T7), e2e(T8), wire+docs(T9). ✓
- Type consistency: `generate(prompt, out_path, reference_image=None, lora=None, trigger=None)` identical across Protocol(T3)/Fake(T3)/Real(T4)/call sites(T7). `_parse_character` 4-tuple updated at all 3 returns + 2 call sites (T6). `character_lora`/`character_trigger` consistent across context/model/preset/stages.
- Placeholder scan: `https://x/l.safetensors` is a test fixture value; real URL injected in T9 from `neon_girl.lora.txt`. No TBDs.
