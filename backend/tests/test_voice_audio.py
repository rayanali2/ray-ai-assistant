import asyncio
import io
import shutil
import subprocess
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ray.voice.base import VoiceError
from ray.voice.providers import local


def stt(monkeypatch):
    model = MagicMock()
    model.transcribe.return_value = (
        [SimpleNamespace(text="decoded")],
        SimpleNamespace(language="en", duration=0.05, no_speech_prob=0.0),
    )
    monkeypatch.setattr(local, "WhisperModel", lambda *args, **kwargs: model)
    return local.LocalSpeechToText(), model


@pytest.mark.parametrize("header", [b"\x1aE\xdf\xa3", b"OggS", b"\x00\x00\x00\x18ftyp", b"ID3"])
async def test_container_is_decoded_before_stt(monkeypatch, header):
    provider, model = stt(monkeypatch)
    wav = local._ensure_wav(b"\x00\x00" * 80, 16000)
    decoder = AsyncMock(return_value=wav)
    monkeypatch.setattr(local, "_ffmpeg_to_wav", decoder)
    audio = header + b"encoded audio"
    assert (await provider.transcribe(audio)).text == "decoded"
    decoder.assert_awaited_once_with(audio)
    assert model.transcribe.call_args.args[0].getvalue() == wav


@pytest.mark.parametrize("wrapped", [False, True])
async def test_pcm_and_wav_do_not_need_ffmpeg(monkeypatch, wrapped):
    provider, model = stt(monkeypatch)
    pcm = b"\x00\x00" * 80
    wav = local._ensure_wav(pcm, 22050)
    decoder = AsyncMock()
    monkeypatch.setattr(local, "_ffmpeg_to_wav", decoder)
    await provider.transcribe(wav if wrapped else pcm, sample_rate=22050)
    decoder.assert_not_awaited()
    with wave.open(model.transcribe.call_args.args[0], "rb") as decoded:
        assert decoded.getframerate() == 22050
        assert decoded.readframes(80) == pcm


async def test_empty_audio_does_not_load_model_or_decode(monkeypatch):
    provider, model = stt(monkeypatch)
    decoder = AsyncMock()
    monkeypatch.setattr(local, "_ffmpeg_to_wav", decoder)
    assert (await provider.transcribe(b"")).text == ""
    model.transcribe.assert_not_called()
    decoder.assert_not_awaited()


async def test_missing_ffmpeg_is_actionable_not_pcm(monkeypatch):
    provider, model = stt(monkeypatch)
    monkeypatch.setattr(
        local.asyncio, "create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError)
    )
    with pytest.raises(VoiceError, match=r"ffmpeg is required.*WebM/Ogg/MP4"):
        await provider.transcribe(b"OggSencoded")
    model.transcribe.assert_not_called()


async def test_invalid_container_is_not_sent_to_stt(monkeypatch):
    provider, model = stt(monkeypatch)
    process = SimpleNamespace(
        returncode=1, communicate=AsyncMock(return_value=(b"", b"Invalid data"))
    )
    monkeypatch.setattr(local.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(VoiceError, match="ffmpeg failed: Invalid data"):
        await provider.transcribe(b"\x00\x00\x00\x18ftypbroken")
    model.transcribe.assert_not_called()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="optional ffmpeg not installed")
@pytest.mark.parametrize(
    ("container", "codec"), [("webm", "libopus"), ("ogg", "libopus"), ("mp4", "aac")]
)
async def test_real_mediarecorder_container_decodes_to_pcm(monkeypatch, container, codec):
    provider, model = stt(monkeypatch)
    encoded = (
        await asyncio.to_thread(
            subprocess.run,
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=mono",
                "-t",
                "0.05",
                "-c:a",
                codec,
                *(["-movflags", "frag_keyframe+empty_moov"] if container == "mp4" else []),
                "-f",
                container,
                "pipe:1",
            ],
            capture_output=True,
            check=True,
            timeout=10,
        )
    ).stdout
    await provider.transcribe(encoded)
    wav = model.transcribe.call_args.args[0].getvalue()
    assert wav != local._ensure_wav(encoded, 16000)
    with wave.open(io.BytesIO(wav), "rb") as decoded:
        assert decoded.getnchannels() == 1
        assert decoded.getsampwidth() == 2
        assert decoded.getframerate() == 16000
        assert len(decoded.readframes(16000)) > 0
