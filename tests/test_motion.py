"""Tests for the motion_first providers (Kling animator + video lip-sync)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from django.test import override_settings

import providers.lipsync as lipsync_mod
import providers.motion as motion_mod
from providers.base import ProviderConfigError, get_animator, get_video_lip_syncer
from providers.fakes import FakeAnimator, FakeVideoLipSyncer
from providers.lipsync import RealSyncVideoLipSyncer
from providers.motion import RealKlingAnimator


@override_settings(PROVIDER_MODE="fake")
def test_factories_return_fakes():
    assert isinstance(get_animator(), FakeAnimator)
    assert isinstance(get_video_lip_syncer(), FakeVideoLipSyncer)


@override_settings(FAL_KEY="")
def test_kling_requires_fal_key():
    with pytest.raises(ProviderConfigError):
        RealKlingAnimator()


@override_settings(FAL_KEY="")
def test_video_lipsync_requires_fal_key():
    with pytest.raises(ProviderConfigError):
        RealSyncVideoLipSyncer()


def test_fake_animator_returns_clip(tmp_path):
    out = FakeAnimator().animate(tmp_path / "img.png", tmp_path / "moving.mp4")
    assert out.is_file()


def test_fake_video_lipsync_passthrough(tmp_path):
    src = tmp_path / "v.mp4"
    src.write_bytes(b"moving-clip")
    out = FakeVideoLipSyncer().sync_video(src, tmp_path / "a.mp3", tmp_path / "o.mp4")
    assert out.read_bytes() == b"moving-clip"


@override_settings(FAL_KEY="k")
def test_kling_animate_downloads(tmp_path, monkeypatch):
    fake = types.ModuleType("fal_client")
    fake.upload_file = lambda p: "https://up/img"  # noqa: E731
    fake.subscribe = lambda model, arguments: {"video": {"url": "https://v/out.mp4"}}  # noqa: E731
    monkeypatch.setitem(sys.modules, "fal_client", fake)
    monkeypatch.setattr(motion_mod, "_download", lambda url, out: Path(out))
    out = RealKlingAnimator().animate(tmp_path / "img.png", tmp_path / "out.mp4")
    assert out == tmp_path / "out.mp4"


@override_settings(FAL_KEY="k")
def test_kling_animate_passes_tail_image_for_loop(tmp_path, monkeypatch):
    # A tail image (same as start) makes Kling end on the starting frame for a
    # seamless loop. It must reach the API as `tail_image_url`.
    captured = {}
    fake = types.ModuleType("fal_client")
    fake.upload_file = lambda p: f"https://up/{Path(p).name}"  # noqa: E731
    fake.subscribe = lambda model, arguments: captured.update(arguments) or {  # noqa: E731
        "video": {"url": "https://v/out.mp4"}
    }
    monkeypatch.setitem(sys.modules, "fal_client", fake)
    monkeypatch.setattr(motion_mod, "_download", lambda url, out: Path(out))
    RealKlingAnimator().animate(
        tmp_path / "start.png", tmp_path / "out.mp4", tail_image_path=tmp_path / "start.png"
    )
    assert captured["tail_image_url"] == "https://up/start.png"


def test_fake_animator_accepts_tail(tmp_path):
    out = FakeAnimator().animate(
        tmp_path / "img.png", tmp_path / "m.mp4", tail_image_path=tmp_path / "img.png"
    )
    assert out.is_file()


@override_settings(FAL_KEY="k")
def test_video_lipsync_downloads(tmp_path, monkeypatch):
    fake = types.ModuleType("fal_client")
    fake.upload_file = lambda p: "https://up/x"  # noqa: E731
    fake.subscribe = lambda model, arguments: {"video": {"url": "https://v/o.mp4"}}  # noqa: E731
    monkeypatch.setitem(sys.modules, "fal_client", fake)
    monkeypatch.setattr(lipsync_mod, "_download", lambda url, out, **kw: Path(out))
    out = RealSyncVideoLipSyncer().sync_video(
        tmp_path / "v.mp4", tmp_path / "a.mp3", tmp_path / "o.mp4"
    )
    assert out == tmp_path / "o.mp4"
