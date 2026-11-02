# ADR-0009 — Voice-first architecture with wake word as a core feature

## Status

Accepted. Supersedes the "wake word is a future enhancement" framing in `docs/02` and
`docs/09`.

Implementation clarification (see ADR-0018): the browser wake filter operates on
Web Speech transcripts, so vendor audio upload can happen before activation. The
HUD's implemented local recording path is push-to-talk, not continuous local wake
capture. The pipeline below records the original design, not a privacy guarantee.

## Context

Wake-word activation is a core identity feature of Ray, not an optional extra: the
target experience is *say "Ray" → Ray activates → speak → Ray answers aloud*. But voice
is also the part most likely to swallow weeks in model tuning and latency work, and
`docs/11` requires incremental delivery that never blocks on one component.

The resolution is to separate **architecture** from **implementation quality**. The
architecture must be voice-first from Phase 1 so that voice is never retrofitted; the
implementation improves across phases.

## Decision

### The pipeline is a first-class part of the system from the start

```
Microphone → Wake word detector → VAD/endpointing → STT → Ray Core → TTS → Speaker
                    (client)                        (server)          (server)
```

`ray/voice/` exists from Phase 1 with the interfaces defined and no-op/browser-backed
implementations behind them:

* `WakeWordDetector.listen() -> AsyncIterator[WakeEvent]`
* `SpeechToText.transcribe(audio) -> Transcript`
* `TextToSpeech.synthesize(text) -> AudioStream`

**Critically, the text path is defined as a special case of the voice path, not the
other way around.** `ray/core/orchestrator.py` accepts an `input_modality` and an
`output_modality`, and agents produce responses with a `speech_text` variant alongside
the markdown for the screen — because a good spoken answer is shorter and has no code
blocks or bullet lists. Adding this later would have meant rewriting every agent's
output contract.

### Chosen implementations (all free, all local)

* **Wake word: openWakeWord.** Free, Apache-licensed, runs on CPU, and supports training
  a custom "Ray" model. Preferred over Porcupine, whose free tier carries licensing and
  activation limits that conflict with `docs/01`.
* **STT: `faster-whisper`** (`base`/`small` int8, CPU). Fully local, fast enough for
  conversational turns, far more accurate than browser STT on technical vocabulary
  ("Processing", "pgvector", "Waterloo").
* **TTS: Piper.** Local neural TTS, natural sounding, near-instant on CPU, free.
* **Fallbacks:** browser Web Speech API for STT and `SpeechSynthesis` for TTS, so voice
  works on day one with zero model downloads while the local stack is being built out.

### Transport

Wake-word detection runs **in the browser client**, not the server: it must listen
continuously, and streaming raw microphone audio to the backend all day would be both
wasteful and a privacy problem. Only after the wake word fires does audio go to the
server — over a WebSocket at `/voice/stream`, which is the one genuinely bidirectional
part of Ray and the exception to ADR-0007.

### Incremental delivery

| Phase | Voice deliverable |
|---|---|
| 1 | `ray/voice/` interfaces, modality-aware core contract, `speech_text` in agent output |
| 2 | Voice button, browser STT/TTS fallback — a working spoken round trip, low quality |
| 6 | Local faster-whisper + Piper, `/voice/stream`, Listening/Processing/Responding states |
| 6b | openWakeWord "Ray" activation, barge-in, latency optimisation |

No phase blocks on voice quality; every phase leaves voice working at some level.

## Alternatives considered

* **Bolt voice on at the end.** The original doc position. Rejected: it would force a
  rewrite of the agent output contract and the core request model, which is exactly the
  retrofit this ADR exists to prevent.
* **Server-side always-on wake word.** Simpler client, but continuous audio upload is
  unacceptable for privacy and bandwidth.
* **Cloud STT/TTS for quality.** Better voices, but recurring cost and every spoken word
  leaves the machine. Rejected.

## Consequences

* Agents must produce two response variants; prompts and tests must cover both.
* Continuous microphone access needs an explicit, revocable user permission and a
  visible always-on indicator (`docs/12`).
* Local Whisper and Piper add model downloads and CPU load; the browser fallback keeps
  Ray usable on weak hardware.
