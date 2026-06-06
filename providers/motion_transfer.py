"""Motion transfer for mimic mode: a character image + a driving dance video in,
a clip of the character performing that dance out.

Two backends (selected by ``settings.MOTION_TRANSFER_PROVIDER`` via the
``get_motion_transfer`` factory):

* ``RealWanAnimate`` — Alibaba Wan-2.2 Animate on fal (the default). Purpose-built
  for full-body character dance; coherent legs + backgrounds where MimicMotion
  melts. Uses ``fal_client.subscribe`` (the SDK handles the queue/polling), same
  as the Kling animator.
* ``RealMimicMotion`` — zsxkib/mimic-motion on Replicate (the original). Soft and
  warps on fast full-body motion; kept as a fallback. Renders for many minutes,
  so we create the prediction and poll it explicitly rather than using the
  blocking ``client.run()`` (which hits an httpx ReadTimeout on cold start).

Heavy SDKs (``replicate``, ``fal_client``) are imported at the callsite
(real-mode only); a missing key raises at construction; a failed/empty result
raises (no silent fallback).
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
from django.conf import settings

from providers.base import ProviderConfigError

_HTTP_TIMEOUT = httpx.Timeout(600.0)
# MimicMotion renders are slow — minutes at 576px, much longer at 1024px (the
# diffusion cost scales with pixels × frames). The ceiling must comfortably
# outlast the worst case: a timeout here raises, and the stage's autoretry would
# then start a BRAND-NEW prediction (duplicate GPU spend). 10s × 1080 = 3 hours.
_POLL_INTERVAL_S = 10.0
_POLL_MAX_TRIES = 1080


def _download(url: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, timeout=_HTTP_TIMEOUT, follow_redirects=True) as response:
        response.raise_for_status()
        with out_path.open("wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
    return out_path


class RealWanAnimate:
    """Motion transfer via Alibaba Wan-2.2 Animate (animation/"move" mode) on fal."""

    def __init__(self) -> None:
        if not settings.FAL_KEY:
            raise ProviderConfigError("FAL_KEY is empty; required for RealWanAnimate.")
        self._model = settings.WAN_ANIMATE_MODEL
        self._resolution = settings.WAN_ANIMATE_RESOLUTION
        self._quality = settings.WAN_ANIMATE_QUALITY
        self._steps = settings.WAN_ANIMATE_STEPS

    def transfer(self, appearance_image: Path, motion_video: Path, out_path: Path) -> Path:
        import fal_client  # noqa: PLC0415  (heavy optional SDK, real-mode only)

        image_url = fal_client.upload_file(Path(appearance_image))
        video_url = fal_client.upload_file(Path(motion_video))
        result = fal_client.subscribe(
            self._model,
            arguments={
                "image_url": image_url,
                "video_url": video_url,
                "resolution": self._resolution,
                "video_quality": self._quality,
                "num_inference_steps": self._steps,
            },
        )
        if not isinstance(result, dict):
            raise ProviderConfigError(f"Wan-Animate result is not a dict: {result!r}")
        video = result.get("video")
        url = video.get("url") if isinstance(video, dict) else video
        if not isinstance(url, str) or not url:
            raise ProviderConfigError(f"Wan-Animate result missing a video URL: {result!r}")
        return _download(url, out_path)


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
