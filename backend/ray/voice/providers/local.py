"""Local voice providers: faster-whisper STT, Piper TTS, openWakeWord wake word.

These are optional installs. See ``pyproject.toml`` ``[dependency-groups] voice``
for the STT/TTS deps; openWakeWord must be installed manually because it is not
yet published with Python 3.12 wheels.

If a package or model file is missing the provider reports ``ready=False`` and an
explanatory ``detail`` string, so Ray still starts and the UI can fall back to
browser speech.
"""

import asyncio
import io
import os
import wave
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ray.voice.base import (
    AudioChunk,
    SpeechRequest,
    Transcript,
    VoiceError,
    VoiceProviderInfo,
    WakeEvent,
    WakeWordDetector,
)

# Optional heavy dependencies. They are only loaded when the user opts into the local
# voice stack; failing to import must not break the default install.
np: Any = None
try:
    import numpy as _np

    np = _np
except Exception:  # pragma: no cover - CI without the voice group
    pass

WhisperModel: Any = None
try:
    from faster_whisper import WhisperModel as _WhisperModel

    WhisperModel = _WhisperModel
except Exception:  # pragma: no cover
    pass

PiperVoice: Any = None
SynthesisConfig: Any = None
try:
    from piper import PiperVoice as _PiperVoice
    from piper.config import SynthesisConfig as _SynthesisConfig

    PiperVoice = _PiperVoice
    SynthesisConfig = _SynthesisConfig
except Exception:  # pragma: no cover
    pass

OpenWakeWordModel: Any = None
try:
    from openwakeword.model import Model as _OpenWakeWordModel

    OpenWakeWordModel = _OpenWakeWordModel
except Exception:  # pragma: no cover
    pass


class _Lazy:
    """Holds a lazily-initialised dependency so import failures surface as info, not crashes."""

    def __init__(self, factory: Any) -> None:
        self._factory = factory
        self._value: Any | None = None
        self._error: Exception | None = None

    def get(self) -> Any:
        if self._value is not None:
            return self._value
        if self._error is not None:
            raise self._error
        try:
            self._value = self._factory()
            return self._value
        except Exception as exc:  # pragma: no cover - exercised by missing models
            self._error = VoiceError(str(exc))
            raise self._error from exc


def _ensure_wav(audio: bytes, sample_rate: int) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV header, or pass through an existing WAV."""
    if audio.startswith(b"RIFF"):
        return audio
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio)
    return buffer.getvalue()


async def _ffmpeg_to_wav(audio: bytes) -> bytes:
    """Convert any audio ffmpeg understands to 16-bit 16 kHz mono WAV."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise VoiceError(
            "ffmpeg is required to decode browser audio (WebM/Ogg/MP4). "
            "Install ffmpeg, ensure it is on PATH, and restart Ray; see README local voice setup."
        ) from exc
    stdout, stderr = await proc.communicate(input=audio)
    if proc.returncode != 0:
        raise VoiceError(f"ffmpeg failed: {stderr.decode(errors='ignore')[:200]}")
    return stdout


def _is_encoded_audio(audio: bytes) -> bool:
    return audio.startswith(
        (b"\x1a\x45\xdf\xa3", b"OggS", b"fLaC", b"ID3", b"FORM", b"caff")
    ) or audio[4:8] in (b"ftyp", b"moov", b"mdat")


