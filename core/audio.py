"""Local audio preparation (CPU, free — runs on the Pi).

The only audio work done locally is loudness normalization, so every song
enters the pipeline at a consistent level regardless of how the source was
mastered. Heavy audio work (vocal separation) is a cloud provider call.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class AudioNormalizationError(RuntimeError):
    """ffmpeg failed to normalize the source audio."""


class TimeRangeError(ValueError):
    """A ``song.clip`` range could not be parsed (expected ``start-end``)."""


def _parse_timestamp(value: str) -> float:
    """Parse ``SS`` / ``M:SS`` / ``H:MM:SS`` into seconds."""
    try:
        parts = [float(p) for p in value.strip().split(":")]
    except ValueError as exc:
        raise TimeRangeError(f"Bad timestamp {value!r}.") from exc
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise TimeRangeError(f"Bad timestamp {value!r}.")


def parse_timerange(spec: str) -> tuple[float, float]:
    """Parse ``"0:45-1:05"`` into ``(start_seconds, end_seconds)``.

    Raises ``TimeRangeError`` on a malformed range or one where end <= start.
    """
    if spec.count("-") != 1:
        raise TimeRangeError(f"Clip range must be 'start-end', got {spec!r}.")
    start_raw, end_raw = spec.split("-")
    start, end = _parse_timestamp(start_raw), _parse_timestamp(end_raw)
    if end <= start:
        raise TimeRangeError(f"Clip end must be after start, got {spec!r}.")
    return start, end


def clip_audio(src: Path, out_path: Path, start_s: float, end_s: float) -> Path:
    """Cut ``[start_s, end_s)`` out of ``src`` into ``out_path``.

    Re-encodes (no stream copy) so the cut is sample-accurate — important for
    lip-sync, where a sloppy keyframe-aligned cut would drift the timing.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start_s),
        "-to",
        str(end_s),
        "-i",
        str(src),
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", "replace") if exc.stderr else ""
        raise AudioNormalizationError(f"clip failed for {src}: {stderr}") from exc
    return out_path


def normalize_loudness(src: Path, out_path: Path) -> Path:
    """Normalize ``src`` to EBU R128 (-16 LUFS) and write ``out_path``.

    Single-pass ``loudnorm`` — good enough for a guide track; we are not
    mastering. A non-zero ffmpeg exit raises (no silent fallthrough).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ar",
        "44100",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", "replace") if exc.stderr else ""
        raise AudioNormalizationError(f"loudnorm failed for {src}: {stderr}") from exc
    return out_path
