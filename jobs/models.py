"""Persistent job state.

``Job`` is the durable record of one pipeline run — its inputs, current
status, and where the finished video landed. ``Artifact`` rows are the audit
trail of intermediate files each stage produced (vocal stem, captions,
background loop, portrait, lip-sync clip, final mp4), so a finished or failed
job can be inspected without trawling the filesystem.

The job's ``id`` is a UUID and doubles as the ``job_id`` used to namespace
artifacts on disk (``media/jobs/<id>/`` — see ``core.storage``).
"""

from __future__ import annotations

import uuid

from django.db import models


class Job(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- Input snapshot (frozen at submit time; the preset file may change) ---
    preset_name = models.CharField(max_length=200, blank=True)
    # Pipeline mode: "dance" (scene-gen + high-motion, no lip-sync) or "closeup"
    # (Hedra singer + matte + side characters).
    mode = models.CharField(max_length=16, default="dance")
    theme = models.TextField()
    lyrics = models.TextField(blank=True)
    character_ref = models.CharField(max_length=500)
    # A ready-made greenscreen portrait to use as-is (preset character.image),
    # instead of generating one. Copied into the job dir at creation.
    character_image = models.CharField(max_length=1000, blank=True)
    # Optional backup character (preset `backup:`) → trio layout. Same shape as
    # the main character: a text ref and/or a ready-made image.
    backup_character_ref = models.CharField(max_length=500, blank=True)
    backup_character_image = models.CharField(max_length=1000, blank=True)
    # Local path to the copied/fetched source song (set once it's on disk).
    song_filename = models.CharField(max_length=500, blank=True)
    # A URL or "title artist" search query, when the preset gives song.source
    # instead of a local file. Downloaded into the job dir by prepare_assets.
    song_source = models.CharField(max_length=1000, blank=True)
    # Optional "start-end" range (e.g. "0:45-1:05") to trim the song to a hook
    # before rendering — keeps lip-sync render time/cost down. Applied in
    # prepare_assets after the song is on disk.
    song_clip = models.CharField(max_length=40, blank=True)

    # --- Lifecycle ---
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    # Name of the stage currently running (or the last one that ran).
    current_stage = models.CharField(max_length=50, blank=True)
    # Set when a stage raises — names the stage that died.
    failed_stage = models.CharField(max_length=50, blank=True)
    error_detail = models.TextField(blank=True)

    # --- Outputs ---
    output_path = models.CharField(max_length=1000, blank=True)
    suggested_caption = models.TextField(blank=True)

    # Celery chain id for the run, so the admin/API can correlate to results.
    chain_task_id = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Job {self.id} ({self.status})"

    @property
    def job_id(self) -> str:
        """The string id used to namespace artifacts on disk."""
        return str(self.id)


class Artifact(models.Model):
    """One intermediate or final file produced by a stage."""

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="artifacts")
    # Which stage produced it (e.g. "separate_vocals").
    stage = models.CharField(max_length=50)
    # Logical kind (e.g. "vocal_stem", "captions", "background_loop",
    # "portrait", "lipsync", "output").
    kind = models.CharField(max_length=50)
    path = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.kind} for job {self.job_id}"
