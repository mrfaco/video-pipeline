"""``manage.py run_job <preset.yaml>`` — create a Job from a preset and run it.

By default the chain is dispatched to the Celery worker (async). Pass
``--sync`` to run the whole pipeline inline in this process (no worker/broker
needed) and block until the output mp4 exists — handy for a one-off on the Pi
or in dev.
"""

from __future__ import annotations

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from jobs.orchestrator import run_job
from jobs.presets import PresetError, create_job_from_preset


class Command(BaseCommand):
    help = "Create a pipeline job from a preset YAML and run it."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("preset", help="Path to the preset YAML (e.g. presets/demo.yaml)")
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run the pipeline inline (eager), blocking until done — no worker needed.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            job = create_job_from_preset(options["preset"])
        except PresetError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Created job {job.id}"))

        # ``--sync`` runs the whole chain inline via .apply() (no worker/broker).
        run_job(job, eager=options["sync"])
        job.refresh_from_db()

        if options["sync"]:
            self.stdout.write(
                self.style.SUCCESS(f"Finished: status={job.status} output={job.output_path}")
            )
        else:
            self.stdout.write(f"Dispatched job {job.id} (status={job.status}).")
