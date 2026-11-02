"""Voice runtime: wires STT, TTS, and wake-word into one local pipeline.

The manager is intentionally small. It loads optional local providers, exposes a
single ``info()`` surface for ``/health``, and creates per-connection sessions
that drive the ``/voice/stream`` WebSocket.
"""

import asyncio
import base64
import json
import uuid
from dataclasses import dataclass, field

import structlog
from fastapi import WebSocket

from ray.config import Settings, get_settings
from ray.core.contracts import RayRequest
from ray.core.orchestrator import Orchestrator
from ray.domain.enums import Modality
from ray.services import user_service
from ray.voice.base import SpeechRequest, VoiceError
from ray.voice.providers.local import LocalSpeechToText, LocalTextToSpeech, LocalWakeWord

log = structlog.get_logger()


def _get_voice_manager() -> "VoiceManager":
    """Global singleton; replaced by tests through ``manager`` parameter."""
    return VoiceManager(get_settings())


@dataclass
class VoiceCapabilities:
    """Snapshot reported by ``/health``."""

    stt_backend: str
    tts_backend: str
    wake_word_enabled: bool
    wake_words: list[str] = field(default_factory=lambda: ["ray", "jarvis"])
    local_ready: bool = False
    local_detail: str = ""


class VoiceManager:
    """Owns local voice provider instances for the process lifetime."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.stt = self._build_stt()
        self.tts = self._build_tts()
        self.wake = self._build_wake()

    def _build_stt(self) -> LocalSpeechToText:
        return LocalSpeechToText(
            model_name=self.settings.stt_model,
            language=self.settings.stt_language,
        )

    def _build_tts(self) -> LocalTextToSpeech:
        return LocalTextToSpeech(
            voice_path=self.settings.tts_voice,
            length_scale=self.settings.tts_length_scale,
            voice_models_dir=self.settings.voice_models_dir,
        )

    def _build_wake(self) -> LocalWakeWord:
        return LocalWakeWord(
            model_path=self.settings.wake_word_model,
            keywords=self.settings.wake_words,
            stt_model=self.settings.stt_model,
            stt_language=self.settings.stt_language,
        )

    def info(self) -> VoiceCapabilities:
        stt_info = self.stt.info()
        tts_info = self.tts.info()
        wake_info = self.wake.info()
        ready = stt_info.ready and tts_info.ready
        details = []
        if not stt_info.ready:
            details.append(f"stt: {stt_info.detail}")
        if not tts_info.ready:
            details.append(f"tts: {tts_info.detail}")
        if self.settings.wake_word_enabled and not wake_info.ready:
            details.append(f"wake: {wake_info.detail}")
        return VoiceCapabilities(
            stt_backend=self.settings.stt_backend,
            tts_backend=self.settings.tts_backend,
            wake_word_enabled=self.settings.wake_word_enabled,
            wake_words=self.settings.wake_words,
            local_ready=ready,
            local_detail="; ".join(details) if details else "",
        )

    async def session(self, user_id: uuid.UUID) -> "VoiceSession":
        return VoiceSession(self, user_id)


class VoiceSession:
    """One WebSocket connection's state machine.

    States: armed -> listening -> thinking -> speaking -> armed
    The wake word, if enabled, keeps the session armed and monitors incoming audio
    for the activation phrase. Without it the client must send a ``start`` message.
    """

    def __init__(self, manager: VoiceManager, user_id: uuid.UUID) -> None:
        self.manager = manager
        self.user_id = user_id
        self.state = "armed" if manager.settings.wake_word_enabled else "idle"
        self.audio_buffer = bytearray()
        self.current_task: asyncio.Task[None] | None = None

    async def run(self, websocket: WebSocket) -> None:
        await websocket.accept()
        await self._send_state(websocket)

        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break

                if "text" in message:
                    await self._handle_text(websocket, message["text"])
                elif "bytes" in message:
                    await self._handle_bytes(websocket, message["bytes"])
        finally:
            if self.current_task is not None:
                self.current_task.cancel()
                try:
                    await self.current_task
                except asyncio.CancelledError:
                    pass

    async def _handle_text(self, websocket: WebSocket, text: str) -> None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            await self._send_error(websocket, "expected JSON control message")
            return

        msg_type = data.get("type")

        if msg_type == "start":
            self.audio_buffer.clear()
            self.state = "listening"
            await self._send_state(websocket)
        elif msg_type == "stop":
            await self._transcribe_and_respond(websocket)
        elif msg_type == "barge":
            if self.current_task is not None:
                self.current_task.cancel()
                self.current_task = None
            self.audio_buffer.clear()
            self.state = "listening"
            await self._send_state(websocket)
        else:
            await self._send_error(websocket, f"unknown type: {msg_type}")

    async def _handle_bytes(self, websocket: WebSocket, audio: bytes) -> None:
        if self.state == "armed":
            if self.manager.settings.wake_word_enabled:
                event = await self.manager.wake.feed(audio)
                if event is not None:
                    await self._send(
                        websocket,
                        "wake",
                        {
                            "phrase": event.phrase,
                            "confidence": event.confidence,
                            "detected_at": event.detected_at.isoformat(),
                        },
                    )
                    self.audio_buffer.clear()
                    self.state = "listening"
                    await self._send_state(websocket)
            return

        if self.state == "listening":
            self.audio_buffer.extend(audio)
            await self._send(websocket, "partial", {"bytes": len(self.audio_buffer)})

    async def _transcribe_and_respond(self, websocket: WebSocket) -> None:
        self.state = "thinking"
        await self._send_state(websocket)

        try:
            transcript = await self.manager.stt.transcribe(bytes(self.audio_buffer))
        except VoiceError as exc:
            await self._send_error(websocket, str(exc))
            self.state = "armed" if self.manager.settings.wake_word_enabled else "idle"
            await self._send_state(websocket)
            return
        await self._send(
            websocket,
            "transcript",
            {"text": transcript.text, "language": transcript.language},
        )

        if not transcript.text.strip():
            self.state = "armed" if self.manager.settings.wake_word_enabled else "idle"
            await self._send_state(websocket)
            return

        self.current_task = asyncio.create_task(self._process_request(websocket, transcript.text))

    async def _process_request(self, websocket: WebSocket, text: str) -> None:
        from ray.db.session import get_sessionmaker

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            user = await user_service.get_user(session, self.user_id)
            user_name = user.name if user is not None else "Ray User"

            orchestrator = Orchestrator(settings=self.manager.settings)
            request = RayRequest(
                user_id=self.user_id,
                message=text,
                input_modality=Modality.VOICE,
                output_modality=Modality.VOICE,
            )

            content_parts: list[str] = []
            speech_text: str = ""
            async for event in orchestrator.run(session, request, user_name):
                if event.event == "token":
                    content_parts.append(event.text)
                elif event.event == "done":
                    speech_text = event.speech_text or ""

            content = "".join(content_parts)
            if not speech_text and content:
                speech_text = content

            await session.commit()

            await self._send(
                websocket,
                "response_text",
                {"content": content, "speech_text": speech_text},
            )

            self.state = "speaking"
            await self._send_state(websocket)

            await self._stream_tts(websocket, speech_text)

            self.state = "armed" if self.manager.settings.wake_word_enabled else "idle"
            await self._send_state(websocket)

    async def _stream_tts(self, websocket: WebSocket, text: str) -> None:
        request = SpeechRequest(text=text, voice="default")
        try:
            async for chunk in self.manager.tts.synthesize(request):
                if chunk.data:
                    await self._send(
                        websocket,
                        "audio",
                        {
                            "data": base64.b64encode(chunk.data).decode("ascii"),
                            "sample_rate": chunk.sample_rate,
                            "is_final": chunk.is_final,
                        },
                    )
                elif chunk.is_final:
                    await self._send(websocket, "audio", {"is_final": True})
        except Exception as exc:
            log.warning("voice.tts_failed", error=str(exc))
            await self._send(websocket, "audio", {"is_final": True, "error": str(exc)})

    async def _send_state(self, websocket: WebSocket) -> None:
        await self._send(websocket, "state", {"state": self.state})

    async def _send_error(self, websocket: WebSocket, message: str) -> None:
        await self._send(websocket, "error", {"message": message})

    async def _send(self, websocket: WebSocket, msg_type: str, payload: dict[str, object]) -> None:
        await websocket.send_json({"type": msg_type, **payload})


def get_voice_manager() -> VoiceManager:
    """Process-level voice manager singleton."""
    return _get_voice_manager()
