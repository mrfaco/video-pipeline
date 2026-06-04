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
from compose.ffmpeg import (
    compose_final,
    compose_scene,
    composite_window,
    crop_window,
    loop_seamless,
    probe_dimensions,
)
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
    get_scene_generator,
    get_video_lip_syncer,
    get_vocal_separator,
)
from providers.replicate import EmptyTranscriptionError
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
        mode=job.mode,
        character_ref=job.character_ref,
        lyrics=(job.lyrics or None),
        # Closeup needs known lyrics to caption; dance auto-transcribes the song
        # with WhisperX (no lyrics needed), so it always captions when enabled.
        enable_captions=bool(settings.ENABLE_CAPTIONS and (job.lyrics or job.mode == "dance")),
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
    if ctx.mode == "dance" and not ctx.enable_captions:
        # Dance has no lip-sync; it only needs the stem to caption (clean vocals
        # transcribe far better than a full mix). No captions => skip Demucs.
        return ctx.to_dict()
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
    # Closeup transcribes the FULL song guided by its known lyrics (WhisperX's
    # VAD is unreliable on a short clip but nails the full mix with a prompt).
    # Dance has no lyrics, so transcribe the isolated vocal stem instead — clean
    # vocals transcribe far better than a music-laden full mix.
    transcribe_source = (
        ctx.vocal_stem_path if (ctx.mode == "dance" and ctx.vocal_stem_path) else ctx.song_full_path
    )
    full_words = artifact_path(ctx.job_id, "word_timestamps_full.json")
    try:
        get_caption_aligner().align(_require_path(transcribe_source), ctx.lyrics, full_words)
    except EmptyTranscriptionError:  # allow: suppress-exception
        # Instrumental / untranscribable audio yields no words — captions are
        # best-effort, so skip them and still deliver the video rather than
        # failing an otherwise-finished render.
        logger.warning("No transcribable words for job %s; rendering without captions.", ctx.job_id)
        return ctx.to_dict()

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

    if ctx.mode == "dance":
        # One integrated scene still (girl + environment), then animate it with
        # the high-motion model. No greenscreen, no portrait, no separate bg.
        prompt = settings.SCENE_PROMPT_TEMPLATE.format(theme=ctx.theme)
        still = artifact_path(ctx.job_id, "scene_still.png")
        get_scene_generator().generate(prompt, still)
        _record(ctx.job_id, "generate_visuals", "scene_still", still)
        clip = artifact_path(ctx.job_id, "scene_motion.mp4")
        # Seamless loop: end the dance on the same frame it started, so the
        # motion returns home and the platform's loop has no visible seam.
        tail = still if settings.LOOP_SEAMLESS_ENABLED else None
        get_animator().animate(still, clip, tail_image_path=tail)
        ctx.scene_clip_path = str(clip)
        _record(ctx.job_id, "generate_visuals", "scene", clip)
        return ctx.to_dict()

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
        if settings.RESYNC_LAYER_ENABLED:
            _resync_head(moving, capped, raw, job_id, name)
        else:
            get_video_lip_syncer().sync_video(moving, capped, raw)
    else:
        get_lip_syncer().sync(portrait, audio, raw)

    if not settings.MATTING_ENABLED:
        return raw
    return get_matter().matte(raw, artifact_path(job_id, f"{name}.webm"))


def _resync_head(moving: Path, audio: Path, raw: Path, job_id: str, name: str) -> Path:
    """Lip-sync a full-body Kling clip by correcting only the head region.

    The face is tiny in a full-body shot, so a whole-clip sync barely moves the
    mouth. Instead: crop the head window, upscale it so the face is large,
    lip-sync that crop, then paste it back over the moving body (only the mouth
    changed, so the feathered blend is seamless). Writes ``raw`` and returns it.
    """
    w_frame, h_frame = probe_dimensions(moving)

    def _even(v: float) -> int:
        return int(v) - (int(v) % 2)

    x = _even(w_frame * settings.RESYNC_WIN_X_FRAC)
    y = _even(h_frame * settings.RESYNC_WIN_Y_FRAC)
    w = _even(w_frame * settings.RESYNC_WIN_W_FRAC)
    h = _even(h_frame * settings.RESYNC_WIN_H_FRAC)

    head = artifact_path(job_id, f"{name}_head.mp4")
    crop_window(moving, head, x=x, y=y, w=w, h=h, out_h=settings.RESYNC_UPSCALE_H)
    head_synced = artifact_path(job_id, f"{name}_head_synced.mp4")
    get_video_lip_syncer().sync_video(head, audio, head_synced)
    composite_window(
        moving, head_synced, raw, x=x, y=y, w=w, h=h, feather=settings.RESYNC_FEATHER_PX
    )
    return raw


@shared_task(**_TASK_OPTS)
def lipsync_render(payload: dict) -> dict:
    ctx = JobContext.from_dict(payload)
    _advance(ctx.job_id, "lipsync_render")
    if ctx.mode == "dance":
        # Dance mode leaves lip-sync alone — the scene clip is the final motion.
        return ctx.to_dict()
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
    # Dance loops via Kling's end-frame (start == end) already. Closeup can't
    # drive that, so compose into a pre-wrap file and dissolve the tail back over
    # the head for a seamless loop.
    loop_closeup = ctx.mode != "dance" and settings.LOOP_SEAMLESS_ENABLED
    compose_target = artifact_path(ctx.job_id, "prewrap.mp4") if loop_closeup else out
    if ctx.mode == "dance":
        # Single integrated scene clip — no overlay, no matte, no lip-sync layer.
        compose_scene(
            scene_clip=_require_path(ctx.scene_clip_path),
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
    else:
        compose_final(
            background_loop=_require_path(ctx.background_loop_path),
            character_clip=_require_path(ctx.lipsync_path),
            backup_clip=backup_clip,
            matted=settings.MATTING_ENABLED,
            audio=audio,
            captions=captions,
            out_path=compose_target,
            intro_zoom=settings.INTRO_PUNCH_ZOOM,
            intro_seconds=settings.INTRO_PUNCH_SECONDS,
            beat_zoom=beat_zoom,
            beat_period=beat_period,
            beat_offset=beat_offset,
            beat_decay=settings.BEAT_DECAY_SECONDS,
            base_zoom=base_zoom,
            shake_px=shake_px,
            boss_height_frac=settings.TRIO_BOSS_HEIGHT_FRAC,
            flank_height_frac=settings.TRIO_FLANK_HEIGHT_FRAC,
            flank_y_frac=settings.TRIO_FLANK_Y_FRAC,
            flank_peek_px=settings.TRIO_FLANK_PEEK_PX,
        )
    if loop_closeup:
        loop_seamless(compose_target, out, settings.LOOP_CROSSFADE_SECONDS)
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
