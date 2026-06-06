"""Tests for the yt-dlp audio fetcher — mocked, never hits the network."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core import fetch
from core.fetch import AudioFetchError, VideoFetchError, fetch_audio, fetch_video


def _fake_run_factory(captured: dict, *, create: bool = True, returncode: int = 0):
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        if returncode != 0:
            raise subprocess.CalledProcessError(returncode, cmd, stderr=b"boom")
        if create:
            # yt-dlp writes <stem>.mp3 — mimic that.
            out_template = cmd[cmd.index("--output") + 1]
            Path(out_template.replace(".%(ext)s", ".mp3")).write_bytes(b"ID3fakeaudio")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    return fake_run


def test_fetch_search_query_uses_ytsearch(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(captured))
    out = fetch_audio("Blinding Lights The Weeknd", tmp_path / "source.mp3")
    assert out.exists()
    assert "ytsearch1:Blinding Lights The Weeknd" in captured["cmd"]
    assert "mp3" in captured["cmd"]


def test_fetch_url_passed_through(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(captured))
    url = "https://example.com/track"
    fetch_audio(url, tmp_path / "source.mp3")
    assert url in captured["cmd"]
    assert not any(c.startswith("ytsearch") for c in captured["cmd"] if isinstance(c, str))


def test_fetch_empty_source_raises(tmp_path):
    with pytest.raises(AudioFetchError):
        fetch_audio("", tmp_path / "source.mp3")


def test_fetch_yt_dlp_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run_factory({}, returncode=1))
    with pytest.raises(AudioFetchError, match="yt-dlp failed"):
        fetch_audio("anything", tmp_path / "source.mp3")


def test_fetch_missing_output_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run_factory({}, create=False))
    with pytest.raises(AudioFetchError, match="missing"):
        fetch_audio("anything", tmp_path / "source.mp3")


def test_is_url():
    assert fetch._is_url("http://x") and fetch._is_url("https://x")
    assert not fetch._is_url("Blinding Lights")


def _fake_video_run_factory(captured: dict, *, create: bool = True, returncode: int = 0):
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        if returncode != 0:
            raise subprocess.CalledProcessError(returncode, cmd, stderr=b"boom")
        if create:
            out_template = cmd[cmd.index("--output") + 1]
            Path(out_template.replace(".%(ext)s", ".mp4")).write_bytes(b"\x00fakevideo")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    return fake_run


def test_fetch_video_url_downloads(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_video_run_factory(captured))
    out = fetch_video("https://example.com/clip", tmp_path / "drive.mp4")
    assert out.exists()
    assert "https://example.com/clip" in captured["cmd"]


def test_fetch_video_local_path_passthrough(tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"\x00localvideo")
    out = fetch_video(str(src), tmp_path / "drive.mp4")
    assert out.read_bytes() == b"\x00localvideo"


def test_fetch_video_empty_source_raises(tmp_path):
    with pytest.raises(VideoFetchError):
        fetch_video("", tmp_path / "drive.mp4")


def test_fetch_video_missing_local_raises(tmp_path):
    with pytest.raises(VideoFetchError, match="not found"):
        fetch_video("/no/such/file.mp4", tmp_path / "drive.mp4")


def test_fetch_video_yt_dlp_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_video_run_factory({}, returncode=1))
    with pytest.raises(VideoFetchError, match="yt-dlp failed"):
        fetch_video("https://example.com/clip", tmp_path / "drive.mp4")
