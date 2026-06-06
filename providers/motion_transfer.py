"""Motion transfer via MimicMotion on Replicate (mimic mode).

The character's appearance still + a driving dance video go in; a clip of the
character performing that dance comes out. MimicMotion renders for minutes, so
we create the prediction and poll it explicitly rather than using the blocking
``client.run()`` (which hits an httpx ReadTimeout on cold start). The
``replicate`` SDK is imported inside the method (real-mode only); a missing
token raises at construction; a failed/empty prediction raises (no fallback).
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
from django.conf import settings

from providers.base import ProviderConfigError

_HTTP_TIMEOUT = httpx.Timeout(600.0)
_POLL_INTERVAL_S = 5.0
_POLL_MAX_TRIES = 360  # 360 * 5s = 30 min ceiling


def _download(url: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, timeout=_HTTP_TIMEOUT, follow_redirects=True) as response:
        response.raise_for_status()
        with out_path.open("wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
    return out_path


class RealMimicMotion:
    """Motion transfer via the ``zsxkib/mimic-motion`` model on Replicate."""

    def __init__(self) -> None:
        if not settings.REPLICATE_API_TOKEN:
            raise ProviderConfigError(
                "REPLICATE_API_TOKEN is empty; required for RealMimicMotion."
            )
        # Model is "owner/name:version"; predictions.create wants the bare hash.
        self._version = settings.MIMICMOTION_MODEL.split(":", 1)[-1]
        self._resolution = settings.MIMICMOTION_RESOLUTION
        self._fps = settings.MIMICMOTION_FPS

    def transfer(self, appearance_image: Path, motion_video: Path, out_path: Path) -> Path:
        import replicate  # noqa: PLC0415  (heavy optional SDK, real-mode only)

        client = replicate.Client(api_token=settings.REPLICATE_API_TOKEN)
        with Path(appearance_image).open("rb") as img, Path(motion_video).open("rb") as vid:
            prediction = client.predictions.create(
                version=self._version,
                input={
                    "appearance_image": img,
                    "motion_video": vid,
                    "resolution": self._resolution,
                    "output_frames_per_second": self._fps,
                },
            )

        for _ in range(_POLL_MAX_TRIES):
            if prediction.status in ("succeeded", "failed", "canceled"):
                break
            time.sleep(_POLL_INTERVAL_S)
            prediction.reload()
        if prediction.status != "succeeded":
            raise ProviderConfigError(
                f"MimicMotion prediction did not succeed: status={prediction.status!r} "
                f"error={getattr(prediction, 'error', None)!r}"
            )

        output = prediction.output
        if isinstance(output, (list, tuple)):
            output = output[0] if output else None
        url = getattr(output, "url", output)
        if not isinstance(url, str) or not url:
            raise ProviderConfigError(f"MimicMotion output is not a URL: {prediction.output!r}")
        return _download(url, out_path)
