"""Lip-sync vendor clients: Hedra, Sync, Magic Hour.

One vendor is selected by ``settings.LIPSYNC_PROVIDER`` (see
``providers.base.get_lip_syncer``). Each client speaks plain ``httpx`` to its
vendor's REST API — no SDK — submitting the portrait + audio, polling for the
finished render, and downloading the mp4 to ``out_path``.

Request shapes are best-effort (these can't be exercised live). The auth
header and a plausible job-submit/poll/download flow are encoded per vendor.
No fallbacks: a missing key raises at construction; a non-2xx, a failed job
status, or a missing result URL raises (AGENTS.md §1).
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
from django.conf import settings

from providers.base import ProviderConfigError

_HTTP_TIMEOUT = httpx.Timeout(120.0)
# How long to wait for an async render before giving up loudly.
_POLL_INTERVAL_S = 5.0
_POLL_TIMEOUT_S = 600.0


def _download(url: str, out_path: Path, *, headers: dict[str, str] | None = None) -> Path:
    """Stream a finished render to disk, raising on any non-2xx response."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream(
        "GET", url, timeout=_HTTP_TIMEOUT, headers=headers, follow_redirects=True
    ) as response:
        response.raise_for_status()
        with out_path.open("wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
    return out_path


def _deadline() -> float:
    return time.monotonic() + _POLL_TIMEOUT_S


class RealHedraLipSyncer:
    """Talking-head render via the Hedra Character API (``x-api-key`` auth)."""

    _BASE = "https://api.hedra.com/web-app/public"

    def __init__(self) -> None:
        if not settings.HEDRA_API_KEY:
            raise ProviderConfigError("HEDRA_API_KEY is empty; required for RealHedraLipSyncer.")
        self._headers = {"x-api-key": settings.HEDRA_API_KEY}
        self._model_id = settings.HEDRA_MODEL_ID
        self._resolution = settings.HEDRA_RESOLUTION
        self._aspect_ratio = settings.HEDRA_ASPECT_RATIO

    def _upload_asset(self, client: httpx.Client, path: Path, asset_type: str) -> str:
        """Create an asset record then upload its bytes; return the asset id.

        Hedra's flow is two calls: POST /assets to mint the record, then POST
        /assets/{id}/upload with the multipart file.
        """
        meta = client.post(
            f"{self._BASE}/assets",
            json={"name": path.name, "type": asset_type},
        )
        meta.raise_for_status()
        asset_id = meta.json()["id"]
        with path.open("rb") as fh:
            upload = client.post(
                f"{self._BASE}/assets/{asset_id}/upload",
                files={"file": (path.name, fh)},
            )
        upload.raise_for_status()
        return asset_id

    def sync(self, portrait_path: Path, audio_path: Path, out_path: Path) -> Path:
        with httpx.Client(headers=self._headers, timeout=_HTTP_TIMEOUT) as client:
            image_id = self._upload_asset(client, Path(portrait_path), "image")
            audio_id = self._upload_asset(client, Path(audio_path), "audio")

            # Character-3 is audio-driven: duration follows the audio (no
            # duration_ms). text_prompt guides expression/scene.
            submit = client.post(
                f"{self._BASE}/generations",
                json={
                    "type": "video",
                    "ai_model_id": self._model_id,
                    "start_keyframe_id": image_id,
                    "audio_id": audio_id,
                    "generated_video_inputs": {
                        "text_prompt": "talking head, natural singing expression",
                        "resolution": self._resolution,
                        "aspect_ratio": self._aspect_ratio,
                    },
                },
            )
            submit.raise_for_status()
            generation_id = submit.json()["id"]

            deadline = _deadline()
            while True:
                status = client.get(f"{self._BASE}/generations/{generation_id}/status")
                status.raise_for_status()
                body = status.json()
                state = body.get("status")
                if state == "complete":
                    url = body["url"]
                    break
                if state in {"error", "failed"}:
                    raise ProviderConfigError(f"Hedra render failed: {body!r}")
                if time.monotonic() > deadline:
                    raise ProviderConfigError("Hedra render timed out.")
                time.sleep(_POLL_INTERVAL_S)

        return _download(url, out_path)


class RealSyncVideoLipSyncer:
    """Video lip-sync (mouth onto an already-moving clip) via Sync on fal.

    Used by the motion_first workflow after Kling has animated the body. Takes
    a video + audio (both uploaded to fal) and returns the lip-synced video.
    Uses ``FAL_KEY`` since the model is fal-hosted.
    """

    def __init__(self) -> None:
        if not settings.FAL_KEY:
            raise ProviderConfigError("FAL_KEY is empty; required for RealSyncVideoLipSyncer.")
        self._model = settings.VIDEO_LIPSYNC_MODEL

    def sync_video(self, video_path: Path, audio_path: Path, out_path: Path) -> Path:
        import fal_client  # noqa: PLC0415  (heavy optional SDK, real-mode only)

        video_url = fal_client.upload_file(Path(video_path))
        audio_url = fal_client.upload_file(Path(audio_path))
        result = fal_client.subscribe(
            self._model,
            arguments={"video_url": video_url, "audio_url": audio_url},
        )
        if not isinstance(result, dict):
            raise ProviderConfigError(f"video lip-sync result is not a dict: {result!r}")
        video = result.get("video")
        out_url = video.get("url") if isinstance(video, dict) else video
        if not isinstance(out_url, str) or not out_url:
            raise ProviderConfigError(f"video lip-sync result missing a URL: {result!r}")
        return _download(out_url, out_path)


class RealOmniHumanLipSyncer:
    """Full-body singing+dancing avatar via Bytedance OmniHuman 1.5 on fal.

    Unlike Hedra's talking-head models, OmniHuman animates the whole body to the
    audio (beat + vocals), so it's fed the full-mix clip, not the isolated
    vocal stem. Uses ``fal_client`` (deferred import, real-mode only).
    """

    def __init__(self) -> None:
        if not settings.FAL_KEY:
            raise ProviderConfigError("FAL_KEY is empty; required for RealOmniHumanLipSyncer.")
        self._model = settings.OMNIHUMAN_MODEL
        self._resolution = settings.OMNIHUMAN_RESOLUTION
        self._prompt = settings.OMNIHUMAN_PROMPT

    def sync(self, portrait_path: Path, audio_path: Path, out_path: Path) -> Path:
        import fal_client  # noqa: PLC0415  (heavy optional SDK, real-mode only)

        image_url = fal_client.upload_file(Path(portrait_path))
        audio_url = fal_client.upload_file(Path(audio_path))
        result = fal_client.subscribe(
            self._model,
            arguments={
                "image_url": image_url,
                "audio_url": audio_url,
                "prompt": self._prompt,
                "resolution": self._resolution,
            },
        )
        if not isinstance(result, dict):
            raise ProviderConfigError(f"OmniHuman result is not a dict: {result!r}")
        video = result.get("video")
        url = video.get("url") if isinstance(video, dict) else video
        if not isinstance(url, str) or not url:
            raise ProviderConfigError(f"OmniHuman result missing a video URL: {result!r}")
        return _download(url, out_path)


class RealSyncLipSyncer:
    """Talking-head render via Sync (sync.so / ``x-api-key`` auth)."""

    _BASE = "https://api.sync.so/v2"

    def __init__(self) -> None:
        if not settings.SYNC_API_KEY:
            raise ProviderConfigError("SYNC_API_KEY is empty; required for RealSyncLipSyncer.")
        self._headers = {"x-api-key": settings.SYNC_API_KEY}

    def _upload(self, client: httpx.Client, path: Path) -> str:
        with path.open("rb") as fh:
            response = client.post(f"{self._BASE}/uploads", files={"file": (path.name, fh)})
        response.raise_for_status()
        return response.json()["url"]

    def sync(self, portrait_path: Path, audio_path: Path, out_path: Path) -> Path:
        with httpx.Client(headers=self._headers, timeout=_HTTP_TIMEOUT) as client:
            video_url = self._upload(client, Path(portrait_path))
            audio_url = self._upload(client, Path(audio_path))

            submit = client.post(
                f"{self._BASE}/generate",
                json={
                    "model": "lipsync-2",
                    "input": [
                        {"type": "video", "url": video_url},
                        {"type": "audio", "url": audio_url},
                    ],
                },
            )
            submit.raise_for_status()
            job_id = submit.json()["id"]

            deadline = _deadline()
            while True:
                status = client.get(f"{self._BASE}/generate/{job_id}")
                status.raise_for_status()
                body = status.json()
                state = body.get("status")
                if state == "COMPLETED":
                    url = body["outputUrl"]
                    break
                if state in {"FAILED", "REJECTED", "CANCELED", "TIMED_OUT"}:
                    raise ProviderConfigError(f"Sync render failed: {body!r}")
                if time.monotonic() > deadline:
                    raise ProviderConfigError("Sync render timed out.")
                time.sleep(_POLL_INTERVAL_S)

        return _download(url, out_path)


class RealMagicHourLipSyncer:
    """Talking-head render via Magic Hour (Bearer auth)."""

    _BASE = "https://api.magichour.ai/v1"

    def __init__(self) -> None:
        if not settings.MAGIC_HOUR_API_KEY:
            raise ProviderConfigError(
                "MAGIC_HOUR_API_KEY is empty; required for RealMagicHourLipSyncer."
            )
        self._headers = {"Authorization": f"Bearer {settings.MAGIC_HOUR_API_KEY}"}

    def _upload(self, client: httpx.Client, path: Path, extension: str) -> str:
        meta = client.post(
            f"{self._BASE}/files/upload-urls",
            json={"items": [{"type": "video", "extension": extension}]},
        )
        meta.raise_for_status()
        item = meta.json()["items"][0]
        with path.open("rb") as fh:
            put = httpx.put(item["upload_url"], content=fh.read(), timeout=_HTTP_TIMEOUT)
        put.raise_for_status()
        return item["file_path"]

    def sync(self, portrait_path: Path, audio_path: Path, out_path: Path) -> Path:
        with httpx.Client(headers=self._headers, timeout=_HTTP_TIMEOUT) as client:
            image_path = self._upload(client, Path(portrait_path), "png")
            audio_path_ref = self._upload(client, Path(audio_path), "wav")

            submit = client.post(
                f"{self._BASE}/lip-sync",
                json={
                    "assets": {
                        "image_file_path": image_path,
                        "audio_file_path": audio_path_ref,
                    }
                },
            )
            submit.raise_for_status()
            job_id = submit.json()["id"]

            deadline = _deadline()
            while True:
                status = client.get(f"{self._BASE}/image-projects/{job_id}")
                status.raise_for_status()
                body = status.json()
                state = body.get("status")
                if state == "complete":
                    url = body["downloads"][0]["url"]
                    break
                if state in {"error", "canceled"}:
                    raise ProviderConfigError(f"Magic Hour render failed: {body!r}")
                if time.monotonic() > deadline:
                    raise ProviderConfigError("Magic Hour render timed out.")
                time.sleep(_POLL_INTERVAL_S)

        return _download(url, out_path)
