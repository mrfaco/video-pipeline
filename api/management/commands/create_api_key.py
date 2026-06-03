"""``manage.py create_api_key <username> [--label L]``.

Mints a Bearer token for an existing user and prints the RAW token once.
Only the hash is stored, so the token cannot be recovered later — copy it now.
"""

from __future__ import annotations

from argparse import ArgumentParser
from typing import Any

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from api.models import generate_key


class Command(BaseCommand):
    help = "Create an API key for a user and print the raw token (shown once)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("username", help="Username to mint the key for.")
        parser.add_argument("--label", default="", help="Optional human label for the key.")

    def handle(self, *args: Any, **options: Any) -> None:
        username = options["username"]
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise CommandError(f"No user with username {username!r}.") from exc

        raw, api_key = generate_key(user, label=options["label"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Created API key {api_key.pk} for {username}. "
                "Store this token now — it cannot be recovered:"
            )
        )
        self.stdout.write(raw)
