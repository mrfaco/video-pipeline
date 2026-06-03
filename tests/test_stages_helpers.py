"""Unit tests for the small pure helpers in the stages package."""

from __future__ import annotations

from pathlib import Path

import pytest

from stages.base import extract_job_id, short_stage_name
from stages.tasks import _build_caption, _require_path


def test_extract_job_id_from_string():
    assert extract_job_id(("abc-123",)) == "abc-123"


def test_extract_job_id_from_ctx_dict():
    assert extract_job_id(({"job_id": "xyz"},)) == "xyz"


def test_extract_job_id_handles_empty_and_unknown():
    assert extract_job_id(()) is None
    assert extract_job_id((42,)) is None
    assert extract_job_id(({"no_job": 1},)) is None


def test_short_stage_name():
    assert short_stage_name("stages.tasks.separate_vocals") == "separate_vocals"
    assert short_stage_name("compose_video") == "compose_video"


def test_require_path_returns_path():
    assert _require_path("/tmp/x.mp4") == Path("/tmp/x.mp4")


def test_require_path_raises_on_none():
    with pytest.raises(ValueError, match="prior stage"):
        _require_path(None)


def test_build_caption_uses_lyrics_first_line():
    caption = _build_caption("a theme", "first line\nsecond line")
    assert caption.startswith("first line")
    assert "#fyp" in caption


def test_build_caption_falls_back_when_empty():
    caption = _build_caption("", "")
    assert caption.startswith("new drop")
