"use client";

import { useEffect, useRef, useState } from "react";
import type { VoiceState } from "@/hooks/use-voice";
import { smoothLevel } from "@/lib/hud";

export function useAudioLevel(state: VoiceState, stream: MediaStream | null, audio: HTMLAudioElement | null) {
  const [level, setLevel] = useState(0);
  const contextRef = useRef<AudioContext | null>(null);
  const sources = useRef(new WeakMap<HTMLAudioElement, MediaElementAudioSourceNode>());

  useEffect(() => {
    if (state !== "armed" && state !== "listening" && state !== "speaking") {
      setLevel(0);
      return;
    }
    let disposed = false;
    let frame = 0;
    let ownedStream: MediaStream | null = null;
    let source: AudioNode | null = null;
    let analyser: AnalyserNode | null = null;
    let current = 0;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const connect = async () => {
      try {
        const input = state === "speaking" ? null : stream ?? await navigator.mediaDevices.getUserMedia({ audio: true });
        if (!stream) ownedStream = input;
        if (disposed) { ownedStream?.getTracks().forEach((track) => track.stop()); return; }
        if (!input && !audio) return;
        const context = contextRef.current ?? new AudioContext();
        contextRef.current = context;
        await context.resume();
        if (disposed) return;
        analyser = context.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = .7;
        if (input) source = context.createMediaStreamSource(input);
        else if (audio) {
          source = sources.current.get(audio) ?? context.createMediaElementSource(audio);
          sources.current.set(audio, source as MediaElementAudioSourceNode);
          source.connect(context.destination);
        }
        source?.connect(analyser);
      } catch {
        // Metering must never prevent voice use if Web Audio or permission fails.
      }
    };
    void connect();
    const data = new Uint8Array(256);
    const tick = (time: number) => {
      let target = 0;
      if (analyser) {
        analyser.getByteTimeDomainData(data);
        target = Math.min(1, Math.sqrt(data.reduce((sum, value) => sum + ((value - 128) / 128) ** 2, 0) / data.length) * 4);
      } else if (state === "speaking") {
        target = reduced ? .2 : .18 + .22 * Math.abs(Math.sin(time / 137) * Math.sin(time / 311));
      }
      current = smoothLevel(current, target);
      setLevel(current);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      source?.disconnect();
      analyser?.disconnect();
      ownedStream?.getTracks().forEach((track) => track.stop());
    };
  }, [state, stream, audio]);

  useEffect(() => () => { void contextRef.current?.close(); contextRef.current = null; }, []);
  return level;
}
