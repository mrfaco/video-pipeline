"""Transition mode: a two-look before→after glow-up, saved as a preset and
rendered by ``manage.py render_transition``.

A normal preset renders one scene; a transition stitches two (different outfit +
setting) with a hard cut. These cover the compose stitch (``concat_cuts``), the
``load_transition_preset`` parser, and the end-to-end command in fake mode.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from django.conf import settings
from django.core.management import call_command

from compose.ffmpeg import concat_cuts
from jobs.presets import PresetError, load_transition_preset


def _codec_types(path: Path) -> set[str]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return set(out.stdout.split())


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


# --- compose: hard-cut stitch -----------------------------------------------


def test_concat_cuts_stitches_segments(tmp_path: Path) -> None:
    a = Path(settings.FIXTURES_DIR) / "character_lipsync.mp4"  # 3s
    b = Path(settings.FIXTURES_DIR) / "background_loop.mp4"    # 2s
    out = tmp_path / "stitched.mp4"
    result = concat_cuts([(a, 0.0, 1.0), (b, 0.0, 1.0)], out)
    assert result == out
    assert "video" in _codec_types(out)
    # ~2s total (two 1s cuts); allow ffmpeg rounding.
    assert 1.6 < _duration(out) < 2.4


# --- preset parsing ---------------------------------------------------------


def _write_transition_preset(path: Path) -> None:
    path.write_text(yaml.safe_dump({
        "mode": "transition",
        "character": {"description": "a young woman"},
        "before": {"theme": "a kitchen", "style": "a robe", "motion": "yawns", "duration": 1.0},
        "after": {"theme": "a club", "style": "a dress", "motion": "poses",
                  "start": 0.0, "duration": 1.0, "framing": "from the hips up"},
    }), encoding="utf-8")


def test_load_transition_preset(tmp_path: Path) -> None:
    p = tmp_path / "t.yaml"
    _write_transition_preset(p)
    data = load_transition_preset(p)
    assert data["character_ref"] == "a young woman"
    assert data["before"]["theme"] == "a kitchen"
    assert data["after"]["style"] == "a dress"
    assert data["after"]["duration"] == 1.0


def test_load_transition_preset_requires_both_looks(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump({
        "mode": "transition", "character": {"description": "x"},
        "before": {"theme": "a", "style": "b", "motion": "c"},
    }), encoding="utf-8")
    with pytest.raises(PresetError):
        load_transition_preset(p)


# --- the command (fake providers, real ffmpeg) ------------------------------


def test_render_transition_produces_video(tmp_path: Path) -> None:
    preset = tmp_path / "glow.yaml"
    _write_transition_preset(preset)
    out = tmp_path / "final.mp4"
    call_command("render_transition", str(preset), "--out", str(out))
    assert out.is_file()
    assert "video" in _codec_types(out)
