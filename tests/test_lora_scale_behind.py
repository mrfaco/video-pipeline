"""Per-preset ``lora_scale`` + ``framing: behind`` (the follow-from-behind walk).

A glamour-trained identity LoRA needs ~1.0 to hold in a new scene, but the global
default is 0.6 (realism) — so a preset can pin its own ``lora_scale``. And the
dance/close scene templates assume a face-forward subject; ``framing: behind``
frames the character walking away from the camera (the "that girl" POV). These
keep such presets self-contained (a plain run_job, no env overrides).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from django.conf import settings

from jobs.presets import create_job_from_preset, load_preset
from providers.fakes import FakeSceneGenerator


def _preset(tmp_path: Path, **extra: object) -> Path:
    data: dict = {
        "mode": "dance", "theme": "a street", "style": "a look",
        "song": {"source": "some song"}, **extra,
    }
    p = tmp_path / "p.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_framing_behind_allowed(tmp_path: Path) -> None:
    assert load_preset(_preset(tmp_path, framing="behind"))["framing"] == "behind"


def test_lora_scale_parsed(tmp_path: Path) -> None:
    assert load_preset(_preset(tmp_path, lora_scale=1.0))["lora_scale"] == 1.0


def test_lora_scale_optional(tmp_path: Path) -> None:
    assert load_preset(_preset(tmp_path))["lora_scale"] is None


def test_scene_prompt_behind_setting() -> None:
    tmpl = settings.SCENE_PROMPT_BEHIND
    assert "{theme}" in tmpl and "{style}" in tmpl
    assert "behind" in tmpl.lower()


def test_fake_scene_generator_accepts_lora_scale(tmp_path: Path) -> None:
    out = FakeSceneGenerator().generate(
        "p", tmp_path / "s.png", lora="l", trigger="t", lora_scale=1.0
    )
    assert out.exists()


@pytest.mark.django_db
def test_create_job_threads_framing_and_lora_scale(tmp_path: Path) -> None:
    job = create_job_from_preset(_preset(tmp_path, framing="behind", lora_scale=0.9))
    assert job.framing == "behind"
    assert job.lora_scale == 0.9
