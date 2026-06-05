"""High-motion image->video via Kling on fal (the motion_first workflow).

Kling animates the static portrait with aggressive full-body motion (head-bob,
jumping, dancing) — but does NOT lip-sync. A video lip-sync step
(``providers.lipsync.RealSyncVideoLipSyncer``) then maps the mouth onto the
moving clip. ``fal_client`` is imported at the callsite (real-mode only).
"""

from __future__ import annotations

from pathlib import Path

import httpx
from django.conf import settings

from providers.base import ProviderConfigError

_HTTP_TIMEOUT = httpx.Timeout(600.0)


def _download(url: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, timeout=_HTTP_TIMEOUT, follow_redirects=True) as response:
        response.raise_for_status()
        with out_path.open("wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
    return out_path


class RealKlingAnimator:
    """Aggressive image->video motion via Kling on fal."""

    def __init__(self) -> None:
        if not settings.FAL_KEY:
            raise ProviderConfigError("FAL_KEY is empty; required for RealKlingAnimator.")
        self._model = settings.KLING_MODEL
        self._prompt = settings.KLING_MOTION_PROMPT
        self._duration = settings.KLING_DURATION
        self._cfg = settings.KLING_CFG

    def animate(
        self,
        image_path: Path,
        out_path: Path,
        tail_image_path: Path | None = None,
        prompt: str | None = None,
        cfg_scale: float | None = None,
    ) -> Path:
        import fal_client  # noqa: PLC0415  (heavy optional SDK, real-mode only)

        url = fal_client.upload_file(Path(image_path))
        arguments: dict[str, object] = {
            "prompt": prompt if prompt is not None else self._prompt,
            "image_url": url,
            "duration": self._duration,
            "cfg_scale": cfg_scale if cfg_scale is not None else self._cfg,
        }
        if tail_image_path is not None:
            # End the clip on this frame; start == tail gives a seamless loop.
            arguments["tail_image_url"] = fal_client.upload_file(Path(tail_image_path))
        result = fal_client.subscribe(self._model, arguments=arguments)
        if not isinstance(result, dict):
            raise ProviderConfigError(f"Kling result is not a dict: {result!r}")
        video = result.get("video")
        out_url = video.get("url") if isinstance(video, dict) else video
        if not isinstance(out_url, str) or not out_url:
            raise ProviderConfigError(f"Kling result missing a video URL: {result!r}")
        return _download(out_url, out_path)
