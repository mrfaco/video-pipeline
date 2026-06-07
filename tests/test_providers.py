"""Tests for the provider layer: Fakes copy fixtures, factories select the
right backend, and Real clients fail loudly when their key is missing.

Everything runs with ``PROVIDER_MODE=fake`` and never touches the network —
the Real clients are only exercised at construction time (which must raise on
a blank key) and via the factory's class selection.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings

from providers import base
from providers.base import ProviderConfigError
from providers.fakes import (
    FakeBackgroundGenerator,
    FakeCaptionAligner,
    FakeLipSyncer,
    FakePortraitGenerator,
    FakeVocalSeparator,
)
from providers.fal import RealFalBackgroundGenerator, RealFalPortraitGenerator
from providers.lipsync import (
    RealHedraLipSyncer,
    RealMagicHourLipSyncer,
    RealSyncLipSyncer,
)
from providers.replicate import RealDemucsSeparator, RealWhisperXAligner


def _fixture_bytes(name: str) -> bytes:
    return (Path(settings.FIXTURES_DIR) / name).read_bytes()


# --- Fakes copy the matching fixture verbatim ------------------------------


def test_fake_vocal_separator_copies_stem(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "vocals.wav"
    result = FakeVocalSeparator().separate(tmp_path / "song.mp3", out)
    assert result == out
    assert out.exists()
    assert out.read_bytes() == _fixture_bytes("vocal_stem.wav")


def test_fake_caption_aligner_copies_timestamps(tmp_path: Path) -> None:
    out = tmp_path / "words.json"
    result = FakeCaptionAligner().align(tmp_path / "a.wav", "neon dreams", out)
    assert result == out
    assert out.read_bytes() == _fixture_bytes("word_timestamps.json")


def test_fake_background_generator_copies_still_and_loop(tmp_path: Path) -> None:
    gen = FakeBackgroundGenerator()
    still = tmp_path / "still.png"
    loop = tmp_path / "loop.mp4"
    assert gen.generate_still("vaporwave", still) == still
    assert gen.animate(still, loop) == loop
    assert still.read_bytes() == _fixture_bytes("background_still.png")
    assert loop.read_bytes() == _fixture_bytes("background_loop.mp4")


def test_fake_portrait_generator_copies_portrait(tmp_path: Path) -> None:
    out = tmp_path / "portrait.png"
    result = FakePortraitGenerator().generate("a wizard", out)
    assert result == out
    assert out.read_bytes() == _fixture_bytes("character_portrait.png")


def test_fake_lip_syncer_copies_clip(tmp_path: Path) -> None:
    out = tmp_path / "talking.mp4"
    result = FakeLipSyncer().sync(tmp_path / "p.png", tmp_path / "a.wav", out)
    assert result == out
    assert out.read_bytes() == _fixture_bytes("character_lipsync.mp4")


# --- Factories return the Fake backend in fake mode ------------------------


@override_settings(PROVIDER_MODE="fake")
def test_factories_return_fakes() -> None:
    assert isinstance(base.get_vocal_separator(), FakeVocalSeparator)
    assert isinstance(base.get_caption_aligner(), FakeCaptionAligner)
    assert isinstance(base.get_background_generator(), FakeBackgroundGenerator)
    assert isinstance(base.get_portrait_generator(), FakePortraitGenerator)
    assert isinstance(base.get_lip_syncer(), FakeLipSyncer)


# --- Real clients raise loudly when their key is blank ---------------------


@override_settings(PROVIDER_MODE="real", REPLICATE_API_TOKEN="")
def test_real_demucs_requires_token() -> None:
    with pytest.raises(ProviderConfigError):
        RealDemucsSeparator()


@override_settings(PROVIDER_MODE="real", REPLICATE_API_TOKEN="")
def test_real_whisperx_requires_token() -> None:
    with pytest.raises(ProviderConfigError):
        RealWhisperXAligner()


@override_settings(PROVIDER_MODE="real", FAL_KEY="")
def test_real_fal_background_requires_key() -> None:
    with pytest.raises(ProviderConfigError):
        RealFalBackgroundGenerator()


@override_settings(PROVIDER_MODE="fake")
def test_get_scene_generator_fake() -> None:
    from providers.fakes import FakeSceneGenerator

    assert isinstance(base.get_scene_generator(), FakeSceneGenerator)


def test_fake_scene_generator_writes_image(tmp_path) -> None:
    from providers.fakes import FakeSceneGenerator

    out = FakeSceneGenerator().generate("a girl dancing in a field", tmp_path / "scene.png")
    assert out.is_file()


@override_settings(PROVIDER_MODE="real", FAL_KEY="")
def test_real_fal_scene_requires_key() -> None:
    from providers.fal import RealFalSceneGenerator

    with pytest.raises(ProviderConfigError):
        RealFalSceneGenerator()


@override_settings(PROVIDER_MODE="real", FAL_KEY="")
def test_real_fal_portrait_requires_key() -> None:
    with pytest.raises(ProviderConfigError):
        RealFalPortraitGenerator()


@override_settings(PROVIDER_MODE="real", HEDRA_API_KEY="")
def test_real_hedra_requires_key() -> None:
    with pytest.raises(ProviderConfigError):
        RealHedraLipSyncer()


@override_settings(PROVIDER_MODE="real", SYNC_API_KEY="")
def test_real_sync_requires_key() -> None:
    with pytest.raises(ProviderConfigError):
        RealSyncLipSyncer()


@override_settings(PROVIDER_MODE="real", MAGIC_HOUR_API_KEY="")
def test_real_magic_hour_requires_key() -> None:
    with pytest.raises(ProviderConfigError):
        RealMagicHourLipSyncer()


# --- get_lip_syncer selects the right Real client per LIPSYNC_PROVIDER ------
# The key is set so construction succeeds; no network call is made.


@override_settings(PROVIDER_MODE="real", LIPSYNC_PROVIDER="hedra", HEDRA_API_KEY="k")
def test_get_lip_syncer_hedra() -> None:
    assert isinstance(base.get_lip_syncer(), RealHedraLipSyncer)


@override_settings(PROVIDER_MODE="real", LIPSYNC_PROVIDER="sync", SYNC_API_KEY="k")
def test_get_lip_syncer_sync() -> None:
    assert isinstance(base.get_lip_syncer(), RealSyncLipSyncer)


@override_settings(PROVIDER_MODE="real", LIPSYNC_PROVIDER="magic_hour", MAGIC_HOUR_API_KEY="k")
def test_get_lip_syncer_magic_hour() -> None:
    assert isinstance(base.get_lip_syncer(), RealMagicHourLipSyncer)


@override_settings(PROVIDER_MODE="real", LIPSYNC_PROVIDER="nope")
def test_get_lip_syncer_unknown_raises() -> None:
    with pytest.raises(ProviderConfigError):
        base.get_lip_syncer()


def test_fake_motion_transfer_copies_fixture(tmp_path):
    from providers.fakes import FakeMotionTransfer

    out = tmp_path / "motion.mp4"
    result = FakeMotionTransfer().transfer(
        tmp_path / "appearance.png", tmp_path / "drive.mp4", out
    )
    assert result == out
    assert out.read_bytes() == _fixture_bytes("background_loop.mp4")


def test_get_motion_transfer_selects_backend():
    from providers.fakes import FakeMotionTransfer
    from providers.motion_transfer import RealMimicMotion, RealWanAnimate

    with override_settings(PROVIDER_MODE="fake"):
        assert isinstance(base.get_motion_transfer(), FakeMotionTransfer)
    with override_settings(
        PROVIDER_MODE="real", MOTION_TRANSFER_PROVIDER="wan_animate", FAL_KEY="k"
    ):
        assert isinstance(base.get_motion_transfer(), RealWanAnimate)
    with override_settings(
        PROVIDER_MODE="real", MOTION_TRANSFER_PROVIDER="mimicmotion", REPLICATE_API_TOKEN="tok"
    ):
        assert isinstance(base.get_motion_transfer(), RealMimicMotion)


def test_get_motion_transfer_rejects_unknown_provider():
    with override_settings(PROVIDER_MODE="real", MOTION_TRANSFER_PROVIDER="bogus"):
        with pytest.raises(ProviderConfigError):
            base.get_motion_transfer()


def test_real_mimic_motion_requires_token():
    from providers.motion_transfer import RealMimicMotion

    with override_settings(REPLICATE_API_TOKEN=""):
        with pytest.raises(ProviderConfigError):
            RealMimicMotion()


def test_real_wan_animate_requires_fal_key():
    from providers.motion_transfer import RealWanAnimate

    with override_settings(FAL_KEY=""):
        with pytest.raises(ProviderConfigError):
            RealWanAnimate()


def test_fake_scene_generator_accepts_lora(tmp_path):
    from providers.fakes import FakeSceneGenerator
    out = tmp_path / "s.png"
    r = FakeSceneGenerator().generate("p", out, lora="https://x/l.safetensors", trigger="neongirl")
    assert r == out and out.exists()
