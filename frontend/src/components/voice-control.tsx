"use client";

import type { VoiceCapabilities } from "@/lib/api";
import type { Voice, VoiceState } from "@/hooks/use-voice";

const LABEL: Record<VoiceState, string> = {
  idle: "Voice off",
  armed: "Say \u201cRay\u201d or \u201cJarvis\u201d",
  listening: "Listening\u2026",
  thinking: "Thinking\u2026",
  speaking: "Responding\u2026",
};

const DOT: Record<VoiceState, string> = {
  idle: "bg-hud-muted",
  armed: "bg-hud-accent/60",
  listening: "bg-hud-accent hud-pulse",
  thinking: "bg-hud-warn hud-pulse",
  speaking: "bg-hud-accent hud-pulse",
};

const WAKE_WORDS = ["ray", "jarvis"];

/**
 * Voice affordances and the pipeline's real state (ADR-0009).
 *
 * Arming keeps the microphone open and waits for the wake word; push-to-talk is
 * one utterance. Both must be user gestures — browsers only grant microphone
 * permission from one — which is why a backend that reports the wake word as
 * enabled still cannot auto-arm.
 *
 * The backend label is not decoration: `browser` speech recognition sends audio
 * to Google, so the user is entitled to see which backend is transcribing them
 * (docs/12).
 */
export function VoiceControl({
  capabilities,
  voice,
}: {
  capabilities: VoiceCapabilities | null;
  voice: Voice;
}) {
  const armed = voice.state !== "idle";
  const wakeWords = capabilities?.wake_words ?? WAKE_WORDS;
  const wakeLabel = wakeWords.length > 1 ? wakeWords.slice(0, -1).join(", ") + " or " + wakeWords[wakeWords.length - 1] : wakeWords[0] ?? "Ray";

  return (
    <div className="flex items-center gap-2">
      {voice.error !== null && (
        <span role="alert" className="max-w-[18rem] text-[11px] text-hud-danger">
          {voice.error}
        </span>
      )}

      <button
        type="button"
        onClick={voice.toggleArmed}
        disabled={!voice.supported}
        aria-pressed={armed}
        aria-label={voice.localReady ? (armed ? "Stop local recording" : "Start local recording") : armed ? "Disarm wake word listening" : "Arm wake word listening"}
        title={
          voice.supported
            ? voice.localReady ? "Record locally; click again to send" : `Listen continuously for "${wakeLabel}"`
            : "This browser has no speech recognition"
        }
        className="flex items-center gap-2 rounded-full border border-hud-border px-3 py-1.5 text-xs text-hud-muted transition-colors hover:border-hud-accent/50 hover:text-hud-text disabled:cursor-not-allowed disabled:opacity-60"
      >
        <span className={`h-2 w-2 rounded-full ${DOT[voice.state]}`} />
        {voice.localReady ? (voice.state === "idle" ? "Local microphone" : LABEL[voice.state]) : armed && wakeWords.length > 1 ? `Say "${wakeLabel}"` : LABEL[voice.state]}
      </button>

      <button
        type="button"
        onClick={voice.pushToTalk}
        disabled={!voice.supported}
        aria-label="Push to talk"
        title={voice.localReady ? "Push and hold to speak to Ray locally" : "Speak one request without the wake word"}
        className="rounded-full border border-hud-border px-2.5 py-1.5 text-xs text-hud-muted transition-colors hover:border-hud-accent/50 hover:text-hud-text disabled:cursor-not-allowed disabled:opacity-60"
      >
        ⏺
      </button>

      <button
        type="button"
        onClick={voice.toggleSpeech}
        aria-pressed={voice.speechEnabled}
        aria-label="Toggle spoken replies"
        title="Speak Ray's replies aloud"
        className={`rounded-full border px-2.5 py-1.5 text-xs transition-colors ${
          voice.speechEnabled
            ? "border-hud-accent/50 text-hud-accent"
            : "border-hud-border text-hud-muted hover:text-hud-text"
        }`}
      >
        {voice.speechEnabled ? "🔊" : "🔇"}
      </button>

      <span className="font-mono text-[10px] uppercase tracking-widest text-hud-muted">
        {capabilities === null
          ? "unavailable"
          : `${capabilities.local_ready ? "local" : capabilities.stt_backend} voice`}
      </span>
    </div>
  );
}
