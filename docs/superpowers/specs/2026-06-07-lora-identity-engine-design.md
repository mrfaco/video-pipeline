# LoRA Identity Engine — Design

**Status:** approved (brainstorm 2026-06-07)
**Author:** pipeline work session

## What this adds

A trained-LoRA identity path for the scene generator. When a character has a trained Flux LoRA,
her stills render via `fal-ai/flux-lora` (the LoRA + a trigger word) — **photorealistic and
identity-consistent** — instead of PuLID, which trades realism for face-lock.

Validated by a PoC: a LoRA trained on the neon girl (`fal-ai/flux-lora-fast-training`, 17-image
dataset, trigger `neongirl`) renders her far more photorealistically than `flux-pulid` while keeping
her identity. This wires that LoRA into the pipeline so every scene-gen mode uses it.

**Scope:** the scene generator only — `dance`, `mimic` (the appearance still), and the (future)
glow-up. `closeup` keeps its static `character.image` portrait for now (a documented follow-on).

## Identity-path priority (the core change)

`SceneGenerator.generate` gains a third, highest-priority path:

1. **`lora` set** → `fal-ai/flux-lora`: `loras=[{path, scale}]`, the `trigger` word prepended to the
   prompt, 9:16 image size, safety-checker off. ← NEW
2. else **`reference_image` set** → `fal-ai/flux-pulid` (current PuLID identity path).
3. else → `fal-ai/flux-pro/v1.1-ultra` (current; max realism, no identity lock).

The LoRA path needs **no reference image** — the LoRA *is* the identity.

## Components

### `providers/base.py`
Extend the Protocol:
```
SceneGenerator.generate(prompt, out_path, reference_image=None, lora=None, trigger=None) -> Path
```

### `providers/fal.py` — `RealFalSceneGenerator.generate`
New branch when `lora` is set, before the PuLID branch:
- Resolve the LoRA reference: if `lora` starts with `http` → use the URL directly; else treat it as a
  local file path and `fal_client.upload_file(...)` it.
- Prompt = `f"{trigger}, {prompt}"` when `trigger` is set (LoRA activation), else the prompt as-is.
- Call `settings.LORA_INFERENCE_MODEL` (`fal-ai/flux-lora`) with `loras=[{"path": ref, "scale":
  settings.LORA_SCALE}]`, `image_size="portrait_16_9"`, `num_inference_steps=30`,
  `guidance_scale=3.5`, `enable_safety_checker=False`, `num_images=1`.
- Download `result["images"][0]["url"]` (raise if missing — no silent degrade).
The `fal_client` import stays at the callsite (real-mode only).

### `providers/fakes.py` — `FakeSceneGenerator.generate`
Accept `lora=None, trigger=None` (ignored) and keep copying the bundled still, so the whole chain
runs in fake mode regardless of identity path.

### `config/settings.py`
- `LORA_INFERENCE_MODEL = env("LORA_INFERENCE_MODEL", default="fal-ai/flux-lora")`
- `LORA_SCALE = env.float("LORA_SCALE", default=1.0)`

### `core/context.py`
- Add `character_lora: str | None = None` and `character_trigger: str | None = None`.
- Bump `SCHEMA_VERSION` 11 → 12.

### `jobs/models.py` + migration `0012_job_character_lora`
- `Job.character_lora = models.CharField(max_length=1000, blank=True)`
- `Job.character_trigger = models.CharField(max_length=100, blank=True)`

### `jobs/presets.py`
- `_parse_character` accepts optional `lora` (URL or path) and `trigger` in the character block, in
  addition to the existing `image`/`description`/`identity_asset`. A character may have **both** an
  `image` (kept for closeup / as the PuLID fallback) **and** a `lora` (used by scene-gen). Return
  `(ref, image, lora, trigger)`.
- `load_preset` returns `character_lora`, `character_trigger`; `create_job_from_preset` stores them
  on the Job. The lora value is **not** copied into the job dir (it is a URL or an external local
  path resolved at generation time).

### `stages/tasks.py` — `generate_visuals`
For the `dance`/`mimic` scene-gen calls, pass `lora=ctx.character_lora, trigger=ctx.character_trigger`.
When `lora` is set it takes priority; the PuLID `reference` is still computed but the LoRA branch wins
inside the provider (so a character with both lora and image uses the lora for scene-gen).

### Neon girl presets
Add to her character blocks (`dance_neon_girl.yaml`, the four `dance_neon_girl_*` outfit presets,
`mimic_neon_girl.yaml`):
```yaml
character:
  image: presets/characters/neon_girl.png      # kept (closeup / fallback)
  lora: "<her fal.media LoRA url>"              # used by scene-gen
  trigger: neongirl
```
The LoRA URL + the local `.safetensors` backup live in the gitignored `presets/characters/`
(`neon_girl.lora.txt`, `neon_girl.lora.safetensors`). If the fal.media URL ever expires, switch the
preset `lora:` to the local `.safetensors` path (the code uploads it).

## Data flow

```
preset character.lora/trigger → Job.character_lora/trigger → ctx.character_lora/trigger
  → generate_visuals → get_scene_generator().generate(..., lora=, trigger=) → fal-ai/flux-lora
```

## Error handling (loud — AGENTS.md §1)

- `lora` that is neither a URL nor an existing file → raise (no silent fallback to PuLID).
- `fal-ai/flux-lora` non-2xx or missing image URL → raise.
- Missing `FAL_KEY` → existing `ProviderConfigError` at construction.

## Testing (all `PROVIDER_MODE=fake`, no network)

1. **`FakeSceneGenerator`** accepts `lora`/`trigger` (signature test) and still returns the fixture.
2. **Preset parsing** (`tests/test_pipeline.py`): a character with `lora` + `trigger` parses; both
   land on the Job via `create_job_from_preset`. A character with only `image` still works (no lora).
3. **Context** (`tests/test_context.py`): schema-12 round-trip carries `character_lora`/`trigger`.
4. **End-to-end** (`tests/test_pipeline.py`): a dance preset with `character.lora` set runs the full
   chain in fake mode (Fake scene-gen ignores the lora, real ffmpeg composes) → delivers a video,
   and the `scene` artifact is recorded. Confirms the lora threads through without breaking the chain.

## Out of scope (YAGNI)

- Routing `closeup` portraits through the LoRA (documented follow-on).
- Training new LoRAs in-pipeline (training stays the manual `flux-lora-fast-training` step; this spec
  only consumes a trained LoRA).
- Per-stage LoRA scale overrides beyond the global `LORA_SCALE`.
