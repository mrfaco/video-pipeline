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


def probe_duration(path: Path) -> float:
    """Public wrapper: return a media file's duration in seconds via ffprobe."""
    return _probe_duration(Path(path))


def probe_dimensions(path: Path) -> tuple[int, int]:
    """Return the (width, height) of a video's first video stream via ffprobe."""
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    w, _, h = out.partition("x")
    return int(w), int(h)


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


def crop_window(
    video_in: Path, out_path: Path, *, x: int, y: int, w: int, h: int, out_h: int
) -> Path:
    """Crop a ``w``x``h`` rectangle at (``x``,``y``) and upscale it to ``out_h`` tall.

    The resync layer uses this to blow up the head region of a full-body clip so
    the face is large enough for a video lip-sync model to track and correct.
    Width follows the aspect (``-2`` keeps it even for yuv420p).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_in),
        "-vf",
        f"crop={w}:{h}:{x}:{y},scale=-2:{out_h}",
        "-an",
        *_VIDEO_ENCODE,
        str(out_path),
    ]
    _run(cmd)
    return out_path


def composite_window(
    base: Path, patch: Path, out_path: Path, *, x: int, y: int, w: int, h: int, feather: int = 40
) -> Path:
    """Overlay ``patch`` (the lip-synced head crop) back onto ``base`` at (``x``,``y``).

    ``patch`` is scaled back to ``w``x``h`` and blended through a static feathered
    alpha mask (opaque interior ramping to transparent over ``feather`` px at the
    edges) so the resampled window has no hard seam against the untouched frame.
    Only the mouth differs inside the window, so the blend is invisible.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # A static feather mask (same for every frame): white interior, edges ramping
    # to black over ``feather`` px, via distance-to-nearest-edge.
    mask = out_path.with_name(f"{out_path.stem}_feather.png")
    edge = f"min(min(X\\,{w}-X)\\,min(Y\\,{h}-Y))"
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=black:s={w}x{h}",
            "-vf",
            f"geq=lum='clip({edge}/{feather}\\,0\\,1)*255',format=gray",
            "-frames:v",
            "1",
            str(mask),
        ]
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(base),
        "-i",
        str(patch),
        "-i",
        str(mask),
        "-filter_complex",
        f"[1:v]scale={w}:{h}[p];[p][2:v]alphamerge[pa];[0:v][pa]overlay={x}:{y}[v]",
        "-map",
        "[v]",
        "-map",
        "0:a?",
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


