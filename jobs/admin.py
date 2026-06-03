"""Admin surface for jobs — themed with django-unfold.

Operators create a ``Job`` (or run a preset via the API / ``run_job`` command)
and use the "Run pipeline" action to dispatch it. Artifacts are shown inline so
a finished or failed run can be inspected without touching the filesystem.
"""

from __future__ import annotations

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest
from unfold.admin import ModelAdmin, TabularInline

from jobs.models import Artifact, Job
from jobs.orchestrator import run_job


class ArtifactInline(TabularInline):
    model = Artifact
    extra = 0
    can_delete = False
    fields = ("stage", "kind", "path", "created_at")
    readonly_fields = ("stage", "kind", "path", "created_at")

    def has_add_permission(self, request: HttpRequest, obj: Job | None = None) -> bool:
        return False


@admin.register(Job)
class JobAdmin(ModelAdmin):
    list_display = ("id", "status", "current_stage", "theme_short", "created_at")
    list_filter = ("status",)
    search_fields = ("id", "theme", "preset_name")
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "status",
        "current_stage",
        "failed_stage",
        "error_detail",
        "output_path",
        "suggested_caption",
        "chain_task_id",
    )
    inlines = (ArtifactInline,)
    actions = ("run_pipeline",)

    @admin.display(description="Theme")
    def theme_short(self, obj: Job) -> str:
        return (obj.theme[:60] + "…") if len(obj.theme) > 60 else obj.theme

    @admin.action(description="Run pipeline")
    def run_pipeline(self, request: HttpRequest, queryset: QuerySet[Job]) -> None:
        dispatched = 0
        for job in queryset:
            if job.status == Job.Status.RUNNING:
                self.message_user(
                    request, f"Job {job.id} is already running; skipped.", level=messages.WARNING
                )
                continue
            run_job(job)
            dispatched += 1
        if dispatched:
            self.message_user(request, f"Dispatched {dispatched} job(s).", level=messages.SUCCESS)


@admin.register(Artifact)
class ArtifactAdmin(ModelAdmin):
    list_display = ("id", "job", "stage", "kind", "created_at")
    list_filter = ("stage", "kind")
    search_fields = ("job__id", "path")
