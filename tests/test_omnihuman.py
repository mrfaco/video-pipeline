"""Tests for the OmniHuman lip-sync backend selection + config guard."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.test import override_settings

from providers.base import ProviderConfigError, get_lip_syncer
from providers.lipsync import RealOmniHumanLipSyncer


@override_settings(PROVIDER_MODE="real", LIPSYNC_PROVIDER="omnihuman", FAL_KEY="k")
def test_factory_returns_omnihuman():
    assert isinstance(get_lip_syncer(), RealOmniHumanLipSyncer)


@override_settings(FAL_KEY="")
def test_omnihuman_requires_fal_key():
    with pytest.raises(ProviderConfigError):
        RealOmniHumanLipSyncer()


def _fake_fal(monkeypatch, subscribe_result):
    import sys
    import types

    import providers.lipsync as lipsync_mod

    fake = types.ModuleType("fal_client")
    fake.upload_file = lambda p: f"https://up/{Path(p).name}"  # noqa: E731
    fake.subscribe = lambda model, arguments: subscribe_result  # noqa: E731
    monkeypatch.setitem(sys.modules, "fal_client", fake)
    monkeypatch.setattr(lipsync_mod, "_download", lambda url, out: Path(out))


@override_settings(FAL_KEY="k")
def test_omnihuman_sync_downloads_video_url(tmp_path, monkeypatch):
    _fake_fal(monkeypatch, {"video": {"url": "https://v/out.mp4"}})
    out = RealOmniHumanLipSyncer().sync(tmp_path / "p.png", tmp_path / "a.mp3", tmp_path / "o.mp4")
    assert out == Path(tmp_path / "o.mp4")


@override_settings(FAL_KEY="k")
def test_omnihuman_sync_raises_on_bad_result(tmp_path, monkeypatch):
    _fake_fal(monkeypatch, {"no_video": True})
    with pytest.raises(ProviderConfigError):
        RealOmniHumanLipSyncer().sync(tmp_path / "p.png", tmp_path / "a.mp3", tmp_path / "o.mp4")
