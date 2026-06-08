"""Seedream scene generator (photoreal, reference-image identity) + vibe-mode
character (the "comfort post" lane: her in a scene, slow, mute, no caption).

Alma was switched off the FLUX-1 LoRA onto Seedream 4.5 for realism; identity is
locked by reference images, not a LoRA. A preset picks the backend per-job with
``scene_generator:`` and runs ``mode: vibe`` with a ``character:`` for the slow,
mute, captionless comfort loop.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from django.test import override_settings

from jobs.presets import create_job_from_preset, load_preset
from providers import base
from providers.base import ProviderConfigError


def _preset(tmp_path: Path, **extra: object) -> Path:
    data: dict = {"mode": "vibe", "theme": "a river at sunset", **extra}
    p = tmp_path / "p.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


# --- backend selection ------------------------------------------------------


@override_settings(PROVIDER_MODE="real", FAL_KEY="")
def test_real_seedream_requires_key() -> None:
    from providers.seedream import RealSeedreamSceneGenerator

    with pytest.raises(ProviderConfigError):
        RealSeedreamSceneGenerator()


@override_settings(PROVIDER_MODE="real", FAL_KEY="k")
def test_get_scene_generator_seedream_backend() -> None:
    from providers.seedream import RealSeedreamSceneGenerator

    assert isinstance(base.get_scene_generator(backend="seedream"), RealSeedreamSceneGenerator)


@override_settings(PROVIDER_MODE="real", FAL_KEY="k")
def test_get_scene_generator_fal_backend() -> None:
    from providers.fal import RealFalSceneGenerator

    assert isinstance(base.get_scene_generator(backend="fal"), RealFalSceneGenerator)


@override_settings(PROVIDER_MODE="fake")
def test_fake_scene_generator_ignores_backend() -> None:
    from providers.fakes import FakeSceneGenerator

    assert isinstance(base.get_scene_generator(backend="seedream"), FakeSceneGenerator)


# --- preset: scene_generator + vibe character -------------------------------


def test_preset_scene_generator_parsed(tmp_path: Path) -> None:
    preset = load_preset(_preset(tmp_path, scene_generator="seedream"))
    assert preset["scene_generator"] == "seedream"


def test_preset_scene_generator_defaults_blank(tmp_path: Path) -> None:
    assert load_preset(_preset(tmp_path))["scene_generator"] == ""


def test_preset_scene_generator_rejects_unknown(tmp_path: Path) -> None:
    from jobs.presets import PresetError

    with pytest.raises(PresetError):
        load_preset(_preset(tmp_path, scene_generator="midjourney"))


def test_vibe_accepts_a_character(tmp_path: Path) -> None:
    preset = load_preset(_preset(tmp_path, character={"image": "fixtures/character_portrait.png"}))
    assert preset["character_image"].endswith("character_portrait.png")


@pytest.mark.django_db
def test_create_job_sets_scene_generator(tmp_path: Path) -> None:
    job = create_job_from_preset(_preset(tmp_path, scene_generator="seedream"))
    assert job.scene_generator == "seedream"
