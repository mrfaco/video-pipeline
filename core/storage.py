"""Filesystem layout for job artifacts.

Everything a job produces lives under ``MEDIA_ROOT/jobs/<job_id>/``. Keeping
all paths funnelled through these helpers means a job's entire footprint is a
single directory — trivial to inspect, archive, or delete — and that
artifacts are namespaced by ``job_id`` (AGENTS.md idempotency note).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings


def media_root() -> Path:
    return Path(settings.MEDIA_ROOT)


def job_dir(job_id: str) -> Path:
    """Return (creating if needed) the directory holding this job's artifacts."""
    path = media_root() / "jobs" / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def artifact_path(job_id: str, name: str) -> Path:
    """Path to a named artifact inside the job dir, e.g. ``vocal_stem.wav``.

    Does not create the file — only resolves where it should go. The parent
    job dir is ensured to exist.
    """
    return job_dir(job_id) / name
