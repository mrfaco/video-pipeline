"""Preset loading + Job creation.

A preset is a YAML file describing one job: the song (audio + optional
lyrics), the theme prompt, and the locked character's identity asset. Loading
validates the shape and that referenced files exist (loud failures — a typo'd
path must not silently produce an empty video), then snapshots everything into
a ``Job`` row so a later edit to the preset file can't mutate an in-flight run.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from django.conf import settings

from core.audio import TimeRangeError, parse_timerange
from core.storage import job_dir
from jobs.models import Job


class PresetError(ValueError):
    """A preset is missing required fields or references missing files."""


def _require(mapping: dict, key: str, where: str) -> object:
    if key not in mapping or mapping[key] in (None, ""):
        raise PresetError(f"Preset {where} is missing required key {key!r}.")
    return mapping[key]


def load_preset(path: str | Path) -> dict:
    """Parse + validate a preset YAML, returning a normalized dict.

    Keys: ``song.audio`` (path), ``song.lyrics`` (optional str), ``theme``
    (str), ``character.identity_asset`` (path).
    """
    preset_path = Path(path)
    if not preset_path.is_file():
        raise PresetError(f"Preset file not found: {preset_path}")
    data = yaml.safe_load(preset_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PresetError(f"Preset {preset_path} did not parse to a mapping.")

    song = _require(data, "song", str(preset_path))
    if not isinstance(song, dict):
        raise PresetError("Preset 'song' must be a mapping with an 'audio' or 'source' key.")
    theme = _require(data, "theme", str(preset_path))
    character = _require(data, "character", str(preset_path))
    if not isinstance(character, dict):
        raise PresetError("Preset 'character' needs 'identity_asset' or 'description'.")

    # Exactly one of a local file (``audio``) or a fetchable URL/query
    # (``source``). ``source`` is downloaded later, in prepare_assets.
    audio = song.get("audio")
    source = song.get("source")
    if bool(audio) == bool(source):
        raise PresetError(
            "Preset 'song' needs exactly one of 'audio' (path) or 'source' (url/query)."
        )

    audio_path: Path | None = None
    if audio:
        audio_path = (settings.BASE_DIR / str(audio)).resolve()
        if not audio_path.is_file():
            raise PresetError(f"Song audio not found: {audio_path}")

    # Character identity: exactly one of an image file (identity_asset, used
    # for fake mode / a future InstantID lock) or a text description (used as
    # the FLUX prompt in real mode). character_ref carries whichever.
    identity_asset = character.get("identity_asset")
    description = character.get("description")
    if bool(identity_asset) == bool(description):
        raise PresetError(
            "Preset 'character' needs exactly one of 'identity_asset' (file) "
            "or 'description' (text)."
        )
    if identity_asset:
        identity_path = (settings.BASE_DIR / str(identity_asset)).resolve()
        if not identity_path.is_file():
            raise PresetError(f"Character identity asset not found: {identity_path}")
        character_ref = str(identity_path)
    else:
        character_ref = str(description).strip()

    clip = str(song.get("clip")).strip() if song.get("clip") else ""
    if clip:
        # Validate the range now so a bad timestamp fails at submit, not mid-run.
        try:
            parse_timerange(clip)
        except TimeRangeError as exc:
            raise PresetError(str(exc)) from exc

    return {
        "audio_path": audio_path,
        "audio_source": (str(source).strip() if source else ""),
        "clip": clip,
        "lyrics": (song.get("lyrics") or "").strip(),
        "theme": str(theme).strip(),
        "character_ref": character_ref,
    }


def create_job_from_preset(preset_path: str | Path) -> Job:
    """Build a ``Job`` from a preset.

    A local ``song.audio`` is copied into the job dir now (self-contained run);
    a ``song.source`` (url/query) is stored and downloaded later by
    prepare_assets, so job creation stays cheap and offline.
    """
    preset = load_preset(preset_path)
    job = Job.objects.create(
        preset_name=str(preset_path),
        theme=preset["theme"],
        lyrics=preset["lyrics"],
        character_ref=preset["character_ref"],
        song_source=preset["audio_source"],
        song_clip=preset["clip"],
    )
    src = preset["audio_path"]
    if src is not None:
        # Copy the local song into the job dir so the run is immune to the
        # source file moving/changing later.
        dest = job_dir(job.job_id) / f"source{src.suffix}"
        shutil.copyfile(src, dest)
        job.song_filename = str(dest)
        job.save(update_fields=["song_filename"])
    return job
