"""Subject-segmentation matting via BiRefNet on fal.

Replaces chroma-keying: instead of removing a green background by colour (which
also eats green clothes, green creatures, and green-blended thin limbs), this
cuts out the *subject* and returns a clip with a real alpha channel. Compose
then overlays it cleanly over any background.

``fal_client`` is imported at the callsite (real-mode only). The model caps at
``settings.MATTING_MAX_FRAMES``; clips with more frames are re-encoded to a
lower fps to fit (timing is preserved — only frame density drops).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
from django.conf import settings

from providers.base import ProviderConfigError

_HTTP_TIMEOUT = httpx.Timeout(600.0)

# File extension per BiRefNet output type (the matte container the model returns).
_EXT_BY_OUTPUT = {
    "PRORES4444 (.mov)": ".mov",
    "VP9 (.webm)": ".webm",
    "X264 (.mp4)": ".mp4",
    "GIF (.gif)": ".gif",
}


class MattingError(RuntimeError):
    """The matting model could not process the clip."""


def _download(url: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, timeout=_HTTP_TIMEOUT, follow_redirects=True) as response:
        response.raise_for_status()
        with out_path.open("wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
    return out_path


def _frame_count_and_fps(video: Path) -> tuple[int, float]:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames,avg_frame_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    rate, frames = out[0], out[1]
    num, _, den = rate.partition("/")
    fps = float(num) / float(den) if den and float(den) else float(num or 0)
    return int(frames), fps


def _fit_frame_cap(video: Path, max_frames: int) -> Path:
    """Return a clip with <= ``max_frames`` frames, re-encoding fps down if needed."""
    frames, fps = _frame_count_and_fps(video)
    if frames <= max_frames or fps <= 0:
        return video
    duration = frames / fps
    target_fps = max(1, int(max_frames / duration))
    reduced = video.with_name(f"{video.stem}_fps{target_fps}.mp4")
    cmd = ["ffmpeg", "-y", "-i", str(video), "-r", str(target_fps), str(reduced)]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", "replace") if exc.stderr else ""
        raise MattingError(f"fps reduction failed for {video}: {stderr}") from exc
    return reduced


class RealFalMatter:
    """Video matting (subject cutout with alpha) via BiRefNet on fal."""

    def __init__(self) -> None:
        if not settings.FAL_KEY:
            raise ProviderConfigError("FAL_KEY is empty; required for RealFalMatter.")
        self._model = settings.MATTING_MODEL
        self._variant = settings.MATTING_MODEL_VARIANT
        self._output_type = settings.MATTING_OUTPUT_TYPE

    def matte(self, video_in: Path, out_path: Path) -> Path:
        import fal_client  # noqa: PLC0415  (heavy optional SDK, real-mode only)

        clip = _fit_frame_cap(Path(video_in), settings.MATTING_MAX_FRAMES)
        url = fal_client.upload_file(clip)
        result = fal_client.subscribe(
            self._model,
            arguments={
                "video_url": url,
                "model": self._variant,
                "video_output_type": self._output_type,
                "video_quality": "high",
            },
        )
        if not isinstance(result, dict):
            raise MattingError(f"matting result is not a dict: {result!r}")
        video = result.get("video")
        out_url = video.get("url") if isinstance(video, dict) else video
        if not isinstance(out_url, str) or not out_url:
            raise MattingError(f"matting result missing a video URL: {result!r}")
        # Write with the container's real extension (e.g. .mov for ProRes).
        dest = Path(out_path).with_suffix(_EXT_BY_OUTPUT.get(self._output_type, ".mov"))
        return _download(out_url, dest)
