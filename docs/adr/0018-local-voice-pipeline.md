# ADR-0018 — Local voice providers behind optional model downloads

## Status

Accepted. Extends ADR-0009.

Current client limitation: backend wake detection exists, but the HUD's local
MediaRecorder path is push-to-talk only. Browser wake mode uses Web Speech and
can upload audio to the browser vendor before activation. WebM/Ogg/MP4 recordings
are decoded by ffmpeg; missing ffmpeg reports an error. Continuous local wake
capture remains future work, rather than a verified end-to-end HUD capability.

## Context

Phase 6 must add a fully local speech pipeline (wake word, STT, TTS) while keeping the
default install small and runnable without GPUs or model downloads. `faster-whisper`,
`piper-tts`, and `openwakeword` are not installed by default, and `openwakeword` has
compatibility issues with pre-built Python 3.12 wheels in the base environment.

The design must:

* let the backend claim voice capabilities only when models are present;
* keep the browser STT/TTS fallback working unchanged;
* never crash at import time when the optional packages are missing;
* support `ray` and `jarvis` as wake-word aliases.

## Decision

Voice providers live in `ray/voice/providers/local.py` behind lazy optional imports:

* `LocalSpeechToText` loads `faster-whisper` when the model files are present.
* `LocalTextToSpeech` loads `piper` and a voice model on first synthesis; relative voice
  paths are resolved against `voice_models_dir`.
* `LocalWakeWord` prefers an `openwakeword` `.tflite` model when one is configured and
  present. When it is absent, it falls back to a tiny `faster-whisper` keyword spotter that
  runs on 1.5-second sliding windows, so "Ray" and "Jarvis" activate the assistant without
  any dedicated wake-word dependency.

A `VoiceManager` reports `VoiceCapabilities` (`stt_backend`, `tts_backend`,
`wake_words`, `local_ready`, `local_detail`) so the frontend can switch between the
browser fallback and the local `/voice/stream` WebSocket without protocol changes.

`/voice/stream` is a stateful WebSocket that accepts binary audio frames and control
messages (`start`, `stop`, `barge`), runs STT, invokes the orchestrator with
`Modality.VOICE` input/output, and streams synthesized PCM audio back as base64 frames.
States (`armed`, `listening`, `thinking`, `speaking`) are pushed to the client so the HUD
reflects the real pipeline state. Barge-in cancels the current response and starts a new
listening turn.

For V1, the client wake-word loop can run in the browser (`SpeechRecognition`) or on the
server (`LocalWakeWord`). The server-side provider uses `openwakeword` when a `.tflite`
model is configured; otherwise it uses a `faster-whisper` keyword spotter so the
experience is usable without the missing wheel. Both paths use the same abstract
`WakeWordDetector` interface, so swapping implementations does not touch the core pipeline.

`wake_words` is a configuration list defaulting to `["ray", "jarvis"]`; the UI and the
wake-word detector render/use it without hardcoding a single keyword.

## Alternatives considered

* **Make `faster-whisper`, `piper-tts`, and `openwakeword` default dependencies.**
  Rejected: it bloats the install by gigabytes and breaks CI and low-powered machines.
* **Use cloud STT/TTS for Phase 6.** Rejected: it violates the free-first and local-only
  voice constraints in ADR-0009.
* **Wait for `openwakeword` wheels before shipping Phase 6.** Rejected: the WebSocket,
  STT, TTS, state machine, and UI are independently useful and can be merged.

## Consequences

* The `voice` dependency group in `pyproject.toml` is optional; users enable it with
  `uv sync --group voice` and download models with `uv run python scripts/download_voice_models.py`.
* `openwakeword` is not pinned in the default `voice` group because of the wheel
  incompatibility, but the keyword spotter fallback means wake word is usable out of the box.
* The frontend uses `MediaRecorder` and the Web Audio stack; browser codec support
  (WebM/Opus) is normalized to 16 kHz PCM on the server using `ffmpeg`.
* Wake-word state and barge-in are explicit and testable through the WebSocket protocol.
