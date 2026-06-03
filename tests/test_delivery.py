"""Tests for delivery.telegram.send_video — no real network is hit.

The outbound POST is monkeypatched to avoid new dependencies (respx is not
installed) and to keep the suite offline.
"""

from __future__ import annotations

import httpx
import pytest

from delivery.telegram import TelegramDeliveryError, send_video

BOT_TOKEN = "123456:ABCDEF"
CHAT_ID = "987654"


class _FakeResponse:
    """Minimal stand-in for httpx.Response used by send_video."""

    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def video_file(tmp_path):
    path = tmp_path / "final.mp4"
    path.write_bytes(b"\x00\x01fake-mp4-bytes")
    return path


def test_send_video_success(monkeypatch, video_file):
    captured: dict = {}

    def fake_post(url, *, data, files, timeout):
        captured["url"] = url
        captured["data"] = data
        captured["files"] = files
        captured["timeout"] = timeout
        return _FakeResponse(200, {"ok": True, "result": {"message_id": 42}})

    monkeypatch.setattr(httpx, "post", fake_post)

    result = send_video(
        video_file,
        "neon nights",
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
    )

    assert result == {"message_id": 42}
    assert BOT_TOKEN in captured["url"]
    assert captured["url"].endswith("/sendVideo")
    assert captured["data"]["chat_id"] == CHAT_ID
    assert captured["data"]["caption"] == "neon nights"
    assert "video" in captured["files"]


def test_empty_bot_token_raises_without_network(monkeypatch, video_file):
    def boom(*args, **kwargs):
        raise AssertionError("network must not be touched")

    monkeypatch.setattr(httpx, "post", boom)

    with pytest.raises(TelegramDeliveryError):
        send_video(video_file, "cap", bot_token="", chat_id=CHAT_ID)


def test_empty_chat_id_raises_without_network(monkeypatch, video_file):
    def boom(*args, **kwargs):
        raise AssertionError("network must not be touched")

    monkeypatch.setattr(httpx, "post", boom)

    with pytest.raises(TelegramDeliveryError):
        send_video(video_file, "cap", bot_token=BOT_TOKEN, chat_id="")


def test_ok_false_response_raises(monkeypatch, video_file):
    def fake_post(url, *, data, files, timeout):
        return _FakeResponse(200, {"ok": False, "description": "Bad Request"})

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(TelegramDeliveryError):
        send_video(video_file, "cap", bot_token=BOT_TOKEN, chat_id=CHAT_ID)


def test_non_2xx_response_raises(monkeypatch, video_file):
    def fake_post(url, *, data, files, timeout):
        return _FakeResponse(500, {"ok": False, "description": "server error"})

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(TelegramDeliveryError):
        send_video(video_file, "cap", bot_token=BOT_TOKEN, chat_id=CHAT_ID)
