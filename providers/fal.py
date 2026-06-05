"""fal-backed providers: FLUX still + greenscreen portrait, image->video loop.

Used when ``PROVIDER_MODE=real``. ``fal_client`` is a heavy optional
dependency imported at the callsite so a fake-only run imports this module
without it (AGENTS.md §5).

No fallbacks: a missing key raises at construction, and a missing result URL
or a non-2xx download raises (AGENTS.md §1).
"""

from __future__ import annotations

from pathlib import Path

import httpx
from django.conf import settings

from providers.base import ProviderConfigError

_HTTP_TIMEOUT = httpx.Timeout(600.0)


def _download(url: str, out_path: Path) -> Path:
    """Stream a fal result URL to disk, raising on any non-2xx response."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, timeout=_HTTP_TIMEOUT, follow_redirects=True) as response:
        response.raise_for_status()
        with out_path.open("wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
    return out_path


def _result_url(result: object, key: str) -> str:
    """Extract the first media URL out of a fal result payload.

    fal returns ``{"images": [{"url": ...}]}`` or ``{"video": {"url": ...}}``
    depending on the model. We pull the URL under ``key`` and raise if absent
    rather than returning a placeholder.
    """
    if not isinstance(result, dict):
        raise ProviderConfigError(f"fal result is not a dict: {result!r}")
    payload = result.get(key)
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    if isinstance(payload, dict):
        payload = payload.get("url")
    if not isinstance(payload, str) or not payload:
        raise ProviderConfigError(f"fal result missing a {key!r} URL: {result!r}")
    return payload


class RealFalBackgroundGenerator:
    """FLUX still + image->video motion loop via fal."""

    def __init__(self) -> None:
        if not settings.FAL_KEY:
            raise ProviderConfigError("FAL_KEY is empty; required for RealFalBackgroundGenerator.")
        self._flux_model = settings.FAL_FLUX_MODEL
        self._i2v_model = settings.FAL_IMAGE_TO_VIDEO_MODEL

    def generate_still(self, theme: str, out_path: Path) -> Path:
        import fal_client  # noqa: PLC0415  (heavy optional SDK, real-mode only)

        result = fal_client.subscribe(
            self._flux_model,
            arguments={"prompt": theme, "image_size": "portrait_16_9"},
        )
        return _download(_result_url(result, "images"), out_path)

    # The bg loop is boomeranged in compose, so we want gentle ambient motion,
    # not a hard camera move. The i2v model requires a text prompt.
    _MOTION_PROMPT = "subtle ambient cinematic motion, slow drift, seamless loop"

    def animate(self, still_path: Path, out_path: Path) -> Path:
        import fal_client  # noqa: PLC0415  (heavy optional SDK, real-mode only)

        image_url = fal_client.upload_file(still_path)
        result = fal_client.subscribe(
            self._i2v_model,
            arguments={"image_url": image_url, "prompt": self._MOTION_PROMPT},
        )
        return _download(_result_url(result, "video"), out_path)


class RealFalSceneGenerator:
    """One integrated scene still (girl + environment together) for dance mode.

    Unlike the portrait generator, there's no greenscreen and no compositing —
    the model draws the character inside the scene so the dance clip is a single
    cohesive frame. Vertical 9:16 to match the canvas.
    """

    def __init__(self) -> None:
        if not settings.FAL_KEY:
            raise ProviderConfigError("FAL_KEY is empty; required for RealFalSceneGenerator.")
        self._model = settings.SCENE_IMAGE_MODEL

    def generate(
        self, prompt: str, out_path: Path, reference_image: Path | None = None
    ) -> Path:
        import fal_client  # noqa: PLC0415  (heavy optional SDK, real-mode only)

        # With a reference face, lock the SAME person into the new scene via a
        # PuLID identity model (persistent character). Otherwise the text-only
        # scene model invents a fresh "same-vibe" woman.
        # The safety checker returns an all-black image when it flags a prompt
        # ("attractive woman dancing" trips it), so it's disabled for these
        # non-explicit creative scenes — else the motion model gets a black frame.
        if reference_image is not None:
            ref_url = fal_client.upload_file(Path(reference_image))
            result = fal_client.subscribe(
                settings.CHARACTER_SCENE_MODEL,
                arguments={
                    "prompt": prompt,
                    "reference_image_url": ref_url,
                    "image_size": "portrait_16_9",
                    "id_weight": settings.CHARACTER_ID_WEIGHT,
                    "enable_safety_checker": False,
                },
            )
        else:
            result = fal_client.subscribe(
                self._model,
                arguments={
                    "prompt": prompt,
                    "aspect_ratio": "9:16",
                    "enable_safety_checker": False,
                    "safety_tolerance": "6",
                },
            )
        return _download(_result_url(result, "images"), out_path)


class RealFalPortraitGenerator:
    """Ultra-realistic greenscreen portrait via FLUX on fal."""

    def __init__(self) -> None:
        if not settings.FAL_KEY:
            raise ProviderConfigError("FAL_KEY is empty; required for RealFalPortraitGenerator.")
        self._flux_model = settings.FAL_FLUX_MODEL

    def generate(self, character_ref: str, out_path: Path) -> Path:
        import fal_client  # noqa: PLC0415  (heavy optional SDK, real-mode only)

        # Per-video identity (character_ref) + the invariant style/greenscreen
        # default. See settings.CHARACTER_STYLE_PROMPT.
        prompt = f"{character_ref}, {settings.CHARACTER_STYLE_PROMPT}"
        result = fal_client.subscribe(
            self._flux_model,
            arguments={"prompt": prompt, "image_size": "portrait_16_9"},
        )
        return _download(_result_url(result, "images"), out_path)
