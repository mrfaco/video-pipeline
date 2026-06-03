"""REST views — list/create jobs and fetch one by id.

Auth and permission are enforced project-wide by ``REST_FRAMEWORK`` settings
(``ApiKeyAuthentication`` + ``IsAuthenticated``), so these views don't repeat
them. Creating a job snapshots a preset and kicks off its pipeline run.

Error paths raise DRF exceptions (``ValidationError`` -> 400, ``NotFound`` ->
404) rather than catching-and-returning a fallback ``Response``: that keeps
the failure loud and is rendered by DRF as the same ``{"detail": ...}`` shape.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.serializers import JobSerializer
from jobs.models import Job
from jobs.orchestrator import run_job
from jobs.presets import PresetError, create_job_from_preset

DEFAULT_LIMIT = 50
MIN_LIMIT = 1
MAX_LIMIT = 200


class JobsView(APIView):
    """``GET`` recent jobs; ``POST`` to create + run a new one."""

    def get(self, request: Request) -> Response:
        limit = DEFAULT_LIMIT
        raw_limit = request.query_params.get("limit")
        if raw_limit is not None:
            if not raw_limit.lstrip("-").isdigit():
                raise ValidationError({"detail": "limit must be an integer."})
            limit = max(MIN_LIMIT, min(MAX_LIMIT, int(raw_limit)))

        jobs = Job.objects.all()[:limit]
        return Response(JobSerializer(jobs, many=True).data)

    def post(self, request: Request) -> Response:
        preset = request.data.get("preset")
        if not preset:
            raise ValidationError({"detail": "preset is required."})
        sync = bool(request.data.get("sync", False))

        try:
            job = create_job_from_preset(preset)
        except PresetError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        run_job(job, eager=sync)
        job.refresh_from_db()
        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class JobDetailView(APIView):
    """``GET`` one job by its UUID primary key."""

    def get(self, request: Request, pk: str) -> Response:
        job = Job.objects.filter(pk=pk).first()
        if job is None:
            raise NotFound("Job not found.")
        return Response(JobSerializer(job).data)
