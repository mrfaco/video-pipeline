"""Tests for beat detection (the kinetic-camera beat grid)."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings

from core.beat import _FALLBACK_OFFSET, _FALLBACK_PERIOD, detect_beat_period

FIXTURES_DIR = Path(settings.FIXTURES_DIR)


def test_detect_beat_period_on_song():
    period, offset = detect_beat_period(FIXTURES_DIR / "song.mp3")
    # A real period is a small positive gap; offset folds into one period.
    assert period > 0
    assert 0 <= offset < period + 1e-6


def test_detect_beat_period_falls_back_on_bad_file(tmp_path):
    # An unreadable/non-audio file must degrade to the steady fallback, not raise.
    bad = tmp_path / "not_audio.mp3"
    bad.write_bytes(b"not really audio")
    period, offset = detect_beat_period(bad)
    assert period == _FALLBACK_PERIOD
    assert offset == _FALLBACK_OFFSET


def test_detect_beat_period_missing_file_falls_back(tmp_path):
    period, offset = detect_beat_period(tmp_path / "nope.mp3")
    assert period == _FALLBACK_PERIOD
    assert offset == _FALLBACK_OFFSET
