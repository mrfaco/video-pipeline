"""Fixture-backed provider clients for ``PROVIDER_MODE=fake``.

Each Fake mirrors the method signature of its Protocol in
``providers.base`` but, instead of calling a cloud vendor, copies the matching
bundled fixture from ``settings.FIXTURES_DIR`` into the caller's ``out_path``.
This is what lets the whole pipeline run end-to-end with no network and no
spend (AGENTS.md §2). Providers never touch the DB or ``ctx`` — paths in, a
written file out, the path returned (AGENTS.md §5).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from django.conf import settings


class FakeMattingError(RuntimeError):
    """ffmpeg failed while faking the matte."""


def _copy_fixture(fixture_name: str, out_path: Path) -> Path:
    """Copy a committed fixture into ``out_path`` and return ``out_path``."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    source = Path(settings.FIXTURES_DIR) / fixture_name
    shutil.copyfile(source, out_path)
    return out_path


class FakeVocalSeparator:
    """Returns the bundled vocal stem instead of running Demucs."""

    def separate(self, song_path: Path, out_path: Path) -> Path:
        return _copy_fixture("vocal_stem.wav", out_path)


class FakeCaptionAligner:
    """Returns bundled word-level timestamps instead of running WhisperX."""

    def align(self, audio_path: Path, lyrics: str | None, out_path: Path) -> Path:
        return _copy_fixture("word_timestamps.json", out_path)


class FakeBackgroundGenerator:
    """Returns the bundled FLUX still + motion loop instead of calling fal."""

    def generate_still(self, theme: str, out_path: Path) -> Path:
        return _copy_fixture("background_still.png", out_path)

    def animate(self, still_path: Path, out_path: Path) -> Path:
        return _copy_fixture("background_loop.mp4", out_path)


class FakePortraitGenerator:
    """Returns the bundled greenscreen portrait instead of calling fal."""

    def generate(self, character_ref: str, out_path: Path) -> Path:
        return _copy_fixture("character_portrait.png", out_path)


class FakeLipSyncer:
    """Returns the bundled talking-head clip instead of calling a vendor."""

    def sync(self, portrait_path: Path, audio_path: Path, out_path: Path) -> Path:
        return _copy_fixture("character_lipsync.mp4", out_path)


class FakeAnimator:
    """Returns the bundled greenscreen clip as the 'animated' (moving) video."""

    def animate(self, image_path: Path, out_path: Path) -> Path:
        return _copy_fixture("character_lipsync.mp4", out_path)


class FakeVideoLipSyncer:
    """Passthrough: returns the moving clip unchanged (no real lip-sync)."""

    def sync_video(self, video_path: Path, audio_path: Path, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(video_path, out_path)
        return out_path


class FakeMatter:
    """Locally chroma-keys the (pure-green) fixture into an alpha clip.

    Stands in for cloud subject-matting: the fake-mode lip-sync fixture is on a
    pure 0x00FF00 screen, so a local chroma-key produces a clean cutout. Output
    is ProRes 4444 .mov (which reliably carries an alpha channel — libvpx-vp9
    drops it locally), written next to ``out_path``; the actual path is returned.
    """

    def matte(self, video_in: Path, out_path: Path) -> Path:
        mov = Path(out_path).with_suffix(".mov")
        mov.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_in),
            "-an",
            "-vf",
            "chromakey=0x00FF00:0.30:0.10",
            "-c:v",
            "prores_ks",
            "-pix_fmt",
            "yuva444p10le",
            str(mov),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", "replace") if exc.stderr else ""
            raise FakeMattingError(f"fake matte failed: {stderr}") from exc
        return mov
