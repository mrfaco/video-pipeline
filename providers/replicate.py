"""Replicate-backed providers: Demucs vocal separation + WhisperX alignment.

Used when ``PROVIDER_MODE=real``. The ``replicate`` SDK is a heavy optional
dependency, so it is imported *inside* the method that uses it — a fake-only
run must import this module without it installed (AGENTS.md §5).

No fallbacks: a missing token raises at construction, and a non-2xx download
or a missing model output raises rather than returning a degraded artifact
(AGENTS.md §1). A silently-empty stem here would yield a silently broken video.
"""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from typing import Callable

import httpx
from django.conf import settings

from providers.base import ProviderConfigError

# Generous ceiling — model cold-starts and long renders take real time.
_HTTP_TIMEOUT = httpx.Timeout(600.0)

# Replicate throttles hard (6/min, burst 1) while account balance < $5. A 429
# is explicitly transient, so we wait out the window and retry rather than
# failing the whole pipeline on a rate cap.
_THROTTLE_RETRIES = 6
_THROTTLE_WAIT_S = 12.0


def _is_throttle(exc: Exception) -> bool:
    return getattr(exc, "status", None) == 429


def _run_with_throttle_retry(client: object, model: str, build_input: Callable[[], dict]) -> object:
    """Run a Replicate model, retrying only on 429 throttling.

    ``build_input`` is called fresh each attempt so a retry gets a rewound
    file handle, not a consumed one. Any non-throttle error, or the final
    attempt, propagates (no silent fallback).
    """
    for attempt in range(_THROTTLE_RETRIES):
        try:
            return client.run(model, input=build_input())  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001  # allow: suppress-exception
            # Retry transient throttles; raise everything else and the last try.
            if not _is_throttle(exc) or attempt == _THROTTLE_RETRIES - 1:
                raise
            time.sleep(_THROTTLE_WAIT_S)
    raise RuntimeError("unreachable: throttle retry loop exited without returning")


def _audio_loader(path: Path) -> Callable[[], io.BytesIO]:
    """Read the audio once; hand out a fresh, named BytesIO per attempt."""
    data = path.read_bytes()
    name = path.name

    def load() -> io.BytesIO:
        bio = io.BytesIO(data)
        bio.name = name  # replicate uses this for the upload filename/content-type
        return bio

    return load


