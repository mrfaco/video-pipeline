"""Seedream 4.5 scene generator — photoreal, reference-image identity.

Alma's identity engine after the FLUX-1 LoRA hit its realism ceiling. Instead of
a trained LoRA, identity is locked by passing her reference image(s) to Seedream
(`image_urls`), which keeps her face while rendering genuinely photoreal scenes.
Implements the same ``SceneGenerator`` Protocol as the FLUX client, so the
pipeline calls it identically; ``lora``/``trigger``/``lora_scale`` are ignored
(Seedream has no LoRA). The ``reference_image`` IS the identity lock here.

``fal_client`` is imported at the callsite (heavy optional SDK, real-mode only).
"""

from __future__ import annotations

from pathlib import Path

import httpx
from django.conf import settings

from providers.base import ProviderConfigError


class RealSeedreamSceneGenerator:
    """Generate a photoreal scene still, identity locked by a reference image."""

    def __init__(self) -> None:
        if not settings.FAL_KEY:
            raise ProviderConfigError("FAL_KEY is empty; required for RealSeedreamSceneGenerator.")
        self._model = settings.SEEDREAM_MODEL

    def generate(
        self,
        prompt: str,
        out_path: Path,
        reference_image: Path | None = None,
        lora: str | None = None,
        trigger: str | None = None,
        lora_scale: float | None = None,
    ) -> Path:
        import fal_client  # noqa: PLC0415  (heavy optional SDK, real-mode only)

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        arguments: dict = {"prompt": prompt, "image_size": "portrait_16_9", "num_images": 1}
        # The reference image is the identity lock (Seedream's character
        # consistency). Uploaded so fal can read it.
        if reference_image is not None:
            arguments["image_urls"] = [fal_client.upload_file(Path(reference_image))]
        result = fal_client.subscribe(self._model, arguments=arguments)
        if not isinstance(result, dict):
            raise ProviderConfigError(f"Seedream result is not a dict: {result!r}")
        images = result.get("images")
        if not isinstance(images, list) or not images:
            raise ProviderConfigError(f"Seedream result missing images: {result!r}")
        url = images[0].get("url") if isinstance(images[0], dict) else images[0]
        if not isinstance(url, str) or not url:
            raise ProviderConfigError(f"Seedream result missing an image URL: {result!r}")
        out_path.write_bytes(httpx.get(url, timeout=120).content)
        return out_path
