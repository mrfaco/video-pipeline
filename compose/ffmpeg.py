"""Composite the final 9:16 video with real ffmpeg.

Two passes shelling out to ffmpeg (``subprocess.run(..., check=True)`` — a
non-zero exit must surface, never a silently-broken render; AGENTS.md §1):

1. ``_make_boomerang`` turns the short background loop into a seamless
   forward+reverse clip so ``-stream_loop`` has no visible seam.
2. ``compose_final`` stream-loops that boomerang to outlast the audio,
   scales/crops it to ``width``x``height``, overlays the chromakeyed character
   clip scaled to fit and centered, optionally burns the ``.ass`` captions, and
   muxes the audio as the guide track with ``-shortest``.

Compose takes paths in, writes a file, returns the path — no DB, no ``ctx``
(AGENTS.md §5).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_VIDEO_ENCODE = [
    "-c:v",
    "libx264",
    "-pix_fmt",
    "yuv420p",
    "-movflags",
    "+faststart",
]


def _run(cmd: list[str]) -> None:
    """Run an ffmpeg command, raising with stderr attached on a non-zero exit."""
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", "replace") if exc.stderr else ""
        message = f"ffmpeg failed (exit {exc.returncode}): {' '.join(cmd)}\n{stderr}"
        raise subprocess.CalledProcessError(
            exc.returncode, exc.cmd, output=exc.output, stderr=message
        ) from exc


def _probe_duration(path: Path) -> float:
    """Return the audio/video duration in seconds via ffprobe."""
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(out.stdout.strip())


def _make_boomerang(source: Path, out_path: Path) -> Path:
    """Write a forward+reverse (boomerang) copy of ``source`` for seamless looping."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-filter_complex",
        "[0:v]split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0[v]",
        "-map",
        "[v]",
        "-an",
        *_VIDEO_ENCODE,
        str(out_path),
    ]
    _run(cmd)
    return out_path


def _escape_subtitles_path(path: Path) -> str:
    """Escape an ass path for use inside the ffmpeg ``subtitles=`` filter arg."""
    text = str(path)
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("'", "\\'")
    text = text.replace("[", "\\[").replace("]", "\\]")
    return text.replace(",", "\\,")


# Trio layout (boss + two flanking backups), as fractions of the canvas height.
_BOSS_HEIGHT_FRAC = 0.64
_FLANK_HEIGHT_FRAC = 0.41
_FLANK_PEEK_PX = 40  # how far the flanks sit beyond the side edges
_BOTTOM_MARGIN_PX = 30


def compose_final(
    *,
    background_loop: Path,
    character_clip: Path,
    audio: Path,
    captions: Path | None,
    out_path: Path,
    backup_clip: Path | None = None,
    width: int = 1080,
    height: int = 1920,
    chroma_color: str = "0x00FF00",
    intro_zoom: float = 1.0,
    intro_seconds: float = 0.4,
    pulse_zoom: float = 1.0,
    pulse_interval: float = 1.5,
    pulse_decay: float = 0.28,
) -> Path:
    """Render the final 9:16 mp4 and return ``out_path``.

    With ``backup_clip`` set, composes the viral TRIO: a large center "boss"
    (``character_clip``) flanked by two smaller backups (``backup_clip``, the
    right one mirrored). Without it, a single centered character.

    Two scroll-stop motion effects, both visual-only (centered crop+rescale, so
    audio/lip-sync timing is never touched):

    * ``intro_zoom`` > 1.0 — a one-time opening punch that settles to 1.0x over
      ``intro_seconds``.
    * ``pulse_zoom`` > 1.0 — a recurring beat-pulse every ``pulse_interval``
      seconds (decaying over ``pulse_decay``) so the edit never goes static.

    Each is disabled at <= 1.0.

    Raises ``subprocess.CalledProcessError`` if any ffmpeg pass exits non-zero
    (e.g. a missing input file).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    boomerang = out_path.with_name(f"{out_path.stem}_boomerang.mp4")
    _make_boomerang(Path(background_loop), boomerang)

    key = f"chromakey={chroma_color}:0.30:0.10"
    bg_chain = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1[bg]"
    )

    # Inputs: bg, boss, [backup], audio. The boss/backup are OmniHuman renders
    # of the same audio, so they match its length; the bg is stream-looped.
    inputs = ["-stream_loop", "-1", "-i", str(boomerang), "-i", str(character_clip)]
    if backup_clip is not None:
        inputs += ["-i", str(backup_clip)]
    inputs += ["-i", str(audio)]
    audio_idx = 3 if backup_clip is not None else 2

    if backup_clip is not None:
        boss_h = int(height * _BOSS_HEIGHT_FRAC)
        flank_h = int(height * _FLANK_HEIGHT_FRAC)
        fg = (
            f"[2:v]{key},split[bk1][bk2];"
            f"[bk1]scale=-1:{flank_h}[lf];"
            f"[bk2]scale=-1:{flank_h},hflip[rf];"
            f"[1:v]{key},scale=-1:{boss_h}[boss];"
            f"[bg][lf]overlay=x=-{_FLANK_PEEK_PX}:y=H-h-{_BOTTOM_MARGIN_PX}[t1];"
            f"[t1][rf]overlay=x=W-w+{_FLANK_PEEK_PX}:y=H-h-{_BOTTOM_MARGIN_PX}[t2];"
            f"[t2][boss]overlay=x=(W-w)/2:y=H-h-10[comp]"
        )
    else:
        fg = (
            f"[1:v]{key},scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[comp]"
        )

    filter_complex = f"{bg_chain};{fg}"
    if captions is not None:
        escaped = _escape_subtitles_path(Path(captions))
        filter_complex += f";[comp]subtitles='{escaped}'[pre]"
    else:
        filter_complex += ";[comp]null[pre]"

    # Build the per-frame zoom factor from whichever motion effects are on.
    # Centered crop by iw/zoom (crop centers by default), then rescale. Commas
    # inside the expressions are quoted so the filtergraph parser keeps them.
    zoom_terms = []
    if intro_zoom > 1.0:
        zoom_terms.append(
            f"if(lt(t,{intro_seconds}),{intro_zoom}-({intro_zoom}-1)*t/{intro_seconds},1)"
        )
    if pulse_zoom > 1.0:
        # Spikes to pulse_zoom at each interval, decays to 1.0 over pulse_decay.
        zoom_terms.append(f"(1+({pulse_zoom}-1)*max(0,1-mod(t,{pulse_interval})/{pulse_decay}))")

    if zoom_terms:
        z = zoom_terms[0] if len(zoom_terms) == 1 else f"max({','.join(zoom_terms)})"
        filter_complex += f";[pre]crop=w='iw/({z})':h='ih/({z})',scale={width}:{height}[v]"
    else:
        filter_complex += ";[pre]null[v]"

    # Bound the output to the audio length explicitly. ``-shortest`` alone is
    # unreliable with an infinite ``-stream_loop`` background — it overshoots,
    # leaving the lip-sync running past the audio (a tail desync). ``-t`` makes
    # the duration deterministic so lips, captions, and audio stay locked.
    duration = _probe_duration(Path(audio))

    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        f"{audio_idx}:a",
        "-t",
        f"{duration:.3f}",
        *_VIDEO_ENCODE,
        "-c:a",
        "aac",
        str(out_path),
    ]
    _run(cmd)
    return out_path
