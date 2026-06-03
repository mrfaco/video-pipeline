"""Tests for the DRF API surface — auth, list/create/detail of jobs.

Auth uses real ``ApiKey`` rows. The create path monkeypatches
``api.views.run_job`` to a no-op so no real pipeline (ffmpeg, providers) runs;
we only assert the Job row was created and the pipeline was kicked off once.
``MEDIA_ROOT`` is redirected to a tmp dir so the song copy lands there.
"""

from __future__ import annotations

import uuid

import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import ApiKey, generate_key, hash_key
from jobs.models import Job

PRESET = "presets/demo.yaml"


@pytest.fixture
def user(db) -> User:
    return User.objects.create_user(username="apitester", password="x")


@pytest.fixture
def auth_client(user) -> tuple[APIClient, str]:
    raw, _ = generate_key(user, label="test")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client, raw


@pytest.mark.django_db
def test_hash_key_matches_stored_hash(user):
    raw, key = generate_key(user)
    assert key.key_hash == hash_key(raw)


@pytest.mark.django_db
def test_list_jobs_unauthenticated_rejected():
    client = APIClient()
    resp = client.get("/api/v1/jobs/")
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_list_jobs_authenticated_ok(auth_client):
    client, _ = auth_client
    resp = client.get("/api/v1/jobs/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.django_db
def test_create_job_runs_pipeline(auth_client, monkeypatch, tmp_path):
    client, _ = auth_client
    calls = []
    monkeypatch.setattr("api.views.run_job", lambda job, eager=False: calls.append((job, eager)))

    with override_settings(MEDIA_ROOT=tmp_path):
        resp = client.post("/api/v1/jobs/", {"preset": PRESET}, format="json")

    assert resp.status_code in (201, 202)
    assert Job.objects.count() == 1
    job = Job.objects.get()
    assert len(calls) == 1
    assert calls[0][0].pk == job.pk
    assert resp.json()["id"] == str(job.pk)


@pytest.mark.django_db
def test_create_job_bad_preset_returns_400(auth_client, tmp_path):
    client, _ = auth_client
    with override_settings(MEDIA_ROOT=tmp_path):
        resp = client.post(
            "/api/v1/jobs/", {"preset": "presets/does-not-exist.yaml"}, format="json"
        )
    assert resp.status_code == 400
    assert "detail" in resp.json()
    assert Job.objects.count() == 0


@pytest.mark.django_db
def test_create_job_missing_preset_returns_400(auth_client):
    client, _ = auth_client
    resp = client.post("/api/v1/jobs/", {}, format="json")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_revoked_key_rejected(user):
    raw, key = generate_key(user)
    ApiKey.objects.filter(pk=key.pk).update(revoked_at=timezone.now())
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    resp = client.get("/api/v1/jobs/")
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_unknown_key_rejected():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer totally-bogus-token")
    resp = client.get("/api/v1/jobs/")
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_job_detail_ok(auth_client):
    client, _ = auth_client
    job = Job.objects.create(theme="t", character_ref="c")
    resp = client.get(f"/api/v1/jobs/{job.pk}/")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(job.pk)


@pytest.mark.django_db
def test_job_detail_missing_returns_404(auth_client):
    client, _ = auth_client
    resp = client.get(f"/api/v1/jobs/{uuid.uuid4()}/")
    assert resp.status_code == 404
    assert "detail" in resp.json()
