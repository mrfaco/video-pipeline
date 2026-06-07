"""Tests for the trend-video → draft-preset authoring helper.

Covers the ``VideoUnderstander`` provider (the Fake returns structured fields
from a fixture, the factory selects it in fake mode, the Real client fails
loudly without a key) and the ``describe_trend`` management command (watches a
clip and writes a draft preset YAML with theme/style/motion/hook filled in).

Everything runs with ``PROVIDER_MODE=fake`` — no network, no spend. The local
fixture clip is "fetched" by ``fetch_video`` via a plain file copy.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings

from providers import base
from providers.base import ProviderConfigError
from providers.fakes import FakeVideoUnderstander

FIXTURE_VIDEO = Path(settings.FIXTURES_DIR) / "background_loop.mp4"
FIELDS = ("theme", "style", "motion", "hook")


# --- The Fake returns structured fields from a fixture ----------------------


def test_fake_video_understander_returns_fields(tmp_path: Path) -> None:
    result = FakeVideoUnderstander().describe(tmp_path / "clip.mp4")
    assert set(FIELDS) <= result.keys()
    assert all(isinstance(result[k], str) and result[k] for k in FIELDS)


def test_fake_video_understander_returns_a_shot_timeline(tmp_path: Path) -> None:
    # The whole point of the describe step is faithful reproduction, which needs
    # a second-by-second breakdown — not just four summary fields.
    shots = FakeVideoUnderstander().describe(tmp_path / "clip.mp4")["shots"]
    assert isinstance(shots, list) and len(shots) >= 2
    for shot in shots:
        assert {"time", "action", "camera"} <= shot.keys()
        assert all(isinstance(shot[k], str) and shot[k] for k in ("time", "action", "camera"))


# --- The factory selects the right backend ----------------------------------


@override_settings(PROVIDER_MODE="fake")
def test_get_video_understander_fake() -> None:
    assert isinstance(base.get_video_understander(), FakeVideoUnderstander)


@override_settings(PROVIDER_MODE="real", GEMINI_API_KEY="k")
def test_get_video_understander_real() -> None:
    from providers.gemini import RealGeminiVideoUnderstander

    assert isinstance(base.get_video_understander(), RealGeminiVideoUnderstander)


# --- The Real client raises loudly when its key is blank --------------------


@override_settings(PROVIDER_MODE="real", GEMINI_API_KEY="")
def test_real_gemini_requires_key() -> None:
    from providers.gemini import RealGeminiVideoUnderstander

    with pytest.raises(ProviderConfigError):
        RealGeminiVideoUnderstander()


# --- The command writes a draft preset --------------------------------------


def test_describe_trend_writes_dance_preset(tmp_path: Path) -> None:
    out = tmp_path / "trend.yaml"
    call_command("describe_trend", str(FIXTURE_VIDEO), "--out", str(out))

    assert out.is_file()
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["mode"] == "dance"

    fields = FakeVideoUnderstander().describe(FIXTURE_VIDEO)
    for key in FIELDS:
        assert data[key] == fields[key]

    # Character + song are left as TODO comments for the human to complete.
    text = out.read_text(encoding="utf-8")
    assert "character" in text.lower()
    assert "song" in text.lower()

    # The second-by-second timeline is written in (as a reference block) so the
    # draft carries enough detail to reproduce the clip, not just summary fields.
    assert "timeline" in text.lower()
    first_shot = fields["shots"][0]
    assert first_shot["time"] in text
    assert first_shot["action"] in text


def test_describe_trend_mimic_seeds_drive(tmp_path: Path) -> None:
    out = tmp_path / "trend_mimic.yaml"
    call_command("describe_trend", str(FIXTURE_VIDEO), "--mode", "mimic", "--out", str(out))

    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["mode"] == "mimic"
    assert data["drive"]["source"] == str(FIXTURE_VIDEO)
