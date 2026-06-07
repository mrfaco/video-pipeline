"""Realism is the standing default for every render (the user's hard rule).

These guard against a regression back to the glossy "AI-influencer" FLUX look:
the scene-prompt templates must default to amateur-phone / realistic-skin
vocabulary and must NOT carry the glossy triggers ("cinematic", "photorealistic,
highly detailed") that produce the waxy over-graded render. The LoRA scale
default is also lowered so a glamour-trained identity LoRA doesn't override the
realism cues on the face.
"""

from __future__ import annotations

from django.conf import settings

# The glossy trigger phrases that push FLUX toward the AI-render look.
_GLOSSY = ("cinematic", "photorealistic, highly detailed", "scroll-stopping")
# At least one of these realism cues must be present.
_REALISM = ("amateur", "phone", "realistic", "unretouched", "true-to-life")


def _assert_realistic(template: str) -> None:
    low = template.lower()
    assert any(cue in low for cue in _REALISM), f"no realism cue in: {template!r}"
    for glossy in _GLOSSY:
        assert glossy not in low, f"glossy trigger {glossy!r} still present in: {template!r}"


def test_lora_scale_defaults_to_realism() -> None:
    # A glamour-trained LoRA at full strength welds heavy makeup/waxy skin onto
    # the face regardless of prompt; a lower default lets realism cues land.
    assert settings.LORA_SCALE <= 0.7


def test_close_scene_prompt_is_realistic() -> None:
    _assert_realistic(settings.SCENE_PROMPT_CLOSE)
    assert "{style}" in settings.SCENE_PROMPT_CLOSE
    assert "{theme}" in settings.SCENE_PROMPT_CLOSE


def test_full_body_scene_prompt_is_realistic() -> None:
    _assert_realistic(settings.SCENE_PROMPT_TEMPLATE)
    assert "{style}" in settings.SCENE_PROMPT_TEMPLATE
    assert "{theme}" in settings.SCENE_PROMPT_TEMPLATE


def test_mimic_scene_prompt_is_realistic() -> None:
    _assert_realistic(settings.MIMIC_SCENE_PROMPT_TEMPLATE)
    assert "{style}" in settings.MIMIC_SCENE_PROMPT_TEMPLATE
    assert "{theme}" in settings.MIMIC_SCENE_PROMPT_TEMPLATE


def test_realism_keeps_wardrobe_safety_clause() -> None:
    # Realism must not drop the platform-safe wardrobe guard (reach concern).
    for template in (settings.SCENE_PROMPT_TEMPLATE, settings.SCENE_PROMPT_CLOSE):
        assert "no nudity" in template.lower()