class LocalSpeechToText:
    """faster-whisper running on the local machine."""

    name = "local"

    def __init__(
        self,
        model_name: str = "tiny",
        language: str | None = None,
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self.model_name = model_name
        self.language = language
        self.device = device
        self.compute_type = compute_type
        self._model: _Lazy | None = None

    def _load(self) -> Any:
        if WhisperModel is None:
            raise VoiceError("faster-whisper is not installed. Run: uv sync --group voice")
        return WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)

    async def transcribe(self, audio: bytes, *, sample_rate: int = 16_000) -> Transcript:
        if not audio:
            return Transcript(text="", confidence=1.0, language="en")

        wav = (
            await _ffmpeg_to_wav(audio)
            if _is_encoded_audio(audio)
            else _ensure_wav(audio, sample_rate)
        )
        audio_file = io.BytesIO(wav)

        if self._model is None:
            self._model = _Lazy(self._load)
        model = await asyncio.to_thread(self._model.get)

        segments, info = await asyncio.to_thread(
            model.transcribe,
            audio_file,
            language=self.language,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text = "".join(segment.text for segment in segments)
        return Transcript(
            text=text.strip(),
            confidence=1.0 - getattr(info, "no_speech_prob", 0.0),
            language=info.language or "en",
            duration_seconds=info.duration,
        )

    async def transcribe_stream(
        self, chunks: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[Transcript]:
        """faster-whisper is utterance-oriented; accumulate and transcribe at end."""
        buffer = bytearray()
        async for chunk in chunks:
            buffer.extend(chunk.data)
            if not chunk.is_final:
                # Keep the HUD alive while audio is still arriving.
                yield Transcript(text="", confidence=0.0, is_final=False)
            else:
                yield await self.transcribe(bytes(buffer))

    def info(self) -> VoiceProviderInfo:
        if WhisperModel is None:
            return VoiceProviderInfo("local_stt", False, "faster-whisper is not installed")
        if not self.model_name:
            return VoiceProviderInfo("local_stt", False, "stt_model is not configured")
        return VoiceProviderInfo("local_stt", True, f"model={self.model_name}")


class LocalTextToSpeech:
    """Piper local neural text-to-speech."""

    name = "local"

    def __init__(
        self,
        voice_path: str = "",
        length_scale: float = 1.0,
        voice_models_dir: str = "",
    ) -> None:
        self.voice_path = voice_path
        self.length_scale = length_scale
        self.voice_models_dir = voice_models_dir
        self._voice: _Lazy | None = None

    def _resolved_voice_path(self) -> Path:
        if not self.voice_path:
            return Path("")
        expanded = Path(os.path.expanduser(self.voice_path))
        if expanded.is_absolute() or not self.voice_models_dir:
            return expanded
        models_dir = Path(os.path.expanduser(self.voice_models_dir))
        return models_dir / expanded

    def _load(self) -> Any:
        if PiperVoice is None:
            raise VoiceError("piper-tts is not installed. Run: uv sync --group voice")
        voice_path = self._resolved_voice_path()
        if not voice_path.exists():
            raise VoiceError(f"Piper voice model not found: {voice_path}")
        return PiperVoice.load(str(voice_path))

    async def synthesize(self, request: SpeechRequest) -> AsyncIterator[AudioChunk]:
        if not request.text.strip():
            yield AudioChunk(data=b"", sample_rate=22_050, is_final=True)
            return

        if self._voice is None:
            self._voice = _Lazy(self._load)
        voice = await asyncio.to_thread(self._voice.get)

        def _stream() -> Iterator[AudioChunk]:
            cfg = SynthesisConfig(length_scale=self.length_scale / max(request.speed, 0.1))
            sample_rate = 22_050
            for chunk in voice.synthesize(request.text, syn_config=cfg):
                sample_rate = chunk.sample_rate
                yield AudioChunk(
                    data=chunk.audio_int16_bytes,
                    sample_rate=sample_rate,
                    is_final=False,
                )
            yield AudioChunk(data=b"", sample_rate=sample_rate, is_final=True)

        # Piper is CPU-bound; run off the event loop.
        for audio_chunk in await asyncio.to_thread(list, _stream()):
            yield audio_chunk

    async def available_voices(self) -> list[str]:
        voice_path = self._resolved_voice_path()
        exists = await asyncio.to_thread(lambda: voice_path.exists())
        if voice_path and exists:
            return [str(voice_path)]
        return []

    def info(self) -> VoiceProviderInfo:
        if PiperVoice is None:
            return VoiceProviderInfo("local_tts", False, "piper-tts is not installed")
        voice_path = self._resolved_voice_path()
        if not self.voice_path:
            return VoiceProviderInfo("local_tts", False, "tts_voice model path is not configured")
        if not voice_path.exists():
            return VoiceProviderInfo(
                "local_tts", False, f"Piper voice model not found: {voice_path}"
            )
        return VoiceProviderInfo("local_tts", True, f"voice={voice_path.name}")


class LocalWakeWord(WakeWordDetector):
    """Server-side wake-word detector.

    Prefer openWakeWord when a model is available. Otherwise fall back to a tiny
    faster-whisper keyword spotter so the wake-word path works locally without
    installing openwakeword wheels.
    """

    name = "local"

    def __init__(
        self,
        model_path: str = "",
        keywords: list[str] | None = None,
        stt_model: str = "tiny",
        stt_language: str | None = None,
    ) -> None:
        self.model_path = model_path
        self.keywords = [k.lower() for k in (keywords or ["ray", "jarvis"])]
        self.stt_model = stt_model
        self.stt_language = stt_language
        self._model: _Lazy | None = None
        self._stt: LocalSpeechToText | None = None
        self._last_detection: float = 0.0
        self._debounce_seconds = 1.0
        self._buffer = bytearray()
        # Process 1.5 s windows, advancing 1.0 s each time, at 16 kHz 16-bit mono.
        self._window_bytes = int(1.5 * 16_000 * 2)
        self._step_bytes = int(1.0 * 16_000 * 2)

    def _use_openwakeword(self) -> bool:
        return (
            OpenWakeWordModel is not None
            and bool(self.model_path)
            and Path(self.model_path).exists()
        )

    def _use_stt(self) -> bool:
        return not self._use_openwakeword() and WhisperModel is not None

    def _load(self) -> Any:
        if OpenWakeWordModel is None:
            raise VoiceError("openwakeword is not installed")
        if not self.model_path or not Path(self.model_path).exists():
            raise VoiceError(f"openWakeWord model not found: {self.model_path}")
        return OpenWakeWordModel(wakeword_models=[self.model_path])

    def _get_stt(self) -> LocalSpeechToText:
        if self._stt is None:
            self._stt = LocalSpeechToText(
                model_name=self.stt_model,
                language=self.stt_language,
            )
        return self._stt

    async def feed(self, audio: bytes, *, sample_rate: int = 16_000) -> WakeEvent | None:
        if self._use_openwakeword():
            return await self._feed_openwakeword(audio, sample_rate)
        if self._use_stt():
            return await self._feed_stt(audio, sample_rate)
        return None

    async def _feed_openwakeword(self, audio: bytes, sample_rate: int) -> WakeEvent | None:
        if np is None:
            raise VoiceError("numpy is not installed")

        if self._model is None:
            self._model = _Lazy(self._load)
        model = await asyncio.to_thread(self._model.get)

        expected_len = len(audio) // 2 * 2
        if expected_len == 0:
            return None
        frame = np.frombuffer(audio[:expected_len], dtype=np.int16)

        def _predict() -> Any:
            return model.predict(frame)

        predictions = await asyncio.to_thread(_predict)

        matched: tuple[str, float] | None = None
        for key, score in predictions.items():
            key_lower = str(key).lower()
            for keyword in self.keywords:
                if keyword in key_lower and float(score) > 0.5:
                    if matched is None or float(score) > matched[1]:
                        matched = (keyword, float(score))
            if matched is None and float(score) > 0.7:
                matched = (self.keywords[0], float(score))

        if matched is None:
            return None

        return self._make_event(matched[0], matched[1])

    async def _feed_stt(self, audio: bytes, sample_rate: int) -> WakeEvent | None:
        stt = self._get_stt()
        self._buffer.extend(audio)

        while len(self._buffer) >= self._window_bytes:
            window = bytes(self._buffer[: self._window_bytes])
            try:
                wav = _ensure_wav(window, sample_rate)
            except Exception:
                wav = await _ffmpeg_to_wav(window)
            transcript = await stt.transcribe(wav, sample_rate=sample_rate)
            text = transcript.text.strip().lower().rstrip(",.!?")
            parts = text.split()
            for keyword in self.keywords:
                if parts and keyword in parts[0]:
                    self._buffer.clear()
                    return self._make_event(keyword, transcript.confidence)

            # Advance by the step size, keeping overlap for phrases that cross windows.
            advance = min(self._step_bytes, len(self._buffer))
            self._buffer = self._buffer[advance:]

        return None

    def _make_event(self, phrase: str, confidence: float) -> WakeEvent | None:
        now = datetime.now(UTC).timestamp()
        if now - self._last_detection < self._debounce_seconds:
            return None
        self._last_detection = now
        return WakeEvent(phrase=phrase, confidence=confidence, detected_at=datetime.now(UTC))

    async def reset(self) -> None:
        self._buffer.clear()
        if self._model is not None:
            try:
                model = await asyncio.to_thread(self._model.get)
                await asyncio.to_thread(model.reset)
            except Exception:
                pass

    def info(self) -> VoiceProviderInfo:
        if self._use_openwakeword():
            return VoiceProviderInfo("local_wake", True, f"model={Path(self.model_path).name}")
        if self._use_stt():
            return VoiceProviderInfo(
                "local_wake",
                True,
                f"keyword STT fallback (model={self.stt_model})",
            )
        if OpenWakeWordModel is None and WhisperModel is None:
            return VoiceProviderInfo(
                "local_wake", False, "openwakeword and faster-whisper are not installed"
            )
        if OpenWakeWordModel is None:
            return VoiceProviderInfo(
                "local_wake", False, "openwakeword not installed; no wake model configured"
            )
        if not self.model_path:
            return VoiceProviderInfo("local_wake", False, "wake_word_model path is not configured")
        if not Path(self.model_path).exists():
            return VoiceProviderInfo(
                "local_wake", False, f"openWakeWord model not found: {self.model_path}"
            )
        return VoiceProviderInfo("local_wake", True, f"model={Path(self.model_path).name}")
