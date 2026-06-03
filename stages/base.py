"""Shared task base + small helpers for the pipeline stages.

``PipelineTask.on_failure`` is the single place that records a job failure:
when a stage's retries are exhausted, it flips the ``Job`` to FAILED, names
the stage that died, and best-effort notifies Telegram. Recording happens
here (not in the stage bodies) so every stage gets identical failure handling
for free, and so a stage body can stay a thin happy-path.
"""

from __future__ import annotations

import logging

from celery import Task

logger = logging.getLogger(__name__)


def extract_job_id(args: tuple) -> str | None:
    """Pull the job id out of a task's positional args.

    ``prepare_assets`` is called with the job id string; every later stage is
    called with the ``ctx`` dict (which carries ``job_id``).
    """
    if not args:
        return None
    first = args[0]
    if isinstance(first, str):
        return first
    if isinstance(first, dict):
        return first.get("job_id")
    return None


def short_stage_name(task_name: str) -> str:
    """``stages.tasks.separate_vocals`` -> ``separate_vocals``."""
    return task_name.rsplit(".", 1)[-1]


class PipelineTask(Task):
    """Base task that records terminal failures onto the ``Job`` row."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # noqa: ANN001
        # Deferred to avoid importing Django models at worker import time.
        from jobs.models import Job  # noqa: PLC0415

        job_id = extract_job_id(args)
        stage = short_stage_name(self.name)
        if job_id is None:
            logger.error("Stage %s failed but no job_id could be extracted", stage)
            return
        Job.objects.filter(pk=job_id).update(
            status=Job.Status.FAILED,
            failed_stage=stage,
            error_detail=str(exc),
        )
        logger.error("Job %s failed at stage %s: %s", job_id, stage, exc)
        self._notify_failure(job_id, stage, exc)

    def _notify_failure(self, job_id: str, stage: str, exc: Exception) -> None:
        from django.conf import settings  # noqa: PLC0415

        token = settings.TELEGRAM_BOT_TOKEN
        chat_id = settings.TELEGRAM_CHAT_ID
        if not (token and chat_id):
            return
        # A failure to *notify* must never mask the original stage failure —
        # this is the rare, intentional suppression the discipline marker is for.
        from delivery.telegram import send_message  # noqa: PLC0415

        try:
            send_message(
                f"❌ brainrot job {job_id} failed at stage `{stage}`:\n{exc}",
                bot_token=token,
                chat_id=chat_id,
            )
        except Exception:  # noqa: BLE001  # allow: suppress-exception
            logger.exception("Could not send Telegram failure notice for job %s", job_id)
