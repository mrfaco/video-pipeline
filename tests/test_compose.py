"""Tests for the compose package — captions and the real-ffmpeg final render."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from django.conf import settings

from compose.captions import build_ass
from compose.ffmpeg import compose_final

FIXTURES_DIR = Path(settings.FIXTURES_DIR)


def _ffprobe(video_path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_build_ass_emits_events_and_words(tmp_path):
    out = build_ass(FIXTURES_DIR / "word_timestamps.json", tmp_path / "captions.ass")

    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "[Events]" in content
    dialogue_lines = [line for line in content.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogue_lines) >= 1
    assert any("neon" in line for line in dialogue_lines)


def test_compose_final_with_captions(tmp_path):
    captions = build_ass(FIXTURES_DIR / "word_timestamps.json", tmp_path / "captions.ass")
    out = compose_final(
        background_loop=FIXTURES_DIR / "background_loop.mp4",
        character_clip=FIXTURES_DIR / "character_lipsync.mp4",
        audio=FIXTURES_DIR / "song.mp3",
        captions=captions,
        out_path=tmp_path / "final.mp4",
    )

    assert out.exists()
    probe = _ffprobe(out)
    video_streams = [s for s in probe["streams"] if s["codec_type"] == "video"]
    assert video_streams, "expected a video stream"
    duration = float(probe["format"]["duration"])
    assert duration == pytest.approx(3.0, abs=0.7)


def test_compose_final_without_captions(tmp_path):
    out = compose_final(
        background_loop=FIXTURES_DIR / "background_loop.mp4",
        character_clip=FIXTURES_DIR / "character_lipsync.mp4",
        audio=FIXTURES_DIR / "song.mp3",
        captions=None,
        out_path=tmp_path / "final_nocap.mp4",
    )

    assert out.exists()
    probe = _ffprobe(out)
    video_streams = [s for s in probe["streams"] if s["codec_type"] == "video"]
    assert video_streams, "expected a video stream"


def test_compose_final_missing_background_raises(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        compose_final(
            background_loop=tmp_path / "does_not_exist.mp4",
            character_clip=FIXTURES_DIR / "character_lipsync.mp4",
            audio=FIXTURES_DIR / "song.mp3",
            captions=None,
            out_path=tmp_path / "final_fail.mp4",
        )
