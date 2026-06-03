"""Transport for posting a finished video to Telegram via the Bot API.

Pure delivery: this module knows how to upload a file to ``sendVideo`` and
nothing about how the caption is composed (the stage owns that). Failures are
loud — an empty token/chat_id, a non-2xx status, or a non-``ok`` body all
raise ``TelegramDeliveryError`` rather than returning a partial result.
"""

from __future__ import annotations

from pathlib import Path

import httpx

# Telegram caps video upload time; uploads can be large, so allow generously.
_UPLOAD_TIMEOUT_SECONDS = 120.0


class TelegramDeliveryError(RuntimeError):
    """Raised when the Telegram ``sendVideo`` call cannot be completed cleanly."""


def send_video(
    video_path: Path,
    caption: str,
    *,
    bot_token: str,
    chat_id: str,
) -> dict:
    """POST ``video_path`` to Telegram ``sendVideo`` and return the ``result`` dict.

    Raises ``TelegramDeliveryError`` if ``bot_token`` or ``chat_id`` is empty
    (before any network call), if the HTTP status is not 2xx, or if the JSON
    body is not ``{"ok": true, ...}``.
    """
    if not bot_token:
        raise TelegramDeliveryError("bot_token is empty; cannot call Telegram.")
    if not chat_id:
        raise TelegramDeliveryError("chat_id is empty; cannot call Telegram.")

    url = f"https://api.telegram.org/bot{bot_token}/sendVideo"
    data = {"chat_id": chat_id, "caption": caption}

    with video_path.open("rb") as video_file:
        files = {"video": (video_path.name, video_file)}
        try:
            response = httpx.post(
                url,
                data=data,
                files=files,
                timeout=_UPLOAD_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise TelegramDeliveryError(f"Telegram request failed: {exc}") from exc

    if not response.is_success:
        raise TelegramDeliveryError(
            f"Telegram sendVideo returned HTTP {response.status_code}: {response.text}"
        )

    body = response.json()
    if not body.get("ok"):
        raise TelegramDeliveryError(f"Telegram sendVideo not ok: {body}")

    return body["result"]


def send_message(text: str, *, bot_token: str, chat_id: str) -> dict:
    """POST a plain-text message to Telegram ``sendMessage``.

    Used for failure notices (no media). Same loud-failure contract as
    ``send_video``.
    """
    if not bot_token:
        raise TelegramDeliveryError("bot_token is empty; cannot call Telegram.")
    if not chat_id:
        raise TelegramDeliveryError("chat_id is empty; cannot call Telegram.")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        response = httpx.post(
            url,
            data={"chat_id": chat_id, "text": text},
            timeout=_UPLOAD_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise TelegramDeliveryError(f"Telegram request failed: {exc}") from exc

    if not response.is_success:
        raise TelegramDeliveryError(
            f"Telegram sendMessage returned HTTP {response.status_code}: {response.text}"
        )

    body = response.json()
    if not body.get("ok"):
        raise TelegramDeliveryError(f"Telegram sendMessage not ok: {body}")

    return body["result"]
