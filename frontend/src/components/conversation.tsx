"use client";

import { useCallback, useEffect, useRef } from "react";

import { Composer, type ComposerHandle } from "@/components/composer";
import { useDashboard } from "@/components/dashboard-context";
import { MessageList } from "@/components/message-list";
import { Reactor, type ReactorState } from "@/components/reactor";
import { VoiceControl } from "@/components/voice-control";
import { useChat } from "@/hooks/use-chat";
import { useAudioLevel } from "@/hooks/use-audio-level";
import { useDesktopListen } from "@/hooks/use-desktop-listen";
import { useKeyboardShortcuts } from "@/hooks/use-keyboard";
import { useVoice } from "@/hooks/use-voice";
import type { Health, RestoredConversation } from "@/lib/api";

/**
 * The conversation surface: the whole loop in one place.
 *
 *   wake word or typing → POST /api/chat → SSE tokens → trace → optional speech
 *
 * Voice and text converge on the same `send`, so a spoken turn and a typed turn
 * are the same turn to everything downstream. The only difference is the
 * modality, which the backend uses to shape the prompt (ADR-0009).
 */
export function Conversation({
  health,
  userName,
  restored,
}: {
  health: Health | null;
  userName: string;
  /** The conversation Ray was last having, fetched on the server. */
  restored: RestoredConversation | null;
}) {
  const chat = useChat(restored ?? undefined);
  const { pendingApprovals, setVoiceState, setAgentName } = useDashboard();
  const composerRef = useRef<ComposerHandle>(null);

  const send = useCallback(
    (message: string, spoken = false) => {
      void chat.send(message, spoken ? "voice" : "text");
    },
    [chat],
  );

  const voice = useVoice({
    onRequest: (text) => send(text, true),
    onResponse: (request, content, speechText) =>
      chat.appendVoiceResponse(request, content, speechText),
    wakeWordEnabled: health?.voice?.wake_word_enabled ?? false,
    capabilities: health?.voice ?? null,
  });
  useDesktopListen(voice.pushToTalk);

  // The voice indicator tracks the request, not just the microphone.
  // In local voice mode the WebSocket drives states itself.
  useEffect(() => {
    if (!voice.localReady) voice.setThinking(chat.sending);
  }, [chat.sending, voice.setThinking, voice]);

  // Speak each answer once, using the spoken variant rather than the markdown.
  const spokenIdRef = useRef<string | null>(null);
  useEffect(() => {
    const completed = chat.lastCompleted;
    if (completed === null || spokenIdRef.current === completed.id) return;
    spokenIdRef.current = completed.id;
    voice.speak(completed.speechText ?? completed.content);
  }, [chat.lastCompleted, voice]);

  // Publish live state to the dashboard context for the status bar and reactor.
  useEffect(() => {
    setVoiceState(voice.state);
  }, [voice.state, setVoiceState]);

  useEffect(() => {
    setAgentName(chat.lastCompleted?.agentName);
  }, [chat.lastCompleted?.agentName, setAgentName]);

  const reactorState: ReactorState =
    pendingApprovals > 0 ? "approval" : voice.state;
  const level = useAudioLevel(voice.state, voice.micStream, voice.playbackAudio);

  useKeyboardShortcuts({
    onFocus: () => composerRef.current?.focus(),
    onStop: () => voice.stop(),
    onToggleArmed: () => voice.toggleArmed(),
  });

  const provider = health?.llm_provider ?? "offline";

  return (
    <section className="hud-frame conversation-surface relative flex min-h-0 flex-1 flex-col overflow-hidden border border-hud-border bg-hud-panel/60">

      <header className="relative z-10 flex items-center justify-between gap-3 border-b border-hud-border px-5 py-3">
        <div className="flex items-center gap-3">
          <h2 className="font-mono text-[11px] uppercase tracking-[0.18em] text-hud-muted">
            Conversation
          </h2>
          {chat.messages.length > 0 && (
            <button
              type="button"
              onClick={chat.reset}
              className="font-mono text-[10px] uppercase tracking-widest text-hud-muted transition-colors hover:text-hud-accent"
            >
              + New
            </button>
          )}
        </div>
        <VoiceControl capabilities={health?.voice ?? null} voice={voice} />
      </header>

      <div className={`reactor-stage ${chat.messages.length > 0 ? "reactor-stage-compact" : ""}`}>
        <div className="reactor-readout" aria-hidden="true"><span>NEURAL INTERFACE</span><strong>R.A.Y.</strong><span>PERSONAL INTELLIGENCE</span></div>
        <Reactor state={chat.sending && reactorState === "idle" ? "thinking" : reactorState} level={level} />
        <div className="reactor-readout text-right" aria-hidden="true"><span>VOICE LINK</span><strong>{voice.localReady ? "LOCAL" : "BROWSER"}</strong><span>{Math.round(level * 100).toString().padStart(3, "0")} / INPUT LEVEL</span></div>
      </div>

      <div className="relative z-10 flex min-h-0 flex-1 flex-col">
        <MessageList messages={chat.messages} userName={userName} onRetry={chat.retry} />
      </div>

      <div className="relative z-10">
        <Composer
          ref={composerRef}
          onSend={send}
          disabled={chat.sending}
          transcript={voice.transcript}
          providerLabel={provider}
        />
      </div>
    </section>
  );
}
