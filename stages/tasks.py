"""The seven pipeline stages.

Each stage is a thin Celery task: it marks the job's progress, calls exactly
one provider / compose / delivery function, records the artifact it produced,
and returns the (mutated) ``ctx`` for the next link in the chain. All the
heavy lifting lives in ``providers`` / ``compose`` / ``delivery``; all failure
bookkeeping lives in ``stages.base.PipelineTask``. Artifacts are namespaced by
``job_id`` so a re-run overwrites cleanly (idempotency).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from celery import shared_task
from django.conf import settings

from compose.captions import build_ass, window_words
from compose.ffmpeg import compose_final
from core.audio import clip_audio, normalize_loudness, parse_timerange
from core.beat import detect_beat_period
from core.context import JobContext
from core.fetch import fetch_audio
from core.storage import artifact_path
from delivery.telegram import send_video
from jobs.models import Artifact, Job
from providers.base import (
    get_animator,
    get_background_generator,
    get_caption_aligner,
    get_lip_syncer,
    get_matter,
    get_portrait_generator,
    get_video_lip_syncer,
    get_vocal_separator,
)
from stages.base import PipelineTask

logger = logging.getLogger(__name__)

# Shared task options: any provider error is retried with backoff; once retries
# are exhausted PipelineTask.on_failure records the failure. No ``bind`` — the
# bodies never call ``self`` (autoretry handles retries).
_TASK_OPTS = {
    "base": PipelineTask,
    "autoretry_for": (Exception,),
    "max_retries": 3,
    "retry_backoff": True,
    "retry_backoff_max": 60,
}


def _advance(job_id: str, stage: str) -> None:
    Job.objects.filter(pk=job_id).update(status=Job.Status.RUNNING, current_stage=stage)


def _record(job_id: str, stage: str, kind: str, path: Path) -> None:
    Artifact.objects.create(job_id=job_id, stage=stage, kind=kind, path=str(path))


def _require_path(value: str | None) -> Path:
    """An upstream artifact path that must exist by now — loud if it doesn't.

    Narrows ``str | None`` to ``Path`` and turns a stage running out of order
    (a None where a prior stage should have set a path) into a clear failure
    rather than a confusing ``Path(None)`` TypeError deep in a provider.
    """
    if value is None:
        raise ValueError("Required artifact path is missing from ctx; a prior stage did not run.")
    return Path(value)


def _resolve_portrait(job_id: str, ref: str, image: str | None, basename: str) -> Path:
    """A ready-made greenscreen image (copy as-is) or a generated portrait."""
    if image:
        src = Path(image)
        portrait = artifact_path(job_id, f"{basename}{src.suffix}")
        shutil.copyfile(src, portrait)
        return portrait
    portrait = artifact_path(job_id, f"{basename}.png")
    get_portrait_generator().generate(ref, portrait)
    return portrait


def _build_caption(theme: str, lyrics: str | None) -> str:
    """A suggested TikTok caption + hashtags from the theme/lyrics.

    Deterministic template — the operator edits it before posting. Keep the
    embedded-song reminder out; the caption is for the post, not the render.
    """
    hook = (lyrics or theme).strip().splitlines()[0] if (lyrics or theme).strip() else "new drop"
    tags = "#ai #synthwave #fyp #aimusic #tiktokmusic"
    return f"{hook} 🎶\n\n{tags}"


@shared_task(**_TASK_OPTS)
def prepare_assets(job_id: str) -> dict:
    _advance(job_id, "prepare_assets")
    job = Job.objects.get(pk=job_id)

    # If the preset gave a url/query instead of a local file, fetch it now.
    if not job.song_filename:
        if not job.song_source:
            raise ValueError(f"Job {job_id} has neither a song file nor a song source.")
        fetched = fetch_audio(job.song_source, artifact_path(job_id, "source.mp3"))
        job.song_filename = str(fetched)
        job.save(update_fields=["song_filename"])
        _record(job_id, "prepare_assets", "fetched_audio", fetched)

    song_src = Path(job.song_filename)

    # Normalize the full song first; captions transcribe this (WhisperX's VAD
    # is unreliable on a short clip — see align_captions).
    full_normalized = artifact_path(job_id, "normalized_full.mp3")
    normalize_loudness(song_src, full_normalized)
    _record(job_id, "prepare_assets", "normalized_full", full_normalized)

    # Optional trim to a hook (keeps lip-sync render time/cost down). The clip
    # is what every downstream stage operates on; the full song is kept only
    # for caption transcription.
    clip_start_s = 0.0
    clip_end_s = 0.0
    if job.song_clip:
        clip_start_s, clip_end_s = parse_timerange(job.song_clip)
        clip = artifact_path(job_id, "clip.mp3")
        clip_audio(full_normalized, clip, clip_start_s, clip_end_s)
        downstream = clip
        _record(job_id, "prepare_assets", "clipped_audio", clip)
    else:
        downstream = full_normalized

    ctx = JobContext(
        job_id=job_id,
        theme=job.theme,
        character_ref=job.character_ref,
        lyrics=(job.lyrics or None),
        enable_captions=bool(settings.ENABLE_CAPTIONS and job.lyrics),
        character_image=(job.character_image or None),
        backup_character_ref=(job.backup_character_ref or None),
        backup_character_image=(job.backup_character_image or None),
        song_path=str(song_src),
        song_normalized_path=str(downstream),
        song_full_path=str(full_normalized),
        clip_start_s=clip_start_s,
        clip_end_s=clip_end_s,
    )
    return ctx.to_dict()


@shared_task(**_TASK_OPTS)
def separate_vocals(payload: dict) -> dict:
    ctx = JobContext.from_dict(payload)
    _advance(ctx.job_id, "separate_vocals")
    out = artifact_path(ctx.job_id, "vocal_stem.wav")
    get_vocal_separator().separate(_require_path(ctx.song_normalized_path), out)
    ctx.vocal_stem_path = str(out)
    _record(ctx.job_id, "separate_vocals", "vocal_stem", out)
    return ctx.to_dict()


@shared_task(**_TASK_OPTS)
def align_captions(payload: dict) -> dict:
    ctx = JobContext.from_dict(payload)
    _advance(ctx.job_id, "align_captions")
    if not ctx.enable_captions:
        logger.info("Captions disabled for job %s; skipping alignment.", ctx.job_id)
        return ctx.to_dict()
    # Transcribe the FULL song (WhisperX's VAD is unreliable on a short
    # isolated clip but nails the full mix), then window the words down to the
    # clip and rebase them into clip time.
    full_words = artifact_path(ctx.job_id, "word_timestamps_full.json")
    get_caption_aligner().align(_require_path(ctx.song_full_path), ctx.lyrics, full_words)

    words = artifact_path(ctx.job_id, "word_timestamps.json")
    if ctx.clip_end_s > 0:
        window_words(full_words, words, ctx.clip_start_s, ctx.clip_end_s)
    else:
        words = full_words
    ctx.word_timestamps_path = str(words)
    _record(ctx.job_id, "align_captions", "word_timestamps", words)

    captions = artifact_path(ctx.job_id, "captions.ass")
    build_ass(words, captions)
    ctx.captions_path = str(captions)
    _record(ctx.job_id, "align_captions", "captions", captions)
    return ctx.to_dict()


@shared_task(**_TASK_OPTS)
def generate_visuals(payload: dict) -> dict:
    ctx = JobContext.from_dict(payload)
    _advance(ctx.job_id, "generate_visuals")

    background = get_background_generator()
    still = artifact_path(ctx.job_id, "background_still.png")
    background.generate_still(ctx.theme, still)
    ctx.background_still_path = str(still)
    _record(ctx.job_id, "generate_visuals", "background_still", still)

    loop = artifact_path(ctx.job_id, "background_loop.mp4")
    background.animate(still, loop)
    ctx.background_loop_path = str(loop)
    _record(ctx.job_id, "generate_visuals", "background_loop", loop)

    portrait = _resolve_portrait(
        ctx.job_id, ctx.character_ref, ctx.character_image, "character_portrait"
    )
    ctx.character_portrait_path = str(portrait)
    _record(ctx.job_id, "generate_visuals", "portrait", portrait)

    # Backup character (trio) — generated/used the same way.
    if ctx.backup_character_ref or ctx.backup_character_image:
        backup = _resolve_portrait(
            ctx.job_id,
            ctx.backup_character_ref or "",
            ctx.backup_character_image,
            "backup_portrait",
        )
        ctx.backup_portrait_path = str(backup)
        _record(ctx.job_id, "generate_visuals", "backup_portrait", backup)
    return ctx.to_dict()


def _render_character(portrait: Path, audio: Path, job_id: str, name: str) -> Path:
    """Animate the portrait to the audio, then (if matting is on) cut it out.

    Two modes (``settings.MOTION_MODE``):
      * ``lipsync`` — OmniHuman on the static portrait (accurate mouth).
      * ``motion_first`` — Kling animates the body, then a video lip-sync maps
        the mouth onto the moving clip (chaotic motion, mouth approximate).
    Matting (BiRefNet) then segments the subject so any colour / thin limb
    stays solid. Returns the composite-ready clip (alpha when matted).
    """
    raw = artifact_path(job_id, f"{name}_raw.mp4")
    if settings.MOTION_MODE == "motion_first":
        moving = artifact_path(job_id, f"{name}_motion.mp4")
        get_animator().animate(portrait, moving)
        # Kling caps at KLING_DURATION; clip the audio to match before syncing.
        capped = artifact_path(job_id, f"{name}_audio.mp3")
        clip_audio(audio, capped, 0.0, float(settings.KLING_DURATION))
        get_video_lip_syncer().sync_video(moving, capped, raw)
    else:
        get_lip_syncer().sync(portrait, audio, raw)

    if not settings.MATTING_ENABLED:
        return raw
    return get_matter().matte(raw, artifact_path(job_id, f"{name}.webm"))


@shared_task(**_TASK_OPTS)
def lipsync_render(payload: dict) -> dict:
    ctx = JobContext.from_dict(payload)
    _advance(ctx.job_id, "lipsync_render")
    # Talking-head models sync best on the isolated vocal stem; body-animating
    # models (OmniHuman) need the full mix to dance to the beat.
    if settings.LIPSYNC_AUDIO_SOURCE == "mix":
        sync_audio = _require_path(ctx.song_normalized_path)
    else:
        sync_audio = _require_path(ctx.vocal_stem_path)

    out = _render_character(
        _require_path(ctx.character_portrait_path), sync_audio, ctx.job_id, "character_lipsync"
    )
    ctx.lipsync_path = str(out)
    _record(ctx.job_id, "lipsync_render", "lipsync", out)

    # Backup character (trio) — synced to the same audio so they're in step.
    if ctx.backup_portrait_path:
        backup_out = _render_character(
            _require_path(ctx.backup_portrait_path), sync_audio, ctx.job_id, "backup_lipsync"
        )
        ctx.backup_lipsync_path = str(backup_out)
        _record(ctx.job_id, "lipsync_render", "backup_lipsync", backup_out)
    return ctx.to_dict()


@shared_task(**_TASK_OPTS)
def compose_video(payload: dict) -> dict:
    ctx = JobContext.from_dict(payload)
    _advance(ctx.job_id, "compose_video")
    out = artifact_path(ctx.job_id, "output.mp4")
    captions = Path(ctx.captions_path) if ctx.captions_path else None
    backup_clip = Path(ctx.backup_lipsync_path) if ctx.backup_lipsync_path else None
    audio = _require_path(ctx.song_normalized_path)
    # Detect the beat grid so compose can pulse the zoom on every beat. Disabled
    # (or any failure) leaves beat_period at 0, which compose treats as off.
    if settings.KINETIC_ENABLED:
        beat_period, beat_offset = detect_beat_period(Path(audio))
        beat_zoom = settings.BEAT_ZOOM
        shake_px = settings.KINETIC_SHAKE_PX
        base_zoom = settings.KINETIC_BASE_ZOOM
    else:
        beat_period = beat_offset = 0.0
        beat_zoom = base_zoom = 1.0
        shake_px = 0.0
    compose_final(
        background_loop=_require_path(ctx.background_loop_path),
        character_clip=_require_path(ctx.lipsync_path),
        backup_clip=backup_clip,
        matted=settings.MATTING_ENABLED,
        audio=audio,
        captions=captions,
        out_path=out,
        intro_zoom=settings.INTRO_PUNCH_ZOOM,
        intro_seconds=settings.INTRO_PUNCH_SECONDS,
        beat_zoom=beat_zoom,
        beat_period=beat_period,
        beat_offset=beat_offset,
        beat_decay=settings.BEAT_DECAY_SECONDS,
        base_zoom=base_zoom,
        shake_px=shake_px,
    )
    ctx.output_path = str(out)
    Job.objects.filter(pk=ctx.job_id).update(output_path=str(out))
    _record(ctx.job_id, "compose_video", "output", out)
    return ctx.to_dict()


@shared_task(**_TASK_OPTS)
def deliver_telegram(payload: dict) -> dict:
    ctx = JobContext.from_dict(payload)
    _advance(ctx.job_id, "deliver_telegram")
    caption = _build_caption(ctx.theme, ctx.lyrics)
    ctx.suggested_caption = caption

    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if token and chat_id:
        send_video(_require_path(ctx.output_path), caption, bot_token=token, chat_id=chat_id)
        ctx.delivered = True
        logger.info("Delivered job %s to Telegram.", ctx.job_id)
    else:
        # Not an error: with Telegram unconfigured the render still succeeds;
        # the operator picks it up from media/jobs/<id>/output.mp4.
        logger.info(
            "Telegram not configured; job %s output at %s (delivery skipped).",
            ctx.job_id,
            ctx.output_path,
        )

    Job.objects.filter(pk=ctx.job_id).update(
        status=Job.Status.DELIVERED,
        suggested_caption=caption,
    )
    return ctx.to_dict()
