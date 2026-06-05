"""The ``ctx`` object that flows through the Celery pipeline chain.

Every stage receives a ``JobContext`` (serialized to a plain dict over the
Celery wire), fills in the artifact path(s) it produced, and returns it. The
context is the single source of truth for "where are this job's files" and is
deliberately JSON-serializable so it survives the broker round-trip.

Artifacts are all namespaced under ``media/jobs/<job_id>/`` — see
``core.storage``. Paths are stored as strings (``str(Path)``) so the model
serializes cleanly to JSON; convert back with ``pathlib.Path`` at use sites.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# Bump when the shape of JobContext changes (AGENTS.md §11 schema versioning).
SCHEMA_VERSION = 6


class JobContext(BaseModel):
    """State + artifact paths carried between pipeline stages.

    Inputs are set by ``prepare_assets``; every later stage adds its own
    artifact field. Optional fields are ``None`` until the stage that
    produces them has run, which makes the context safe to log at any point
    and lets idempotent stages detect already-done work.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    job_id: str

    # --- Inputs (from the preset, resolved by prepare_assets) ---
    theme: str
    character_ref: str
    lyrics: str | None = None
    enable_captions: bool = True
    # Pipeline mode: "dance" (integrated scene-gen + high-motion Kling, no
    # lip-sync) or "closeup" (Hedra singer + matte + side characters).
    mode: str = "dance"
    # Optional scroll-stop hook/title burned at the top for the whole video
    # (e.g. "POV: ..."). None = no hook.
    hook: str | None = None
    # A ready-made greenscreen portrait to use as-is (preset ``character.image``),
    # skipping portrait generation. None means generate from ``character_ref``.
    character_image: str | None = None
    # Optional second character: when set, the pipeline renders it too and
    # compose lays out the viral TRIO (boss + two flanking backups). None = solo.
    backup_character_ref: str | None = None
    backup_character_image: str | None = None
    backup_portrait_path: str | None = None
    backup_lipsync_path: str | None = None
    # Absolute path on disk to the source song (already copied into the job dir).
    song_path: str

    # --- prepare_assets ---
    # The clip used by every downstream stage (demucs, lip-sync, compose). When
    # the preset gives no clip, this is the whole (normalized) song.
    song_normalized_path: str | None = None
    # The full normalized song, kept for caption transcription: WhisperX's VAD
    # is unreliable on a short isolated clip but transcribes the full track
    # cleanly, so align_captions runs on this and windows the words to the clip.
    song_full_path: str | None = None
    # The clip window within the full song, in seconds (clip_end_s == 0 means
    # "no clip — use the whole song's words").
    clip_start_s: float = 0.0
    clip_end_s: float = 0.0

    # --- separate_vocals (Demucs) ---
    vocal_stem_path: str | None = None

    # --- align_captions (WhisperX) ---
    word_timestamps_path: str | None = None
    captions_path: str | None = None

    # --- generate_visuals (fal) ---
    background_still_path: str | None = None
    background_loop_path: str | None = None
    character_portrait_path: str | None = None
    # dance mode: the single integrated scene clip (girl + environment animated
    # together); used in place of the background/portrait/lipsync layers.
    scene_clip_path: str | None = None

    # --- lipsync_render ---
    lipsync_path: str | None = None

    # --- compose_video (ffmpeg) ---
    output_path: str | None = None

    # --- deliver_telegram ---
    suggested_caption: str | None = None
    delivered: bool = False

    # Set by the error callback when a stage raises, so the failure
    # notification can name which stage died.
    failed_stage: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> JobContext:
        """Rehydrate from the dict Celery handed the task."""
        return cls.model_validate(data)

    def to_dict(self) -> dict:
        """Serialize for the next task in the chain (JSON-safe)."""
        return self.model_dump(mode="json")
