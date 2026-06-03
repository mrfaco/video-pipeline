"""API authentication tokens.

An ``ApiKey`` is a Bearer credential for the REST API. We never store the raw
token — only its SHA-256 hash — so a database leak can't be replayed against
the API. The raw token is shown exactly once at creation (see
``generate_key`` and the ``create_api_key`` management command).
"""

from __future__ import annotations

import hashlib
import secrets

from django.contrib.auth.models import User
from django.db import models


def hash_key(raw: str) -> str:
    """Return the SHA-256 hex digest used to store/look up a raw token."""
    return hashlib.sha256(raw.encode()).hexdigest()


class ApiKey(models.Model):
    """A hashed Bearer token tied to a Django user."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_keys")
    key_hash = models.CharField(max_length=64, unique=True, db_index=True)
    label = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ApiKey {self.label or self.pk} for {self.user}"


def generate_key(user: User, label: str = "") -> tuple[str, ApiKey]:
    """Mint a new token for ``user``.

    Returns ``(raw_token, api_key)``. The raw token is only available here —
    only its hash is persisted, so it cannot be recovered later.
    """
    raw = secrets.token_urlsafe(32)
    api_key = ApiKey.objects.create(user=user, key_hash=hash_key(raw), label=label)
    return raw, api_key
