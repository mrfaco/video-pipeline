"""Beat detection for the kinetic-camera pass (CPU, free — runs on the Pi).

Compose punches a small zoom on every beat. To place those punches it needs
the beat *period* (seconds between beats) and an *offset* (when the first beat
lands), which it feeds to ffmpeg's ``mod(t-offset, period)`` zoom expression.

``librosa`` is imported at the callsite so the heavy SDK only loads when beat
detection actually runs. Anything that fails — a silent stem, an unreadable
file, librosa missing — falls back to a steady 120 BPM (0.5s period) rather
than killing the render; a slightly-off pulse beats no video.
"""

from __future__ import annotations

import statistics
from pathlib import Path

# 120 BPM — a neutral dance tempo — when detection has nothing to go on.
_FALLBACK_PERIOD = 0.5
_FALLBACK_OFFSET = 0.0


def detect_beat_period(audio: Path) -> tuple[float, float]:
    """Return ``(period_seconds, offset_seconds)`` for the beat grid in ``audio``.

    ``period`` is the median gap between detected beats; ``offset`` is the first
    beat's timestamp (so ``mod(t - offset, period)`` is zero on every beat).
    Falls back to 120 BPM on any failure.
    """
    try:
        import librosa  # noqa: PLC0415  (heavy optional SDK, only when detecting)

        y, sr = librosa.load(str(audio), mono=True)
        if y.size == 0:
            return _FALLBACK_PERIOD, _FALLBACK_OFFSET
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
        if beats is None or len(beats) < 2:
            # Too few beats to measure a gap — derive the period from tempo.
            bpm = float(tempo) if tempo else 0.0
            period = 60.0 / bpm if bpm > 0 else _FALLBACK_PERIOD
            offset = float(beats[0]) if beats is not None and len(beats) else _FALLBACK_OFFSET
            return period, offset
        gaps = [float(b) - float(a) for a, b in zip(beats[:-1], beats[1:], strict=False)]
        period = statistics.median(gaps)
        if not period > 0:
            return _FALLBACK_PERIOD, _FALLBACK_OFFSET
        # Fold the first beat into the first period so the offset stays small.
        offset = float(beats[0]) % period
        return period, offset
    except Exception:  # noqa: BLE001  allow: suppress-exception
        # Any detection failure degrades to a steady tempo, never a dead render.
        return _FALLBACK_PERIOD, _FALLBACK_OFFSET
