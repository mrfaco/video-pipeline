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


def test_context_carries_drive_fields():
    ctx = JobContext(
        job_id="j", theme="t", character_ref="", song_path="",
        mode="mimic", drive_source="https://x/y", drive_video_path="/d/drive.mp4",
    )
    round_tripped = JobContext.from_dict(ctx.to_dict())
    assert round_tripped.drive_source == "https://x/y"
    assert round_tripped.drive_video_path == "/d/drive.mp4"
    assert round_tripped.schema_version == 12


def test_context_carries_lora_fields():
    ctx = JobContext(
        job_id="j", theme="t", character_ref="", song_path="",
        character_lora="https://x/l.safetensors", character_trigger="neongirl",
    )
    rt = JobContext.from_dict(ctx.to_dict())
    assert rt.character_lora == "https://x/l.safetensors"
    assert rt.character_trigger == "neongirl"
    assert rt.schema_version == 12