def beat_cut_concat(
    clips: list[Path],
    out_path: Path,
    *,
    total_duration: float,
    beat_period: float,
    beat_offset: float,
    width: int = 1080,
    height: int = 1920,
) -> Path:
    """Hard-cut between ``clips`` on the beat grid into one ``total_duration`` clip.

    Splits the timeline into one roughly-equal segment per clip, snaps each cut
    point to the nearest beat (``mod(t-offset, period)`` zero), and takes that
    segment from the start of each clip. Every segment is scaled/padded to
    ``width``x``height`` at a constant fps so ``concat`` accepts them. Returns a
    video-only clip; ``compose_scene`` muxes the audio.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = len(clips)

    def _snap(t: float) -> float:
        if beat_period <= 0:
            return t
        return round((t - beat_offset) / beat_period) * beat_period + beat_offset

    # Cut boundaries: 0, snapped interior points, total. Keep them strictly
    # increasing so every segment has positive length.
    bounds = [0.0]
    for i in range(1, n):
        nxt = min(max(_snap(i * total_duration / n), bounds[-1] + 0.2), total_duration)
        bounds.append(nxt)
    bounds.append(total_duration)

    fit = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"
    )
    parts = []
    labels = ""
    for i in range(n):
        seg = bounds[i + 1] - bounds[i]
        parts.append(f"[{i}:v]trim=0:{seg:.3f},setpts=PTS-STARTPTS,{fit}[s{i}]")
        labels += f"[s{i}]"
    filtergraph = ";".join(parts) + f";{labels}concat=n={n}:v=1:a=0[v]"

    cmd = ["ffmpeg", "-y"]
    for clip in clips:
        cmd += ["-i", str(clip)]
    cmd += ["-filter_complex", filtergraph, "-map", "[v]", "-an", *_VIDEO_ENCODE, str(out_path)]
    _run(cmd)
    return out_path


def loop_seamless(src: Path, out_path: Path, duration: float = 0.4) -> Path:
    """Rewrite ``src`` so it loops seamlessly, dissolving the tail into the head.

    Crossfades the last ``duration`` seconds back over the first ``duration``
    seconds (video ``xfade`` + audio ``acrossfade``). The result is
    ``duration`` shorter and its first frame equals its last, so when a platform
    loops it there is no visible/audible seam. Clips too short to spare two
    crossfades are returned unchanged.
    """
    src = Path(src)
    out_path = Path(out_path)
    length = _probe_duration(src)
    if length <= 2 * duration:
        return src  # nothing to crossfade into
    out_path.parent.mkdir(parents=True, exist_ok=True)
    offset = length - 2 * duration
    d = f"{duration:.3f}"
    # Reorder both video and audio to start at +d, then dissolve the original
    # tail back over the original head (video xfade). xfade needs a constant
    # frame rate, so normalise with fps. Audio is reordered identically to stay
    # in sync; the visible video seam is what a loop reveals, and music tolerates
    # the wrap. The output's first frame equals its last → seamless on loop.
    filtergraph = (
        f"[0:v]split[v0][v1];"
        f"[v0]trim=start={d},setpts=PTS-STARTPTS,fps=30[vmain];"
        f"[v1]trim=duration={d},setpts=PTS-STARTPTS,fps=30[vhead];"
        f"[vmain][vhead]xfade=transition=fade:duration={d}:offset={offset:.3f}[vout];"
        f"[0:a]atrim=start={d},asetpts=PTS-STARTPTS[aout]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-filter_complex",
        filtergraph,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        *_VIDEO_ENCODE,
        "-c:a",
        "aac",
        str(out_path),
    ]
    _run(cmd)
    return out_path


def _kinetic_filter(
    in_label: str,
    out_label: str,
    *,
    width: int,
    height: int,
    intro_zoom: float,
    intro_seconds: float,
    beat_zoom: float,
    beat_period: float,
    beat_offset: float,
    beat_decay: float,
    base_zoom: float,
    shake_px: float,
) -> str:
    """Build a ``[in_label] -> [out_label]`` kinetic-camera filter fragment.

    A single ``zoompan`` re-evaluates ``on`` (the output frame index) every
    frame; a plain ``crop`` with ``t`` does NOT animate in this ffmpeg build, so
    zoompan is the only way to get a per-frame zoom. Commas inside the
    expressions are escaped so the filtergraph parser keeps them as function
    args. With every effect off this is a passthrough ``null``. Shared by
    ``compose_final`` and ``compose_scene``.
    """
    fps = 30
    t = f"on/{fps}"  # seconds, from the (fps-normalised) frame index

    # A continuous handheld jitter needs crop headroom or it shows black edges
    # at the frame border, so derive a minimum base zoom that keeps the shifted
    # crop window inside the source.
    eff_base = base_zoom
    if shake_px > 0.0:
        needed = 1.0 / (1.0 - 2.0 * shake_px / width)
        eff_base = max(eff_base, needed * 1.02)

    terms = []
    if eff_base > 1.0:
        terms.append(f"{eff_base:.4f}")
    if intro_zoom > 1.0:
        terms.append(
            f"if(lt({t}\\,{intro_seconds})\\,"
            f"{intro_zoom}-({intro_zoom}-1)*({t})/{intro_seconds}\\,1)"
        )
    if beat_zoom > 1.0 and beat_period > 0.0:
        # Spikes to beat_zoom on every beat, decaying to 1.0 over beat_decay.
        terms.append(
            f"1+({beat_zoom}-1)*max(0\\,1-mod({t}-{beat_offset}\\,{beat_period})/{beat_decay})"
        )

    if not terms:
        return f"[{in_label}]null[{out_label}]"

    z = terms[0]
    for term in terms[1:]:
        z = f"max({z}\\,{term})"  # ffmpeg max() is binary; nest for >2 terms
    if shake_px > 0.0:
        # Two incommensurate frequencies read as organic handheld drift.
        sx = f"+{shake_px}*sin(2*PI*{t}*5.3)"
        sy = f"+{shake_px}*sin(2*PI*{t}*7.1)"
    else:
        sx = sy = ""
    x = f"iw/2-(iw/zoom/2){sx}"
    y = f"ih/2-(ih/zoom/2){sy}"
    pf = f"{out_label}_pf"
    return (
        f"[{in_label}]fps={fps}[{pf}];"
        f"[{pf}]zoompan=z='{z}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps}[{out_label}]"
    )


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
    matted: bool = False,
    width: int = 1080,
    height: int = 1920,
    chroma_color: str = "0x00FF00",
    intro_zoom: float = 1.0,
    intro_seconds: float = 0.4,
    beat_zoom: float = 1.0,
    beat_period: float = 0.0,
    beat_offset: float = 0.0,
    beat_decay: float = 0.18,
    base_zoom: float = 1.0,
    shake_px: float = 0.0,
    boss_height_frac: float = _BOSS_HEIGHT_FRAC,
    flank_height_frac: float = _FLANK_HEIGHT_FRAC,
    flank_y_frac: float = -1.0,
    flank_peek_px: int = _FLANK_PEEK_PX,
    hook_captions: Path | None = None,
) -> Path:
    """Render the final 9:16 mp4 and return ``out_path``.

    With ``backup_clip`` set, composes the viral TRIO: a large center "boss"
    (``character_clip``) flanked by two smaller backups (``backup_clip``, the
    right one mirrored). Without it, a single centered character.

    The kinetic-camera pass (a single ``zoompan``, visual-only — audio/lip-sync
    timing is untouched):

    * ``intro_zoom`` > 1.0 — opening punch settling to 1.0x over ``intro_seconds``.
    * ``beat_zoom`` > 1.0 with ``beat_period`` > 0 — a zoom punch on every beat
      (decaying over ``beat_decay``), the period from audio beat detection.
    * ``base_zoom`` > 1.0 — a slight always-on crop giving the shake room.
    * ``shake_px`` > 0 — a continuous handheld camera jitter.

    All disabled at their <= defaults (then it's a passthrough).

    Raises ``subprocess.CalledProcessError`` if any ffmpeg pass exits non-zero.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    boomerang = out_path.with_name(f"{out_path.stem}_boomerang.mp4")
    _make_boomerang(Path(background_loop), boomerang)

    # Matted clips already carry alpha (subject cut out) — overlay them
    # directly. Un-matted clips are on a green screen and get chroma-keyed.
    key = "" if matted else f"chromakey={chroma_color}:0.30:0.10,"
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
        boss_h = int(height * boss_height_frac)
        flank_h = int(height * flank_height_frac)
        # Flanks: bottom-anchored by default (flank_y_frac < 0), or floated with
        # their vertical CENTRE at flank_y_frac of the canvas (e.g. moons in the
        # sky). flank_peek_px > 0 pushes them past the edge (half-body backups);
        # negative insets them fully on-screen (small round companions).
        if flank_y_frac < 0:
            flank_y = f"H-h-{_BOTTOM_MARGIN_PX}"
        else:
            flank_y = f"{int(height * flank_y_frac)}-h/2"
        fg = (
            f"[2:v]{key}split[bk1][bk2];"
            f"[bk1]scale=-1:{flank_h}[lf];"
            f"[bk2]scale=-1:{flank_h},hflip[rf];"
            f"[1:v]{key}scale=-1:{boss_h}[boss];"
            f"[bg][lf]overlay=x=-{flank_peek_px}:y={flank_y}[t1];"
            f"[t1][rf]overlay=x=W-w+{flank_peek_px}:y={flank_y}[t2];"
            f"[t2][boss]overlay=x=(W-w)/2:y=H-h-10[comp]"
        )
    else:
        fg = (
            f"[1:v]{key}scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[comp]"
        )

    filter_complex = f"{bg_chain};{fg}"
    if captions is not None:
        escaped = _escape_subtitles_path(Path(captions))
        filter_complex += f";[comp]subtitles='{escaped}'[pre]"
    else:
        filter_complex += ";[comp]null[pre]"

    # Kinetic-camera pass (shared with compose_scene): a single zoompan animating
    # the crop window per frame.
    filter_complex += ";" + _kinetic_filter(
        "pre",
        "v",
        width=width,
        height=height,
        intro_zoom=intro_zoom,
        intro_seconds=intro_seconds,
        beat_zoom=beat_zoom,
        beat_period=beat_period,
        beat_offset=beat_offset,
        beat_decay=beat_decay,
        base_zoom=base_zoom,
        shake_px=shake_px,
    )
    # Hook burned after the kinetic pass so the title stays stable on screen.
    video_label = "[v]"
    if hook_captions is not None:
        hook_esc = _escape_subtitles_path(Path(hook_captions))
        filter_complex += f";[v]subtitles='{hook_esc}'[vh]"
        video_label = "[vh]"

    # Bound the output explicitly (``-shortest`` is unreliable with an infinite
    # ``-stream_loop`` background — it overshoots). Use the shorter of the audio
    # and the character clip: in motion_first the Kling character clip is capped
    # to KLING_DURATION (< the song), so it bounds the video.
    duration = min(_probe_duration(Path(audio)), _probe_duration(Path(character_clip)))

    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        video_label,
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


def compose_scene(
    *,
    scene_clip: Path,
    audio: Path,
    captions: Path | None,
    out_path: Path,
    hook_captions: Path | None = None,
    width: int = 1080,
    height: int = 1920,
    intro_zoom: float = 1.0,
    intro_seconds: float = 0.4,
    beat_zoom: float = 1.0,
    beat_period: float = 0.0,
    beat_offset: float = 0.0,
    beat_decay: float = 0.18,
    base_zoom: float = 1.0,
    shake_px: float = 0.0,
) -> Path:
    """Dance-mode compose: a single integrated scene clip → final 9:16 mp4.

    Unlike ``compose_final`` there is no background loop, no character overlay,
    and no matte — the scene clip already contains the girl in her environment.
    Scale/pad it to ``width``x``height``, optionally burn ``captions``, apply the
    shared kinetic-camera pass, and mux the audio (bounded to the shorter of the
    two). Returns ``out_path``.

    Raises ``subprocess.CalledProcessError`` if ffmpeg exits non-zero.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Fit the scene (whatever the i2v aspect) into the canvas, padded + centered.
    chain = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1[scaled]"
    )
    if captions is not None:
        escaped = _escape_subtitles_path(Path(captions))
        chain += f";[scaled]subtitles='{escaped}'[pre]"
    else:
        chain += ";[scaled]null[pre]"
    chain += ";" + _kinetic_filter(
        "pre",
        "v",
        width=width,
        height=height,
        intro_zoom=intro_zoom,
        intro_seconds=intro_seconds,
        beat_zoom=beat_zoom,
        beat_period=beat_period,
        beat_offset=beat_offset,
        beat_decay=beat_decay,
        base_zoom=base_zoom,
        shake_px=shake_px,
    )
    # The hook is burned AFTER the kinetic pass so the title stays rock-stable
    # (never zooms or shakes with the camera).
    video_label = "[v]"
    if hook_captions is not None:
        hook_esc = _escape_subtitles_path(Path(hook_captions))
        chain += f";[v]subtitles='{hook_esc}'[vh]"
        video_label = "[vh]"

    duration = min(_probe_duration(Path(audio)), _probe_duration(Path(scene_clip)))
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(scene_clip),
        "-i",
        str(audio),
        "-filter_complex",
        chain,
        "-map",
        video_label,
        "-map",
        "1:a",
        "-t",
        f"{duration:.3f}",
        *_VIDEO_ENCODE,
        "-c:a",
        "aac",
        str(out_path),
    ]
    _run(cmd)
    return out_path
