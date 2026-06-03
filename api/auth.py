"""Bearer-key authentication for the REST API.

Reads ``Authorization: Bearer <key>``, hashes the presented token, and looks
up the matching ``ApiKey``. Anything wrong with a *present* credential
(malformed header, unknown/revoked key, inactive user) raises
``AuthenticationFailed`` loudly — we never fall back to anonymous on a bad
key. A missing or non-Bearer header returns ``None`` so the request stays
unauthenticated and ``IsAuthenticated`` rejects it with 403.
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from api.models import ApiKey, hash_key


class ApiKeyAuthentication(BaseAuthentication):
    """Authenticate a request from its ``Authorization: Bearer`` header."""

    keyword = "Bearer"

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header:
            return None
        parts = header.split()
        if parts[0] != self.keyword:
            return None
        if len(parts) != 2:
            raise AuthenticationFailed("Malformed Authorization header.")

        raw = parts[1]
        try:
            key = ApiKey.objects.select_related("user").get(key_hash=hash_key(raw))
        except ApiKey.DoesNotExist as exc:
            raise AuthenticationFailed("Invalid API key.") from exc

        if key.revoked_at is not None:
            raise AuthenticationFailed("API key has been revoked.")
        if not key.user.is_active:
            raise AuthenticationFailed("User is inactive.")

        ApiKey.objects.filter(pk=key.pk).update(last_used_at=timezone.now())
        return key.user, key

    def authenticate_header(self, request: Request) -> str:
        return self.keyword
