"""Admin surface for API keys — themed with django-unfold.

The raw token is never stored, so the admin shows only the hash (read-only)
and lifecycle timestamps. Mint new keys via the ``create_api_key`` command.
"""

from __future__ import annotations

from django.contrib import admin
from unfold.admin import ModelAdmin

from api.models import ApiKey


@admin.register(ApiKey)
class ApiKeyAdmin(ModelAdmin):
    list_display = ("id", "user", "label", "created_at", "last_used_at", "revoked_at")
    readonly_fields = ("key_hash", "created_at", "last_used_at")
    search_fields = ("label", "user__username")
