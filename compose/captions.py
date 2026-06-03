"""Build karaoke-style ``.ass`` subtitles from WhisperX word timestamps.

Reads the ``word_segments`` array a WhisperX aligner writes (shape documented
in ``docs/BUILD_CONTRACT.md``) and emits a libass ``.ass`` file: each word
appears at its own start/end timestamp, centered horizontally and anchored in
the lower third, in a large bold DejaVu Sans face that reads on a 9:16 phone
screen. ``compose.ffmpeg`` burns the result in with the ``subtitles`` filter.

Providers/compose never touch the DB or ``ctx`` — a path in, a written file
out, the path returned (AGENTS.md §5).
"""

from __future__ import annotations

import json
from pathlib import Path

# Outline + shadow keep the text legible over arbitrary background video.
_FONT_NAME = "DejaVu Sans"
_FONT_SIZE = 96
_OUTLINE = 4
_SHADOW = 2
# Distance from the bottom edge (script units) — keeps captions in the lower
# third, clear of TikTok's own UI chrome at the very bottom.
_MARGIN_V = 320


def _format_ass_time(seconds: float) -> str:
    """Convert seconds to the ``H:MM:SS.cs`` (centisecond) ass timestamp form."""
    if seconds < 0:
        seconds = 0.0
    total_cs = round(seconds * 100)
    cs = total_cs % 100
    total_seconds = total_cs // 100
    secs = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _escape_text(text: str) -> str:
    """Escape characters special to the ass event text field."""
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def window_words(src_path: Path, out_path: Path, start_s: float, end_s: float) -> Path:
    """Keep only the words inside ``[start_s, end_s)`` and rebase to the clip.

    WhisperX is run on the full song (its VAD is unreliable on a short
    excerpt), so its word timestamps are in song time. The rendered video is
    just the clip, so we drop words outside the window and shift the survivors
    by ``-start_s`` into clip time. A word is kept if it overlaps the window at
    all; its times are clamped into ``[0, end_s - start_s]``.
    """
    data = json.loads(Path(src_path).read_text(encoding="utf-8"))
    length = end_s - start_s
    kept: list[dict] = []
    for word in data.get("word_segments", []):
        if "start" not in word or "end" not in word:
            continue
        w_start, w_end = float(word["start"]), float(word["end"])
        if w_end <= start_s or w_start >= end_s:
            continue
        kept.append(
            {
                "word": word["word"],
                "start": max(0.0, w_start - start_s),
                "end": min(length, w_end - start_s),
            }
        )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"language": data.get("language", "en"), "word_segments": kept}),
        encoding="utf-8",
    )
    return out_path


def build_ass(
    word_timestamps_path: Path,
    out_path: Path,
    *,
    width: int = 1080,
    height: int = 1920,
) -> Path:
    """Write a karaoke ``.ass`` from a WhisperX word-timestamps JSON.

    One word is shown at a time at its ``start``/``end``, centered low. Returns
    ``out_path``.
    """
    data = json.loads(Path(word_timestamps_path).read_text(encoding="utf-8"))
    word_segments = data["word_segments"]

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # &H00FFFFFF = white fill, &H00000000 = black outline/shadow.
        # Alignment 2 = bottom-center; MarginV lifts it into the lower third.
        f"Style: Karaoke,{_FONT_NAME},{_FONT_SIZE},&H00FFFFFF,&H000000FF,"
        f"&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{_OUTLINE},{_SHADOW},"
        f"2,40,40,{_MARGIN_V},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
    )

    lines = [header]
    for segment in word_segments:
        start = _format_ass_time(float(segment["start"]))
        end = _format_ass_time(float(segment["end"]))
        text = _escape_text(str(segment["word"]).strip())
        lines.append(f"Dialogue: 0,{start},{end},Karaoke,,0,0,0,,{text}\n")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(lines), encoding="utf-8")
    return out_path
