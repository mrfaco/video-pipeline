"""Pipeline orchestration — wire the seven stages into a Celery chain.

The chain passes one ``ctx`` dict from link to link. ``prepare_assets`` takes
the job id; every later stage takes (and returns) the ctx. Failure bookkeeping
is handled by ``stages.base.PipelineTask.on_failure`` on each stage, so the
orchestrator only has to kick the chain off and mark the job RUNNING.
"""

from __future__ import annotations

from celery import chain
from celery.result import AsyncResult

from jobs.models import Job
from stages.tasks import (
    align_captions,
    compose_video,
    deliver_telegram,
    generate_visuals,
    lipsync_render,
    prepare_assets,
    separate_vocals,
)


def build_chain(job_id: str) -> chain:
    """The full pipeline signature for one job."""
    return chain(
        prepare_assets.s(job_id),
        separate_vocals.s(),
        align_captions.s(),
        generate_visuals.s(),
        lipsync_render.s(),
        compose_video.s(),
        deliver_telegram.s(),
    )


def run_job(job: Job, *, eager: bool = False) -> AsyncResult:
    """Mark ``job`` RUNNING and run its pipeline chain.

    With ``eager=False`` (default) the chain is dispatched to the Celery worker
    via the broker. With ``eager=True`` the whole chain runs inline in this
    process via ``.apply()`` — no broker/worker needed. This is how the
    ``run_job --sync`` command and the test suite drive the pipeline; it is
    deterministic and doesn't depend on toggling ``task_always_eager`` (which
    Celery snapshots at app finalize and won't honor when mutated later).
    """
    job.status = Job.Status.RUNNING
    job.current_stage = "prepare_assets"
    job.failed_stage = ""
    job.error_detail = ""
    job.save(update_fields=["status", "current_stage", "failed_stage", "error_detail"])

    signature = build_chain(job.job_id)
    if eager:
        return signature.apply()
    result = signature.apply_async()
    Job.objects.filter(pk=job.pk).update(chain_task_id=result.id)
    return result