def _download(url: str, out_path: Path) -> Path:
    """Stream a result URL to disk, raising on any non-2xx response."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, timeout=_HTTP_TIMEOUT, follow_redirects=True) as response:
        response.raise_for_status()
        with out_path.open("wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
    return out_path


def _named_url(output: object, key: str) -> str:
    """Pull the URL for a specific named output (e.g. the ``vocals`` stem).

    Demucs returns ``{"vocals": ..., "no_vocals": ...}`` — picking the first
    value blindly grabs the *instrumental*, which is the opposite of what we
    want, so the stem must be selected by name. Falls back to ``_first_url``
    for models that return a bare URL.
    """
    if isinstance(output, dict):
        if key not in output:
            raise ProviderConfigError(f"Replicate output has no {key!r} stem: {list(output)}")
        candidate = output[key]
        url = getattr(candidate, "url", candidate)
        if not isinstance(url, str) or not url:
            raise ProviderConfigError(f"Replicate {key!r} stem is not a URL: {candidate!r}")
        return url
    return _first_url(output)


def _first_url(output: object) -> str:
    """Pull a single downloadable URL out of a Replicate model output.

    Replicate returns either a bare URL string, a ``FileOutput`` whose ``url``
    attribute is the URL, or a list/dict of those. We take the first concrete
    URL and raise loudly if there isn't one.
    """
    candidate = output
    if isinstance(candidate, dict):
        # WhisperX-style dicts carry the audio/result under a known key; for a
        # bare file model the dict is usually a single {"path": url}-ish entry.
        candidate = next(iter(candidate.values()), None)
    if isinstance(candidate, (list, tuple)):
        candidate = candidate[0] if candidate else None
    if candidate is None:
        raise ProviderConfigError("Replicate returned no output to download.")
    url = getattr(candidate, "url", candidate)
    if not isinstance(url, str) or not url:
        raise ProviderConfigError(f"Replicate output is not a URL: {output!r}")
    return url


class RealDemucsSeparator:
    """Vocal separation via a Demucs model hosted on Replicate."""

    def __init__(self) -> None:
        if not settings.REPLICATE_API_TOKEN:
            raise ProviderConfigError(
                "REPLICATE_API_TOKEN is empty; required for RealDemucsSeparator."
            )
        self._model = settings.REPLICATE_DEMUCS_MODEL

    def separate(self, song_path: Path, out_path: Path) -> Path:
        import replicate  # noqa: PLC0415  (heavy optional SDK, real-mode only)

        client = replicate.Client(api_token=settings.REPLICATE_API_TOKEN)
        load = _audio_loader(Path(song_path))
        output = _run_with_throttle_retry(
            client, self._model, lambda: {"audio": load(), "stem": "vocals"}
        )
        # Demucs returns {"vocals": ..., "no_vocals": ...}; we need the vocals,
        # not the instrumental. Selecting by name is essential — the first dict
        # value is no_vocals.
        return _download(_named_url(output, "vocals"), out_path)


class RealWhisperXAligner:
    """Word-level caption alignment via a WhisperX model on Replicate."""

    def __init__(self) -> None:
        if not settings.REPLICATE_API_TOKEN:
            raise ProviderConfigError(
                "REPLICATE_API_TOKEN is empty; required for RealWhisperXAligner."
            )
        self._model = settings.REPLICATE_WHISPERX_MODEL

    def align(self, audio_path: Path, lyrics: str | None, out_path: Path) -> Path:
        import replicate  # noqa: PLC0415  (heavy optional SDK, real-mode only)

        client = replicate.Client(api_token=settings.REPLICATE_API_TOKEN)
        load = _audio_loader(Path(audio_path))

        def build_input() -> dict:
            model_input: dict[str, object] = {"audio_file": load(), "align_output": True}
            if lyrics:
                model_input["initial_prompt"] = lyrics
            if settings.WHISPERX_LANGUAGE:
                model_input["language"] = settings.WHISPERX_LANGUAGE
            return model_input

        output = _run_with_throttle_retry(client, self._model, build_input)

        word_segments = self._extract_word_segments(output)
        language = self._extract_language(output)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps({"language": language, "word_segments": word_segments}),
            encoding="utf-8",
        )
        return out_path

    @staticmethod
    def _extract_language(output: object) -> str:
        if isinstance(output, dict):
            language = output.get("language") or output.get("detected_language")
            if isinstance(language, str) and language:
                return language
        return "en"

    @staticmethod
    def _extract_word_segments(output: object) -> list[dict[str, object]]:
        """Normalise WhisperX output to ``[{word, start, end}, ...]``.

        WhisperX commonly returns ``{"segments": [{"words": [...]}]}`` or a
        top-level ``word_segments`` list. We flatten to the contract shape and
        raise if neither is present — never emit empty timings silently.
        """
        if not isinstance(output, dict):
            raise ProviderConfigError(f"WhisperX output is not a dict: {output!r}")

        raw_words: list[dict[str, object]] = []
        if isinstance(output.get("word_segments"), list):
            raw_words = list(output["word_segments"])
        elif isinstance(output.get("segments"), list):
            for segment in output["segments"]:
                if isinstance(segment, dict) and isinstance(segment.get("words"), list):
                    raw_words.extend(segment["words"])

        if not raw_words:
            raise ProviderConfigError(f"WhisperX output carried no word segments: {output!r}")

        # WhisperX leaves some tokens (numbers, punctuation) without alignment
        # timings — those can't be captioned, so drop them. This is correct
        # handling of the model's output, not a silent fallback: if *every*
        # word came back untimed we still raise below.
        segments = [
            {"word": word["word"], "start": word["start"], "end": word["end"]}
            for word in raw_words
            if isinstance(word, dict) and {"word", "start", "end"} <= word.keys()
        ]
        if not segments:
            raise ProviderConfigError(f"WhisperX returned no aligned words: {output!r}")
        return segments
