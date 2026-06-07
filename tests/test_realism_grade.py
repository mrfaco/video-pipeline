"""The de-glow realism grade is a compose step, applied to the final video.

It knocks back highlights/saturation and adds fine grain to fight the glossy
"AI" sheen FLUX (and the avatar models) bake in — the look the user keeps
flagging. These check the ffmpeg pass produces a valid, audio-preserving clip
and that it's wired on by default.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from django.conf import settings

from compose.ffmpeg import apply_realism_grade


def _codec_types(path: Path) -> set[str]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return set(out.stdout.split())


def test_apply_realism_grade_preserves_audio(tmp_path: Path) -> None:
    # The bundled clips are silent, so build one with audio (a muxed song) to
    # prove the grade copies the audio through (a synced song must survive).
    src = tmp_path / "with_audio.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-i", str(Path(settings.FIXTURES_DIR) / "character_lipsync.mp4"),
         "-i", str(Path(settings.FIXTURES_DIR) / "song.mp3"),
         "-map", "0:v", "-map", "1:a", "-shortest",
         "-c:v", "copy", "-c:a", "aac", str(src)],
        check=True,
    )
    out = tmp_path / "graded.mp4"
    result = apply_realism_grade(src, out, settings.REALISM_GRADE_FILTER)
    assert result == out
    assert out.is_file() and out.stat().st_size > 0
    assert _codec_types(out) >= {"video", "audio"}


def test_apply_realism_grade_on_silent_clip(tmp_path: Path) -> None:
    # A mute clip (vibe/mimic) grades fine and stays a valid video.
    src = Path(settings.FIXTURES_DIR) / "background_loop.mp4"
    out = tmp_path / "graded_silent.mp4"
    apply_realism_grade(src, out, settings.REALISM_GRADE_FILTER)
    assert "video" in _codec_types(out)


def test_realism_grade_enabled_by_default() -> None:
    assert settings.REALISM_GRADE_ENABLED is True
    assert settings.REALISM_GRADE_FILTER  # a non-empty ffmpeg filter string
