"""Tests for windowing full-song word timestamps down to a clip + the
scroll-stop zoom-punch in compose."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from compose.captions import window_words
from compose.ffmpeg import compose_final


def _has_video(path: Path) -> bool:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return "video" in out.stdout


def test_intro_zoom_punch_renders(tmp_path):
    # With the punch enabled, compose still produces a valid 9:16 mp4 and the
    # duration is unchanged (visual-only effect).
    out = compose_final(
        background_loop=Path("fixtures/background_loop.mp4"),
        character_clip=Path("fixtures/character_lipsync.mp4"),
        audio=Path("fixtures/song.mp3"),
        captions=None,
        out_path=tmp_path / "punch.mp4",
        intro_zoom=1.4,
        intro_seconds=0.4,
    )
    assert out.is_file() and _has_video(out)
    dur = float(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(out),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    assert 2.3 <= dur <= 3.7  # same as the audio; punch doesn't change timing


def _write(path: Path, words: list[dict]) -> Path:
    path.write_text(json.dumps({"language": "es", "word_segments": words}), encoding="utf-8")
    return path


def test_window_keeps_and_rebases(tmp_path):
    src = _write(
        tmp_path / "full.json",
        [
            {"word": "antes", "start": 10.0, "end": 10.4},
            {"word": "Tú", "start": 64.9, "end": 65.2},
            {"word": "brujería", "start": 65.2, "end": 66.0},
            {"word": "después", "start": 90.0, "end": 90.5},
        ],
    )
    out = window_words(src, tmp_path / "clip.json", 64.0, 80.0)
    data = json.loads(out.read_text())
    assert [w["word"] for w in data["word_segments"]] == ["Tú", "brujería"]
    # rebased into clip time (subtract start=64.0)
    assert abs(data["word_segments"][0]["start"] - 0.9) < 1e-6


def test_window_clamps_overlap(tmp_path):
    src = _write(
        tmp_path / "full.json",
        [{"word": "edge", "start": 63.5, "end": 64.5}],  # straddles the window start
    )
    out = window_words(src, tmp_path / "clip.json", 64.0, 80.0)
    w = json.loads(out.read_text())["word_segments"][0]
    assert w["start"] == 0.0  # clamped to clip start
    assert abs(w["end"] - 0.5) < 1e-6


def test_window_excludes_outside(tmp_path):
    src = _write(tmp_path / "full.json", [{"word": "x", "start": 5.0, "end": 5.5}])
    out = window_words(src, tmp_path / "clip.json", 64.0, 80.0)
    assert json.loads(out.read_text())["word_segments"] == []
