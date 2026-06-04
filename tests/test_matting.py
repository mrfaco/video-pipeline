"""Tests for the matting backend selection, the fake matte, and the real flow."""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest
from django.test import override_settings

import providers.matting as matting_mod
from providers.base import ProviderConfigError, get_matter
from providers.fakes import FakeMatter
from providers.matting import MattingError, RealFalMatter, _fit_frame_cap


@override_settings(PROVIDER_MODE="fake")
def test_get_matter_returns_fake():
    assert isinstance(get_matter(), FakeMatter)


@override_settings(FAL_KEY="")
def test_real_matter_requires_fal_key():
    with pytest.raises(ProviderConfigError):
        RealFalMatter()


def test_fake_matter_produces_alpha_clip(tmp_path):
    out = FakeMatter().matte(Path("fixtures/character_lipsync.mp4"), tmp_path / "m.webm")
    assert out.suffix == ".mov" and out.is_file()
    info = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt",
            "-of",
            "csv=p=0",
            str(out),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert "prores" in info and "a" in info.split(",")[-1]  # alpha pixel format


def test_fit_frame_cap_passthrough_short():
    p = Path("fixtures/character_lipsync.mp4")  # ~3s, well under the cap
    assert _fit_frame_cap(p, 512) == p


def _fake_fal(monkeypatch, result):
    fake = types.ModuleType("fal_client")
    fake.upload_file = lambda p: "https://up/clip"  # noqa: E731
    fake.subscribe = lambda model, arguments: result  # noqa: E731
    monkeypatch.setitem(sys.modules, "fal_client", fake)
    monkeypatch.setattr(matting_mod, "_download", lambda url, out: Path(out))
    monkeypatch.setattr(matting_mod, "_fit_frame_cap", lambda v, m: v)


@override_settings(FAL_KEY="k")
def test_real_matter_downloads_result(tmp_path, monkeypatch):
    _fake_fal(monkeypatch, {"video": {"url": "https://v/out.webm"}})
    out = RealFalMatter().matte(tmp_path / "in.mp4", tmp_path / "out.webm")
    assert out == tmp_path / "out.webm"


@override_settings(FAL_KEY="k")
def test_real_matter_raises_on_bad_result(tmp_path, monkeypatch):
    _fake_fal(monkeypatch, {"no_video": True})
    with pytest.raises(MattingError):
        RealFalMatter().matte(tmp_path / "in.mp4", tmp_path / "out.webm")
