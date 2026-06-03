"""Offline unit tests for the Replicate response-parsing helpers.

These can't be exercised against the live API in CI (it costs money and needs
credit), so the parsing/normalization logic the Real clients depend on is
pinned here with synthetic payloads shaped like real Demucs / WhisperX output.
"""

from __future__ import annotations

import pytest

from providers.base import ProviderConfigError
from providers.replicate import (
    RealWhisperXAligner,
    _audio_loader,
    _first_url,
    _is_throttle,
    _named_url,
    _run_with_throttle_retry,
)


class _Throttle(Exception):
    status = 429


class _Boom(Exception):
    status = 500


def test_is_throttle_detects_429():
    assert _is_throttle(_Throttle())
    assert not _is_throttle(_Boom())
    assert not _is_throttle(ValueError("x"))


def test_audio_loader_yields_fresh_named_streams(tmp_path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"RIFFdata")
    load = _audio_loader(p)
    a, b = load(), load()
    assert a is not b
    assert a.read() == b"RIFFdata" and b.read() == b"RIFFdata"  # each fresh/rewound
    assert a.name == "a.wav"


def test_throttle_retry_succeeds_after_429(monkeypatch):
    import providers.replicate as rep

    monkeypatch.setattr(rep.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    class FakeClient:
        def run(self, model, input):
            calls["n"] += 1
            if calls["n"] < 3:
                raise _Throttle()
            return "ok"

    out = _run_with_throttle_retry(FakeClient(), "m", lambda: {})
    assert out == "ok" and calls["n"] == 3


def test_throttle_retry_reraises_non_throttle(monkeypatch):
    import providers.replicate as rep

    monkeypatch.setattr(rep.time, "sleep", lambda _s: None)

    class FakeClient:
        def run(self, model, input):
            raise _Boom()

    with pytest.raises(_Boom):
        _run_with_throttle_retry(FakeClient(), "m", lambda: {})


class _FileOutput:
    """Mimic a Replicate FileOutput (a URL behind a ``.url`` attribute)."""

    def __init__(self, url: str) -> None:
        self.url = url


def test_first_url_from_bare_string():
    assert _first_url("https://x/y.mp3") == "https://x/y.mp3"


def test_first_url_from_dict_of_stems():
    # Demucs with stem=vocals returns a {stem: url} mapping.
    assert _first_url({"vocals": "https://x/vocals.mp3"}) == "https://x/vocals.mp3"


def test_first_url_from_list_and_fileoutput():
    assert _first_url([_FileOutput("https://x/a.mp3")]) == "https://x/a.mp3"


def test_first_url_raises_on_empty():
    with pytest.raises(ProviderConfigError):
        _first_url(None)


def test_named_url_selects_vocals_not_first():
    # Demucs returns {"no_vocals": ..., "vocals": ...}; we must pick vocals.
    output = {
        "no_vocals": _FileOutput("https://x/instrumental.mp3"),
        "vocals": _FileOutput("https://x/vocals.mp3"),
    }
    assert _named_url(output, "vocals") == "https://x/vocals.mp3"


def test_named_url_raises_when_stem_missing():
    with pytest.raises(ProviderConfigError):
        _named_url({"no_vocals": _FileOutput("https://x/i.mp3")}, "vocals")


def test_named_url_falls_back_to_first_for_bare_url():
    assert _named_url("https://x/y.mp3", "vocals") == "https://x/y.mp3"


def test_whisperx_flattens_segments_words():
    output = {
        "detected_language": "es",
        "segments": [
            {"words": [{"word": "hola", "start": 0.0, "end": 0.4}]},
            {"words": [{"word": "mundo", "start": 0.4, "end": 0.9}]},
        ],
    }
    words = RealWhisperXAligner._extract_word_segments(output)
    assert words == [
        {"word": "hola", "start": 0.0, "end": 0.4},
        {"word": "mundo", "start": 0.4, "end": 0.9},
    ]
    assert RealWhisperXAligner._extract_language(output) == "es"


def test_whisperx_drops_untimed_words_but_keeps_timed():
    output = {
        "word_segments": [
            {"word": "neon", "start": 0.1, "end": 0.5},
            {"word": "7"},  # untimed token — dropped
        ]
    }
    words = RealWhisperXAligner._extract_word_segments(output)
    assert words == [{"word": "neon", "start": 0.1, "end": 0.5}]


def test_whisperx_raises_when_all_untimed():
    with pytest.raises(ProviderConfigError):
        RealWhisperXAligner._extract_word_segments({"word_segments": [{"word": "7"}]})


def test_whisperx_language_defaults_to_en():
    assert RealWhisperXAligner._extract_language({"segments": []}) == "en"
