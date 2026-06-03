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
