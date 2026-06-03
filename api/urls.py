"""API URL routing — mounted at /api/v1/ from config/urls.py."""

from __future__ import annotations

from django.urls import path

from api.views import JobDetailView, JobsView

urlpatterns = [
    path("jobs/", JobsView.as_view(), name="api-jobs"),
    path("jobs/<uuid:pk>/", JobDetailView.as_view(), name="api-job-detail"),
]
