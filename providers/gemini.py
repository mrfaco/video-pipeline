"""Real video-understanding backend: Google Gemini.

Gemini is the only major API with *native* video input — you send the actual
clip (not extracted frames), so camera motion, choreography, and the audio
beat are all preserved, which is exactly what we want described. The
``google-genai`` SDK is imported at the callsite (``# noqa: PLC0415``) so a
fake-only run never needs it installed.

This client is only ever exercised live in ``PROVIDER_MODE=real``; the request
shape (inline video blob + a JSON response schema) is a best-effort match to
the documented API, not a contract verified in CI (AGENTS.md / CLAUDE.md). When
you first run it for real, confirm the SDK call and fix here if needed.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings

from providers.base import ProviderConfigError

_FIELDS = ("theme", "style", "motion", "hook")
_SHOT_KEYS = ("time", "action", "camera")


class GeminiResponseError(RuntimeError):
    """Gemini returned a response that did not parse to the expected fields."""


class RealGeminiVideoUnderstander:
    """Describe a trend clip with Gemini, returning draft preset fields."""

    def __init__(self) -> None:
        if not settings.GEMINI_API_KEY:
            raise ProviderConfigError(
                "GEMINI_API_KEY is empty; required for RealGeminiVideoUnderstander."
            )

    def describe(self, video_path: Path) -> dict[str, object]:
        from google import genai  # noqa: PLC0415  (heavy optional SDK, real-mode only)
        from google.genai import types  # noqa: PLC0415

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        video_bytes = Path(video_path).read_bytes()
        shot_schema = {
            "type": "object",
            "properties": {key: {"type": "string"} for key in _SHOT_KEYS},
            "required": list(_SHOT_KEYS),
        }
        response = client.models.generate_content(
            model=settings.VIDEO_UNDERSTAND_MODEL,
            contents=types.Content(
                parts=[
                    types.Part(
                        inline_data=types.Blob(data=video_bytes, mime_type="video/mp4"),
                        video_metadata=types.VideoMetadata(fps=settings.VIDEO_UNDERSTAND_FPS),
                    ),
                    types.Part(text=settings.TREND_DESCRIBE_PROMPT),
                ],
            ),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
                    "type": "object",
                    "properties": {
                        **{field: {"type": "string"} for field in _FIELDS},
                        "shots": {"type": "array", "items": shot_schema},
                    },
                    "required": [*_FIELDS, "shots"],
                },
            ),
        )
        try:
            data = json.loads(response.text)
            result: dict[str, object] = {field: str(data[field]).strip() for field in _FIELDS}
            result["shots"] = [
                {key: str(shot[key]).strip() for key in _SHOT_KEYS} for shot in data["shots"]
            ]
            return result
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            expected = (*_FIELDS, "shots")
            raise GeminiResponseError(
                f"Gemini did not return the expected fields {expected}: {response.text!r}"
            ) from exc
