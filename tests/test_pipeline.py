"""End-to-end + glue tests for the pipeline spine.

The headline test drives the *entire* Celery chain eagerly with
``PROVIDER_MODE=fake``: the Fake providers return fixtures, real ffmpeg
composes a real ``output.mp4``, and Telegram is left unconfigured (so delivery
is skipped, not mocked). This is the "works end-to-end with tests" guarantee.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from django.test import override_settings

from core.context import JobContext
from jobs.models import Artifact, Job
from jobs.orchestrator import run_job
from jobs.presets import PresetError, create_job_from_preset, load_preset
from stages.tasks import separate_vocals

# Eager execution is configured in the rootdir conftest.py (CELERY_TASK_ALWAYS_EAGER).
PRESET = "presets/demo.yaml"


def _ffprobe_has_video(path: Path) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        check=True,
        capture_output=True,
    )
    streams = json.loads(out.stdout)["streams"]
    return any(s.get("codec_type") == "video" for s in streams)


# --- preset loading -------------------------------------------------------


def test_load_preset_reads_demo():
    preset = load_preset(PRESET)
    assert preset["theme"]
    assert preset["lyrics"].startswith("neon")
    assert Path(preset["audio_path"]).is_file()
    assert Path(preset["character_ref"]).is_file()


def test_load_preset_missing_file_raises():
    with pytest.raises(PresetError):
        load_preset("presets/does-not-exist.yaml")


def test_load_preset_mode_defaults_and_parses(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(
        "song:\n  audio: fixtures/song.mp3\ntheme: t\n"
        "character:\n  image: fixtures/character_portrait.png\n",
        encoding="utf-8",
    )
    assert load_preset(str(p))["mode"] == "dance"
    p.write_text(
        "song:\n  audio: fixtures/song.mp3\ntheme: t\nmode: closeup\n"
        "character:\n  image: fixtures/character_portrait.png\n",
        encoding="utf-8",
    )
    assert load_preset(str(p))["mode"] == "closeup"


def test_load_preset_rejects_bad_mode(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "song:\n  audio: fixtures/song.mp3\ntheme: t\nmode: sideways\n"
        "character:\n  image: fixtures/character_portrait.png\n",
        encoding="utf-8",
    )
    with pytest.raises(PresetError):
        load_preset(str(p))


def test_load_preset_dance_allows_no_character(tmp_path):
    # Dance mode invents the girl in the scene, so a character block is optional.
    p = tmp_path / "dance.yaml"
    p.write_text(
        "song:\n  audio: fixtures/song.mp3\ntheme: a neon city\nmode: dance\n", encoding="utf-8"
    )
    preset = load_preset(str(p))
    assert preset["mode"] == "dance"
    assert preset["character_ref"] == ""


def test_load_preset_closeup_requires_character(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("song:\n  audio: fixtures/song.mp3\ntheme: t\nmode: closeup\n", encoding="utf-8")
    with pytest.raises(PresetError):
        load_preset(str(p))


def test_load_preset_source_variant():
    preset = load_preset("presets/from_source.yaml")
    assert preset["audio_path"] is None
    assert preset["audio_source"] == "Blinding Lights The Weeknd"


def test_load_preset_character_description_and_clip():
    # brujeria.yaml uses a text character description + a source + a clip range.
    preset = load_preset("presets/brujeria.yaml")
    assert preset["character_ref"].startswith("a charismatic Latin salsa singer")
    assert preset["clip"] == "1:04-1:20"
    assert preset["audio_source"] == "Brujería Gilberto Santa Rosa"


def _image_preset(tmp_path) -> str:
    p = tmp_path / "img.yaml"
    p.write_text(
        "song:\n  audio: fixtures/song.mp3\n"
        "theme: a place\nmode: closeup\n"
        "character:\n  image: fixtures/character_portrait.png\n",
        encoding="utf-8",
    )
    return str(p)


def test_load_preset_image_variant(tmp_path):
    preset = load_preset(_image_preset(tmp_path))
    assert preset["character_image"].endswith("character_portrait.png")
    assert preset["character_ref"].endswith("character_portrait.png")


def test_load_preset_rejects_two_character_options(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "song:\n  audio: fixtures/song.mp3\n"
        "theme: a place\n"
        "character:\n  image: fixtures/character_portrait.png\n  description: a person\n",
        encoding="utf-8",
    )
    with pytest.raises(PresetError):
        load_preset(str(p))


def test_load_preset_backup_variant():
    preset = load_preset("presets/trio.yaml")
    assert preset["character_image"].endswith("pink_girl.png")
    assert preset["backup_character_ref"].startswith("a bizarre")


def _trio_preset(tmp_path) -> str:
    p = tmp_path / "trio.yaml"
    p.write_text(
        "song:\n  audio: fixtures/song.mp3\n"
        "theme: a place\nmode: closeup\n"
        "character:\n  image: fixtures/character_portrait.png\n"
        "backup:\n  image: fixtures/character_portrait.png\n",
        encoding="utf-8",
    )
    return str(p)


@pytest.mark.django_db
def test_pipeline_trio_renders_backup(tmp_path):
    with override_settings(
        MEDIA_ROOT=tmp_path, PROVIDER_MODE="fake", TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID=""
    ):
        job = create_job_from_preset(_trio_preset(tmp_path))
        assert job.backup_character_image  # backup copied at creation
        run_job(job, eager=True)
        job.refresh_from_db()
        assert job.status == Job.Status.DELIVERED, job.error_detail
        kinds = set(Artifact.objects.filter(job=job).values_list("kind", flat=True))
        assert {"backup_portrait", "backup_lipsync", "output"} <= kinds
        assert Path(job.output_path).is_file()


@pytest.mark.django_db
def test_pipeline_uses_character_image_as_is(tmp_path):
    with override_settings(
        MEDIA_ROOT=tmp_path, PROVIDER_MODE="fake", TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID=""
    ):
        job = create_job_from_preset(_image_preset(tmp_path))
        assert job.character_image  # copied into the job dir at creation
        run_job(job, eager=True)
        job.refresh_from_db()
        assert job.status == Job.Status.DELIVERED, job.error_detail
        portrait = Artifact.objects.get(job=job, kind="portrait")
        # Used as-is: byte-identical to the supplied greenscreen image.
        assert (
            Path(portrait.path).read_bytes() == Path("fixtures/character_portrait.png").read_bytes()
        )


@pytest.mark.django_db
def test_create_job_from_source_preset_defers_download(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        job = create_job_from_preset("presets/from_source.yaml")
    assert job.song_filename == ""
    assert job.song_source == "Blinding Lights The Weeknd"


@pytest.mark.django_db
def test_create_job_from_preset_copies_song(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        job = create_job_from_preset(PRESET)
    assert job.theme
    assert Path(job.song_filename).is_file()
    assert job.character_ref


# --- full chain -----------------------------------------------------------


@pytest.mark.django_db
def test_full_pipeline_produces_video(tmp_path):
    with override_settings(
        MEDIA_ROOT=tmp_path,
        PROVIDER_MODE="fake",
        ENABLE_CAPTIONS=True,
        TELEGRAM_BOT_TOKEN="",
        TELEGRAM_CHAT_ID="",
    ):
        job = create_job_from_preset(PRESET)
        run_job(job, eager=True)
        job.refresh_from_db()

        assert job.status == Job.Status.DELIVERED, job.error_detail
        assert job.output_path
        output = Path(job.output_path)
        assert output.is_file()
        assert _ffprobe_has_video(output)
        assert job.suggested_caption

        # Every stage that produces an artifact recorded one.
        kinds = set(Artifact.objects.filter(job=job).values_list("kind", flat=True))
        assert {"normalized_full", "vocal_stem", "captions", "background_loop", "output"} <= kinds


@pytest.mark.django_db
def test_pipeline_dance_mode(tmp_path):
    # Dance mode: scene-gen (fixture) -> fake Kling -> compose_scene. No vocals,
    # no portrait, no lipsync artifacts; a real video still comes out.
    p = tmp_path / "dance.yaml"
    p.write_text(
        "song:\n  audio: fixtures/song.mp3\ntheme: a neon city\nmode: dance\n", encoding="utf-8"
    )
    with override_settings(
        MEDIA_ROOT=tmp_path, PROVIDER_MODE="fake", TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID=""
    ):
        job = create_job_from_preset(str(p))
        assert job.mode == "dance"
        run_job(job, eager=True)
        job.refresh_from_db()
        assert job.status == Job.Status.DELIVERED, job.error_detail
        assert _ffprobe_has_video(Path(job.output_path))
        kinds = set(Artifact.objects.filter(job=job).values_list("kind", flat=True))
        # Dance separates vocals only to transcribe them into karaoke captions —
        # no greenscreen portrait and no lip-sync layer.
        assert {"scene", "captions", "vocal_stem"} <= kinds
        assert {"portrait", "lipsync"} & kinds == set()


@pytest.mark.django_db
def test_pipeline_dance_beat_cuts(tmp_path):
    # Dance with 3 beat-synced scene cuts: 3 scene clips generated + cut into one.
    p = tmp_path / "dance.yaml"
    p.write_text(
        "song:\n  audio: fixtures/song.mp3\ntheme: a neon city\nmode: dance\n", encoding="utf-8"
    )
    with override_settings(
        MEDIA_ROOT=tmp_path,
        PROVIDER_MODE="fake",
        DANCE_SCENE_CUTS=3,
        TELEGRAM_BOT_TOKEN="",
        TELEGRAM_CHAT_ID="",
    ):
        job = create_job_from_preset(str(p))
        run_job(job, eager=True)
        job.refresh_from_db()
        assert job.status == Job.Status.DELIVERED, job.error_detail
        assert _ffprobe_has_video(Path(job.output_path))
        scene_count = Artifact.objects.filter(job=job, kind="scene").count()
        assert scene_count == 3


@pytest.mark.django_db
def test_pipeline_vibe_mode(tmp_path):
    # Vibe: cinematic scene-gen -> gentle Kling -> clean compose. No vocals, no
    # captions, no portrait, no lipsync — just the looping scene + audio.
    p = tmp_path / "vibe.yaml"
    p.write_text(
        "song:\n  audio: fixtures/song.mp3\ntheme: a city skyline at dusk\nmode: vibe\n",
        encoding="utf-8",
    )
    with override_settings(
        MEDIA_ROOT=tmp_path, PROVIDER_MODE="fake", TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID=""
    ):
        job = create_job_from_preset(str(p))
        assert job.mode == "vibe"
        run_job(job, eager=True)
        job.refresh_from_db()
        assert job.status == Job.Status.DELIVERED, job.error_detail
        output = Path(job.output_path)
        assert _ffprobe_has_video(output)
        # Vibe is mute — no audio stream, and no audio artifacts at all.
        streams = json.loads(
            subprocess.run(
                ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)],
                check=True, capture_output=True,
            ).stdout
        )["streams"]
        assert not any(s.get("codec_type") == "audio" for s in streams)
        kinds = set(Artifact.objects.filter(job=job).values_list("kind", flat=True))
        assert "scene" in kinds
        assert {
            "vocal_stem", "captions", "portrait", "lipsync", "hook", "normalized_full"
        } & kinds == set()


@pytest.mark.django_db
def test_pipeline_dance_with_hook(tmp_path):
    p = tmp_path / "dance.yaml"
    p.write_text(
        'song:\n  audio: fixtures/song.mp3\ntheme: a city\nmode: dance\nhook: "POV: test"\n',
        encoding="utf-8",
    )
    with override_settings(
        MEDIA_ROOT=tmp_path, PROVIDER_MODE="fake", TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID=""
    ):
        job = create_job_from_preset(str(p))
        assert job.hook == "POV: test"
        run_job(job, eager=True)
        job.refresh_from_db()
        assert job.status == Job.Status.DELIVERED, job.error_detail
        assert "hook" in set(Artifact.objects.filter(job=job).values_list("kind", flat=True))


@pytest.mark.django_db
def test_pipeline_motion_first_mode(tmp_path):
    # motion_first runs Kling (animate) -> video lip-sync -> matte; in fake mode
    # those are fixture/passthrough/ffmpeg, so the whole chain still produces a
    # video.
    with override_settings(
        MEDIA_ROOT=tmp_path,
        PROVIDER_MODE="fake",
        MOTION_MODE="motion_first",
        TELEGRAM_BOT_TOKEN="",
        TELEGRAM_CHAT_ID="",
    ):
        job = create_job_from_preset(PRESET)
        run_job(job, eager=True)
        job.refresh_from_db()
        assert job.status == Job.Status.DELIVERED, job.error_detail
        assert _ffprobe_has_video(Path(job.output_path))


@pytest.mark.django_db
def test_pipeline_skips_captions_without_lyrics(tmp_path):
    with override_settings(
        MEDIA_ROOT=tmp_path,
        PROVIDER_MODE="fake",
        TELEGRAM_BOT_TOKEN="",
        TELEGRAM_CHAT_ID="",
    ):
        job = create_job_from_preset(PRESET)
        # Clear lyrics so captions are skipped.
        job.lyrics = ""
        job.save(update_fields=["lyrics"])
        run_job(job, eager=True)
        job.refresh_from_db()

        assert job.status == Job.Status.DELIVERED, job.error_detail
        assert Path(job.output_path).is_file()
        kinds = set(Artifact.objects.filter(job=job).values_list("kind", flat=True))
        assert "captions" not in kinds


@pytest.mark.django_db
def test_align_captions_skips_on_empty_transcription(tmp_path, monkeypatch):
    # An untranscribable (instrumental) song must NOT fail the render — captions
    # are best-effort, so the stage skips them and returns cleanly.
    from providers.replicate import EmptyTranscriptionError

    class _EmptyAligner:
        def align(self, audio_path, lyrics, out_path):
            raise EmptyTranscriptionError("no words")

    import stages.tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "get_caption_aligner", lambda: _EmptyAligner())
    with override_settings(MEDIA_ROOT=tmp_path):
        dance = tmp_path / "d.yaml"
        dance.write_text(
            "song:\n  audio: fixtures/song.mp3\ntheme: t\nmode: dance\n", encoding="utf-8"
        )
        job = create_job_from_preset(str(dance))
        ctx = JobContext(
            job_id=str(job.job_id),
            theme="t",
            character_ref="",
            song_path="s",
            mode="dance",
            enable_captions=True,
            song_full_path=str(Path("fixtures/song.mp3")),
        )
        out = tasks_mod.align_captions(ctx.to_dict())
    assert JobContext.from_dict(out).captions_path is None


# --- failure bookkeeping --------------------------------------------------


@pytest.mark.django_db
def test_stage_failure_marks_job(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path, TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID=""):
        job = create_job_from_preset(PRESET)
        ctx = JobContext(
            job_id=job.job_id,
            theme=job.theme,
            character_ref=job.character_ref,
            song_path=job.song_filename,
            song_normalized_path=job.song_filename,
        ).to_dict()
        # Invoke the base-task failure hook directly (no Celery retry machinery).
        separate_vocals.on_failure(
            RuntimeError("demucs exploded"),
            task_id="t1",
            args=(ctx,),
            kwargs={},
            einfo=None,
        )
        job.refresh_from_db()
        assert job.status == Job.Status.FAILED
        assert job.failed_stage == "separate_vocals"
        assert "demucs exploded" in job.error_detail
