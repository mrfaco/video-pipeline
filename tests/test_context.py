"""Tests for the JobContext schema (mode field + round-trip)."""

from __future__ import annotations

from core.context import SCHEMA_VERSION, JobContext


def test_mode_defaults_to_dance():
    ctx = JobContext(job_id="j", theme="t", character_ref="c", song_path="s")
    assert ctx.mode == "dance"
    assert ctx.scene_clip_path is None
    assert SCHEMA_VERSION >= 5


def test_mode_roundtrips():
    ctx = JobContext(job_id="j", theme="t", character_ref="c", song_path="s", mode="closeup")
    assert JobContext.from_dict(ctx.to_dict()).mode == "closeup"
