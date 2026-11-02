"""Tests for the local voice pipeline.

The actual STT/TTS/wake engines are optional heavy dependencies, so these tests
mock the provider layer and exercise the manager, session state machine, and
WebSocket protocol.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocket

from ray.config import get_settings
from ray.core.events import DoneEvent
from ray.voice.base import AudioChunk, SpeechRequest, Transcript, VoiceError, WakeEvent
from ray.voice.manager import VoiceManager, VoiceSession
from ray.voice.providers.local import LocalSpeechToText, LocalTextToSpeech, LocalWakeWord
from tests.conftest import TEST_TOKEN


@pytest.fixture
def fake_manager() -> VoiceManager:
    """A manager whose providers are all mocks so no model files are needed."""
    manager = VoiceManager(get_settings())
    manager.stt = MagicMock(spec=LocalSpeechToText)
    manager.tts = MagicMock(spec=LocalTextToSpeech)
    manager.wake = MagicMock(spec=LocalWakeWord)
    return manager


@pytest.fixture
def mock_websocket() -> AsyncMock:
    """A fake WebSocket that records every JSON message sent."""
    ws = AsyncMock(spec=WebSocket)
    ws.send_json = AsyncMock()
    ws.accept = AsyncMock()
    return ws


def _messages_from(ws: AsyncMock) -> list[dict]:
    """Return JSON payloads passed to send_json."""
    return [call.args[0] for call in ws.send_json.call_args_list]


async def _aiter(*items):
    for item in items:
        yield item


async def test_voice_manager_info_without_optional_dependencies() -> None:
    """On a clean install the local stack reports not-ready with a helpful detail."""
    manager = VoiceManager(get_settings())
    info = manager.info()
    assert info.stt_backend == "browser"
    assert info.tts_backend == "browser"
    assert info.wake_words == ["ray", "jarvis"]
    assert info.local_ready is False
    assert "stt" in info.local_detail or "tts" in info.local_detail


async def test_voice_session_full_turn(
    fake_manager: VoiceManager, mock_websocket: AsyncMock
) -> None:
    """User audio is transcribed, sent to Ray, and the spoken answer is streamed."""
    fake_manager.settings.stt_backend = "local"
    fake_manager.settings.tts_backend = "local"
    fake_manager.settings.wake_word_enabled = False

    fake_manager.stt.transcribe = AsyncMock(return_value=Transcript(text="hello", confidence=1.0))

    async def _fake_synthesize(request: SpeechRequest) -> AsyncIterator[AudioChunk]:
        yield AudioChunk(data=b"audio", sample_rate=22_050, is_final=False)
        yield AudioChunk(data=b"", sample_rate=22_050, is_final=True)

    fake_manager.tts.synthesize = _fake_synthesize

    done_event = DoneEvent(
        conversation_id=__import__("uuid").uuid4(),
        message_id=__import__("uuid").uuid4(),
        agent_name="executive",
        speech_text="hi",
        duration_ms=100,
    )

    with patch("ray.voice.manager.Orchestrator") as mock_orch:
        instance = MagicMock()
        instance.run = MagicMock(return_value=_aiter(done_event))
        mock_orch.return_value = instance

        session = VoiceSession(fake_manager, __import__("uuid").uuid4())
        await session._handle_bytes(mock_websocket, b"pcm")
        await session._handle_text(mock_websocket, json.dumps({"type": "stop"}))
        assert session.current_task is not None
        await session.current_task

    messages = _messages_from(mock_websocket)
    types = [m["type"] for m in messages]
    assert "state" in types
    assert "transcript" in types
    assert "response_text" in types
    assert "audio" in types

    transcript_messages = [m for m in messages if m["type"] == "transcript"]
    assert transcript_messages[-1]["text"] == "hello"

    audio_messages = [m for m in messages if m["type"] == "audio"]
    assert any(m.get("is_final") for m in audio_messages)


async def test_voice_session_barge_in(
    fake_manager: VoiceManager, mock_websocket: AsyncMock
) -> None:
    """A barge message cancels the current turn and returns to listening."""
    session = VoiceSession(fake_manager, __import__("uuid").uuid4())
    session.state = "speaking"
    session.current_task = asyncio.create_task(asyncio.sleep(10))

    await session._handle_text(mock_websocket, json.dumps({"type": "barge"}))

    assert session.current_task is None or session.current_task.cancelled()
    assert session.state == "listening"


@pytest.mark.parametrize("armed", [False, True])
async def test_stt_decode_error_reaches_client_and_resets_state(
    fake_manager, mock_websocket, armed
):
    fake_manager.settings.wake_word_enabled = armed
    fake_manager.stt.transcribe = AsyncMock(
        side_effect=VoiceError("ffmpeg is required to decode browser audio")
    )
    session = VoiceSession(fake_manager, __import__("uuid").uuid4())
    session.audio_buffer.extend(b"OggSencoded")
    await session._handle_text(mock_websocket, json.dumps({"type": "stop"}))
    messages = _messages_from(mock_websocket)
    assert {"type": "error", "message": "ffmpeg is required to decode browser audio"} in messages
    assert session.state == ("armed" if armed else "idle")
    assert session.current_task is None


async def test_voice_session_wake_word_arms_listening(
    fake_manager: VoiceManager, mock_websocket: AsyncMock
) -> None:
    """In armed mode, audio is fed to the wake-word detector until it fires."""
    fake_manager.settings.wake_word_enabled = True
    fake_manager.wake.feed = AsyncMock(
        return_value=WakeEvent(phrase="ray", confidence=0.9, detected_at=datetime.now(UTC))
    )

    session = VoiceSession(fake_manager, __import__("uuid").uuid4())
    session.state = "armed"
    await session._handle_bytes(mock_websocket, b"audio")

    fake_manager.wake.feed.assert_awaited_once()
    assert session.state == "listening"


async def test_voice_stream_route_rejects_missing_token() -> None:
    """The WebSocket closes 1008 when the token query param is missing."""
    from ray.api.routes.voice import voice_stream

    ws = AsyncMock(spec=WebSocket)
    ws.query_params = {}
    await voice_stream(ws)
    ws.close.assert_awaited_once_with(code=1008)


async def test_voice_stream_route_closes_when_local_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the right token but missing local voice deps, the route closes 1011."""
    from ray.api.routes.voice import voice_stream

    fake_manager = VoiceManager(get_settings())
    fake_manager.settings.stt_backend = "local"
    fake_manager.settings.tts_backend = "local"
    monkeypatch.setattr("ray.voice.manager.get_voice_manager", lambda: fake_manager)

    ws = AsyncMock(spec=WebSocket)
    ws.query_params = {"token": TEST_TOKEN}
    await voice_stream(ws)
    ws.close.assert_awaited_once()
    assert ws.close.call_args.kwargs["code"] == 1011
