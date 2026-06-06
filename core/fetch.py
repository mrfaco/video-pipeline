"""Fetch the guide-track audio from a URL or a name/artist search.

A preset can give ``song.source`` (a URL, or a plain "title artist" query)
instead of a local ``song.audio`` path. We resolve it with ``yt-dlp``: a query
becomes a ``ytsearch1:`` lookup, a URL is downloaded directly, and either way
the bestaudio stream is extracted to mp3 (via ffmpeg, already on PATH).

The downloaded audio is only ever a **guide track** — muted when the clip is
posted, with TikTok's licensed in-app sound added at upload time — so it never
ships publicly. Failures are loud: a download error raises, never returns a
silent empty file (AGENTS.md §1).
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

# yt-dlp on TikTok/YouTube can hit transient rate-limits; retry a few times
# before failing the run.
_FETCH_RETRIES = 3
_FETCH_RETRY_WAIT_S = 5.0


class AudioFetchError(RuntimeError):
    """yt-dlp could not resolve or download the requested audio."""


class VideoFetchError(RuntimeError):
    """yt-dlp could not resolve/download the requested video, or a local
    driving-video path does not exist."""


def _is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def fetch_audio(source: str, out_path: Path) -> Path:
    """Download ``source`` to ``out_path`` (an .mp3), returning the file.

    ``source`` is a URL or a free-text search query ("Blinding Lights The
    Weeknd"). ``out_path`` should end in ``.mp3``; yt-dlp writes the extracted
    audio there.
    """
    if not source:
        raise AudioFetchError("Empty song source; nothing to fetch.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    target = source if _is_url(source) else f"ytsearch1:{source}"
    # yt-dlp fills %(ext)s with the final container (mp3 after extraction).
    template = str(out_path.with_suffix("")) + ".%(ext)s"
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--extract-audio",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "0",
        "--output",
        template,
        target,
    ]
    for attempt in range(_FETCH_RETRIES):
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            break
        except subprocess.CalledProcessError as exc:  # allow: suppress-exception
            # Retry transient rate-limits; the final attempt raises loudly.
            if attempt == _FETCH_RETRIES - 1:
                stderr = exc.stderr.decode("utf-8", "replace") if exc.stderr else ""
                raise AudioFetchError(f"yt-dlp failed for {source!r}: {stderr[-500:]}") from exc
            time.sleep(_FETCH_RETRY_WAIT_S)

    produced = out_path.with_suffix(".mp3")
    if not produced.exists():
        raise AudioFetchError(f"yt-dlp reported success but {produced} is missing.")
    return produced


def fetch_video(source: str, out_path: Path) -> Path:
    """Resolve a driving video to ``out_path`` (an .mp4), returning the file.

    A URL is downloaded with yt-dlp (best mp4, audio included — it is stripped
    later in normalize_video). A non-URL is treated as a local file path and
    copied through (used by the offline tests and any pre-downloaded clip).
    """
    if not source:
        raise VideoFetchError("Empty drive source; nothing to fetch.")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not _is_url(source):
        local = Path(source)
        if not local.is_file():
            raise VideoFetchError(f"Drive video not found: {local}")
        import shutil  # noqa: PLC0415

        shutil.copyfile(local, out_path)
        return out_path

    template = str(out_path.with_suffix("")) + ".%(ext)s"
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "-f",
        "bv*+ba/b",
        "--merge-output-format",
        "mp4",
        "--output",
        template,
        source,
    ]
    for attempt in range(_FETCH_RETRIES):
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            break
        except subprocess.CalledProcessError as exc:  # allow: suppress-exception
            if attempt == _FETCH_RETRIES - 1:
                stderr = exc.stderr.decode("utf-8", "replace") if exc.stderr else ""
                raise VideoFetchError(f"yt-dlp failed for {source!r}: {stderr[-500:]}") from exc
            time.sleep(_FETCH_RETRY_WAIT_S)

    produced = out_path.with_suffix(".mp4")
    if not produced.exists():
        raise VideoFetchError(f"yt-dlp reported success but {produced} is missing.")
    return produced
