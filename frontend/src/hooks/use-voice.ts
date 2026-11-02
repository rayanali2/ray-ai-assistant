"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getVoiceStreamUrl } from "@/app/actions/voice";
import { canUseLocalVoice } from "@/lib/hud";
import type { VoiceCapabilities } from "@/lib/api";
import {
  DEFAULT_WAKE_WORDS,
  TranscriptWakeWordDetector,
  stripWakeWord,
  type WakeEvent,
} from "@/lib/wake-word";

/**
 * The browser end of the voice round trip (ADR-0009).
 *
 * Two independent browser APIs, deliberately kept behind one state machine whose
 * states are the pipeline's real states, so the local faster-whisper/Piper/
 * openWakeWord backends can replace them without the UI changing:
 *
 *   idle -> armed -> listening -> thinking -> speaking -> armed
 *
 * When the backend reports `local_ready` with `stt_backend=local` and
 * `tts_backend=local`, audio is sent to `/voice/stream` instead of the browser's
 * cloud speech APIs. That path is push-to-talk for now; continuous wake-word
 * streaming will land once openWakeWord client models are wired in.
 *
 * Note that `RAY_STT_BACKEND=browser` is not local: Chrome sends the captured
 * audio to Google for transcription (docs/12). That is why the control shows
 * which backend is active instead of just a microphone icon.
 */

export type VoiceState = "idle" | "armed" | "listening" | "thinking" | "speaking";

/** Minimal shape of the Web Speech API, which TypeScript's DOM lib omits. */
interface SpeechRecognitionAlternative {
  transcript: string;
}
interface SpeechRecognitionResult {
  readonly isFinal: boolean;
  readonly length: number;
  [index: number]: SpeechRecognitionAlternative;
}
interface SpeechRecognitionEventLike {
  readonly resultIndex: number;
  readonly results: {
    readonly length: number;
    [index: number]: SpeechRecognitionResult;
  };
}
interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
}
type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

function recognitionConstructor(): SpeechRecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const candidate = window as unknown as {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  };
  return candidate.SpeechRecognition ?? candidate.webkitSpeechRecognition ?? null;
}

export interface UseVoiceOptions {
  /** Called with the user's request, wake word already stripped. */
  onRequest: (text: string) => void;
  /** Called when the local voice pipeline returns a completed response. */
  onResponse?: (request: string, content: string, speechText: string) => void;
  wakeWords?: readonly string[];
  wakeWordEnabled?: boolean;
  capabilities?: VoiceCapabilities | null;
}

export interface Voice {
  state: VoiceState;
  micStream: MediaStream | null;
  playbackAudio: HTMLAudioElement | null;
  supported: boolean;
  /** Interim transcript, so the user can see they are being heard. */
  transcript: string;
  lastWake: WakeEvent | null;
  error: string | null;
  speechEnabled: boolean;
  /** True when the backend is running local STT/TTS and the browser can use it. */
  localReady: boolean;
  toggleSpeech: () => void;
  /** Arm wake-word listening, or disarm it. */
  toggleArmed: () => void;
  /** Listen for one utterance, no wake word needed. */
  pushToTalk: () => void;
  stop: () => void;
  setThinking: (thinking: boolean) => void;
  speak: (text: string) => void;
}

type LocalMsg =
  | { type: "state"; state: VoiceState }
  | { type: "partial"; bytes: number }
  | { type: "transcript"; text: string; language: string }
  | { type: "response_text"; content: string; speech_text: string }
  | { type: "audio"; data?: string; sample_rate?: number; is_final?: boolean; error?: string }
  | { type: "wake"; phrase: string; confidence: number; detected_at: string }
  | { type: "error"; message: string };

function buildWavHeader(dataLength: number, sampleRate: number): ArrayBuffer {
  const buffer = new ArrayBuffer(44);
  const view = new DataView(buffer);
  const writeString = (offset: number, string: string) => {
    for (let i = 0; i < string.length; i += 1) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  };
  writeString(0, "RIFF");
  view.setUint32(4, 36 + dataLength, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, dataLength, true);
  return buffer;
}

