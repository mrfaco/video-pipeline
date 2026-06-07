"""``manage.py render_transition <preset.yaml>`` — render a two-look glow-up.

A ``mode: transition`` preset holds a locked character performing a ``before``
and an ``after`` look (different outfit + setting). This generates each (scene
still → Kling), hard-cuts them together (the cut is the glow-up reveal), then
composes the hook + seamless loop + de-glow grade. Mute — the operator adds the
trend sound at post (a transition is scored at post anyway).

Standalone like ``describe_trend`` (not a Celery chain): it calls the providers
and compose directly and writes the final mp4. ``PROVIDER_MODE=fake`` runs it
end-to-end on fixtures; ``real`` spends on scene-gen + Kling (two of each).
"""

from __future__ import annotations

import shutil
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from compose.captions import build_hook_ass
from compose.ffmpeg import apply_realism_grade, compose_scene, concat_cuts, loop_seamless
from jobs.presets import PresetError, load_transition_preset
from providers.base import get_animator, get_scene_generator


class Command(BaseCommand):
    help = "Render a two-look before→after transition (glow-up) from a transition preset."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("preset", help="Path to a mode: transition preset YAML.")
        parser.add_argument(
            "--out", help="Output mp4 path (default: media/transitions/<name>/final.mp4)."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            preset = load_transition_preset(options["preset"])
        except PresetError as exc:
            raise CommandError(str(exc)) from exc

        name = Path(options["preset"]).stem
        out = Path(options["out"]) if options.get("out") else (
            Path(settings.MEDIA_ROOT) / "transitions" / name / "final.mp4"
        )
        work = out.parent
        work.mkdir(parents=True, exist_ok=True)

        scene_gen = get_scene_generator()
        animator = get_animator()
        reference = Path(preset["character_image"]) if preset["character_image"] else None

        segments = []
        for label in ("before", "after"):
            look = preset[label]
            prompt = settings.TRANSITION_SCENE_PROMPT.format(
                style=look["style"], theme=look["theme"], framing=look["framing"]
            )
            still = work / f"{label}_still.png"
            scene_gen.generate(
                prompt, still, reference_image=reference,
                lora=preset["character_lora"], trigger=preset["character_trigger"],
            )
            clip = work / f"{label}_clip.mp4"
            animator.animate(still, clip, prompt=look["motion"], cfg_scale=settings.DANCE_KLING_CFG)
            segments.append((clip, look["start"], look["duration"]))
            self.stdout.write(f"{label}: still + clip done")

        stitched = concat_cuts(segments, work / "stitched.mp4")
        hook = build_hook_ass(preset["hook"], work / "hook.ass") if preset["hook"] else None
        prewrap = compose_scene(
            scene_clip=stitched, audio=None, captions=None,
            hook_captions=hook, out_path=work / "prewrap.mp4",
        )
        looped = loop_seamless(prewrap, work / "looped.mp4", settings.LOOP_CROSSFADE_SECONDS)
        if settings.REALISM_GRADE_ENABLED:
            apply_realism_grade(looped, out, settings.REALISM_GRADE_FILTER)
        else:
            shutil.copyfile(looped, out)

        self.stdout.write(self.style.SUCCESS(f"Wrote transition: {out}"))
        self.stdout.write("Mute — add the trend sound at post.")
