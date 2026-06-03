"""Tests for the local audio helpers — timerange parsing + ffmpeg trim."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.audio import TimeRangeError, clip_audio, parse_timerange


def test_parse_timerange_mmss():
    assert parse_timerange("0:48-1:06") == (48.0, 66.0)


def test_parse_timerange_plain_seconds():
    assert parse_timerange("5-20") == (5.0, 20.0)


def test_parse_timerange_hms():
    assert parse_timerange("1:00:00-1:00:30") == (3600.0, 3630.0)


@pytest.mark.parametrize("bad", ["1:05", "20-5", "5-5", "a-b", "1-2-3"])
def test_parse_timerange_rejects_bad(bad):
    with pytest.raises(TimeRangeError):
        parse_timerange(bad)


def test_clip_audio_trims_real_fixture(tmp_path):
    out = tmp_path / "clip.mp3"
    clip_audio(Path("fixtures/song.mp3"), out, 0.0, 1.0)
    assert out.is_file()
    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert 0.7 <= float(dur) <= 1.3