function base64ToUint8Array(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

export function useVoice({
  onRequest,
  onResponse,
  wakeWords = DEFAULT_WAKE_WORDS,
  wakeWordEnabled = false,
  capabilities,
}: UseVoiceOptions): Voice {
  const [state, setState] = useState<VoiceState>("idle");
  const [transcript, setTranscript] = useState("");
  const transcriptRef = useRef("");
  const [lastWake, setLastWake] = useState<WakeEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [speechEnabled, setSpeechEnabled] = useState(false);
  const [micStream, setMicStream] = useState<MediaStream | null>(null);
  const [playbackAudio, setPlaybackAudio] = useState<HTMLAudioElement | null>(null);
  const localMicRef = useRef<MediaStream | null>(null);
  const localTurnRef = useRef(0);

  const setTranscriptWithRef = useCallback((value: string | ((prev: string) => string)) => {
    setTranscript((prev) => {
      const next = typeof value === "function" ? value(prev) : value;
      transcriptRef.current = next;
      return next;
    });
  }, []);

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const detector = useMemo(() => new TranscriptWakeWordDetector(wakeWords), [wakeWords]);
  const modeRef = useRef<"wake" | "push">("wake");
  const armedRef = useRef(false);
  const requestRef = useRef(onRequest);
  const responseRef = useRef(onResponse);
  requestRef.current = onRequest;
  responseRef.current = onResponse;

  // Capability is browser-only, so it cannot be read during render: the server
  // renders "unsupported" and the client would disagree, which is a hydration
  // mismatch. It resolves in an effect, after hydration.
  const [supported, setSupported] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(false);
  const [localReady, setLocalReady] = useState(false);

  useEffect(() => {
    setSupported(recognitionConstructor() !== null);
    setSpeechSupported(typeof window.speechSynthesis !== "undefined");
  }, []);

  useEffect(() => {
    const ready =
      capabilities?.local_ready === true &&
      capabilities.stt_backend === "local" &&
      capabilities.tts_backend === "local";
    setLocalReady(ready ?? false);
  }, [capabilities]);

  // --- browser speech synthesis ------------------------------------------------
  const speak = useCallback(
    (text: string) => {
      if (localReady || !speechEnabled || !speechSupported || text.trim() === "") return;

      window.speechSynthesis?.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1.05;
      utterance.onstart = () => setState("speaking");
      utterance.onend = () => setState(armedRef.current ? "armed" : "idle");
      window.speechSynthesis.speak(utterance);
    },
    [speechEnabled, speechSupported, localReady],
  );

  const toggleSpeech = useCallback(() => {
    setSpeechEnabled((enabled) => {
      if (enabled) window.speechSynthesis?.cancel();
      return !enabled;
    });
  }, []);

  // --- browser speech recognition ----------------------------------------------
  const stopRecognition = useCallback(() => {
    armedRef.current = false;
    recognitionRef.current?.abort();
    recognitionRef.current = null;
    detector.reset();
    setTranscriptWithRef("");
    setState("idle");
  }, [detector, setTranscriptWithRef]);

  const startRecognition = useCallback(
    (mode: "wake" | "push") => {
      const Recognition = recognitionConstructor();
      if (Recognition === null) {
        setError("This browser has no speech recognition. Type instead.");
        return;
      }

      recognitionRef.current?.abort();
      detector.reset();
      modeRef.current = mode;
      armedRef.current = true;
      setError(null);
      setTranscriptWithRef("");

      const recognition = new Recognition();
      recognition.continuous = mode === "wake";
      recognition.interimResults = true;
      recognition.lang = "en-US";

      recognition.onresult = (event) => {
        let interim = "";
        let final = "";
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const result = event.results[index];
          if (result.isFinal) final += result[0].transcript;
          else interim += result[0].transcript;
        }
        const heard = `${final}${interim}`;
        setTranscriptWithRef(heard);

        if (modeRef.current === "wake") {
          const wake = detector.feed(heard);
          if (wake !== null) {
            setLastWake(wake);
            setState("listening");
          }
        }

        if (final.trim() === "") return;

        const spoken =
          modeRef.current === "wake" ? stripWakeWord(final, detector.keywords) : final.trim();

        // In wake mode the keyword alone is an activation, not a request: keep
        // listening for what the user actually wants.
        if (spoken === "") {
          detector.reset();
          return;
        }

        setTranscriptWithRef("");
        detector.reset();
        setState("thinking");
        if (modeRef.current === "push") {
          recognition.stop();
        }
        requestRef.current(spoken);
      };

      recognition.onerror = (event) => {
        if (event.error === "no-speech" || event.error === "aborted") return;
        setError(
          event.error === "not-allowed"
            ? "Microphone permission denied. Allow it in the browser to talk to Ray."
            : `Speech recognition failed (${event.error}).`,
        );
        armedRef.current = false;
        setState("idle");
      };

      recognition.onend = () => {
        // Chrome ends the session after a pause; wake mode must stay armed.
        if (armedRef.current && modeRef.current === "wake") {
          try {
            recognition.start();
            return;
          } catch {
            // Restarting too quickly throws; fall through and disarm.
          }
        }
        armedRef.current = false;
        setState((current) => (current === "thinking" ? current : "idle"));
      };

      recognitionRef.current = recognition;
      try {
        recognition.start();
        setState(mode === "wake" ? "armed" : "listening");
      } catch {
        setError("Could not start the microphone.");
        setState("idle");
      }
    },
    [detector, setTranscriptWithRef],
  );

  // --- local WebSocket voice pipeline ------------------------------------------
  const wsRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioBufferRef = useRef<Uint8Array | null>(null);
  const audioSampleRateRef = useRef<number>(22_050);
  const pendingAudioRef = useRef<HTMLAudioElement | null>(null);

  const resetLocal = useCallback(() => {
    localTurnRef.current += 1;
    if (recorderRef.current?.state !== "inactive") {
      try {
        recorderRef.current?.stop();
      } catch {
        // Already stopped.
      }
    }
    recorderRef.current = null;
    localMicRef.current?.getTracks().forEach((track) => track.stop());
    localMicRef.current = null;
    setMicStream(null);
    if (wsRef.current) {
      wsRef.current.onclose = null;
      try {
        wsRef.current.close();
      } catch {
        // Already closed.
      }
    }
    wsRef.current = null;
    audioBufferRef.current = null;
    pendingAudioRef.current?.pause();
    if (pendingAudioRef.current) URL.revokeObjectURL(pendingAudioRef.current.src);
    pendingAudioRef.current = null;
    setPlaybackAudio(null);
  }, []);

  const playPcm = useCallback((pcm: Uint8Array, sampleRate: number) => {
    const header = buildWavHeader(pcm.length, sampleRate);
    const blob = new Blob([header, pcm], { type: "audio/wav" });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    pendingAudioRef.current = audio;
    setPlaybackAudio(audio);
    audio.onplay = () => setState("speaking");
    audio.onended = () => {
      setState(armedRef.current ? "armed" : "idle");
      URL.revokeObjectURL(url);
      pendingAudioRef.current = null;
      setPlaybackAudio(null);
    };
    audio.onerror = () => {
      URL.revokeObjectURL(url);
      pendingAudioRef.current = null;
      setPlaybackAudio(null);
      setState(armedRef.current ? "armed" : "idle");
    };
    void audio.play().catch(() => {
      URL.revokeObjectURL(url);
      setPlaybackAudio(null);
      setState("idle");
      setError("Audio playback was blocked. Try another microphone interaction.");
    });
  }, []);

  const handleLocalMessage = useCallback((message: LocalMsg) => {
    switch (message.type) {
      case "state":
        setState(message.state);
        break;
      case "transcript":
        setTranscriptWithRef(message.text);
        break;
      case "response_text": {
        setTranscriptWithRef("");
        responseRef.current?.(
          transcriptRef.current,
          message.content,
          message.speech_text ?? message.content,
        );
        break;
      }
      case "audio": {
        if (message.error) {
          setError(message.error);
          break;
        }
        if (message.data) {
          const pcm = base64ToUint8Array(message.data);
          if (message.sample_rate) audioSampleRateRef.current = message.sample_rate;
          audioBufferRef.current = audioBufferRef.current
            ? new Uint8Array([...audioBufferRef.current, ...pcm])
            : pcm;
        }
        if (message.is_final && audioBufferRef.current) {
          playPcm(audioBufferRef.current, audioSampleRateRef.current);
          audioBufferRef.current = null;
        }
        break;
      }
      case "wake": {
        setLastWake({
          keyword: message.phrase,
          confidence: message.confidence,
          at: new Date(message.detected_at).getTime(),
        });
        setState("listening");
        break;
      }
      case "error":
        setError(message.message);
        break;
      default:
        break;
    }
  }, [playPcm, setTranscriptWithRef]);

  const startLocalTurn = useCallback(async () => {
    if (typeof window === "undefined") return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("This browser cannot record microphone audio.");
      return;
    }

    resetLocal();
    const turn = localTurnRef.current;
    setError(null);
    setTranscriptWithRef("");
    audioBufferRef.current = null;

    let url: string;
    try {
      const maybeUrl = await getVoiceStreamUrl();
      if (!maybeUrl) {
        setError("Voice stream is not configured.");
        return;
      }
      url = maybeUrl;
    } catch {
      setError("Could not get a voice stream token.");
      return;
    }

    if (turn !== localTurnRef.current) return;

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Microphone permission denied.");
      return;
    }

    if (turn !== localTurnRef.current) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }

    const ws = new WebSocket(url);
    localMicRef.current = stream;
    setMicStream(stream);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    let started = false;
    const chunks: Blob[] = [];

    const recorder = new MediaRecorder(stream);
    recorderRef.current = recorder;

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };

    recorder.onstop = async () => {
      if (ws.readyState === WebSocket.OPEN) {
        const blob = new Blob(chunks, { type: recorder.mimeType });
        const buffer = await blob.arrayBuffer();
        ws.send(buffer);
        ws.send(JSON.stringify({ type: "stop" }));
      }
      stream.getTracks().forEach((track) => track.stop());
      if (localMicRef.current === stream) setMicStream(null);
    };

    ws.onopen = () => {
      started = true;
      ws.send(JSON.stringify({ type: "start" }));
      // 100 ms slices keep the HUD partial counter moving without fragmenting
      // the webm too much.
      recorder.start(100);
      setState("listening");
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string) as LocalMsg;
        handleLocalMessage(data);
      } catch {
        // Ignore binary or malformed frames.
      }
    };

    ws.onerror = () => {
      setError("Voice stream failed. Falling back to browser speech.");
      resetLocal();
      setLocalReady(false);
    };

    ws.onclose = () => {
      if (!started) {
        setError("Voice stream closed before it opened.");
      }
      resetLocal();
      setState(armedRef.current ? "armed" : "idle");
    };
  }, [resetLocal, handleLocalMessage, setTranscriptWithRef]);

  const stopLocalTurn = useCallback(() => {
    if (recorderRef.current?.state === "recording") {
      recorderRef.current.stop();
    } else {
      resetLocal();
    }
    setState("thinking");
  }, [resetLocal]);

  const bargeLocal = useCallback(() => {
    pendingAudioRef.current?.pause();
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "barge" }));
    }
    resetLocal();
    void startLocalTurn();
  }, [resetLocal, startLocalTurn]);

  // --- public controls ---------------------------------------------------------
  const stop = useCallback(() => {
    window.speechSynthesis?.cancel();
    if (localReady) {
      resetLocal();
      setState("idle");
    } else {
      stopRecognition();
    }
  }, [localReady, resetLocal, stopRecognition]);

  const toggleArmed = useCallback(() => {
    window.speechSynthesis?.cancel();
    if (localReady) {
      if (state === "idle" || state === "armed") {
        void startLocalTurn();
      } else {
        stopLocalTurn();
      }
      return;
    }
    if (state === "idle") startRecognition("wake");
    else stopRecognition();
  }, [localReady, startLocalTurn, stopLocalTurn, startRecognition, stopRecognition, state]);

  const pushToTalk = useCallback(() => {
    window.speechSynthesis?.cancel();
    if (localReady) {
      if (state === "speaking") {
        bargeLocal();
      } else if (state === "listening" || state === "thinking") {
        stopLocalTurn();
      } else {
        void startLocalTurn();
      }
      return;
    }
    if (state === "speaking") {
      // Barge in on a spoken reply and start a fresh push-to-talk turn.
      window.speechSynthesis?.cancel();
      setState("idle");
      startRecognition("push");
    } else if (state === "listening") {
      stopRecognition();
    } else {
      startRecognition("push");
    }
  }, [localReady, bargeLocal, stopLocalTurn, startLocalTurn, startRecognition, stopRecognition, state]);

  const setThinking = useCallback((thinking: boolean) => {
    if (thinking) {
      setState("thinking");
    } else {
      setState((current) => {
        if (current === "thinking") return armedRef.current ? "armed" : "idle";
        return current;
      });
    }
  }, []);

  // Arming needs a user gesture for microphone permission, so a backend that
  // reports wake word enabled cannot auto-arm; it only makes the affordance the
  // primary one.
  useEffect(() => {
    if (!wakeWordEnabled) return;
    setError(null);
  }, [wakeWordEnabled]);

  useEffect(() => stop, [stop]);

  return {
    state,
    micStream,
    playbackAudio,
    supported: supported || canUseLocalVoice(localReady, typeof MediaRecorder !== "undefined", typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia),
    transcript,
    lastWake,
    error,
    speechEnabled: speechEnabled && speechSupported,
    localReady,
    toggleSpeech,
    toggleArmed,
    pushToTalk,
    stop,
    setThinking,
    speak,
  };
}
