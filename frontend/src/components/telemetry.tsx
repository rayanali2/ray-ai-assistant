"use client";

import { useEffect, useState } from "react";
import { useDashboard } from "@/components/dashboard-context";
import type { Health } from "@/lib/api";

export function Telemetry() {
  const { health } = useDashboard();
  const [liveHealth, setLiveHealth] = useState<Health | null>(health);
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const refresh = async () => {
      try {
        const response = await fetch("/api/health", { cache: "no-store", signal: controller.signal });
        const latest = response.ok ? await response.json() as Health : null;
        if (!controller.signal.aborted) setLiveHealth(latest);
      } catch { if (!controller.signal.aborted) setLiveHealth(null); }
    };
    const timer = setInterval(() => void refresh(), 15_000);
    return () => { clearInterval(timer); controller.abort(); };
  }, []);
  return (
    <div className="telemetry-strip">
      <span className="text-hud-accent">◈ SYSTEM TELEMETRY <span className="telemetry-divider">/</span> RAY.OS</span>
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        <span>CORE <b className={liveHealth?.status === "ok" ? "text-hud-accent" : "text-hud-warn"}>{liveHealth?.status === "ok" ? "ONLINE" : "OFFLINE"}</b></span>
        <span>MODEL <b>{liveHealth?.llm_provider ?? "UNAVAILABLE"}</b></span>
        {liveHealth?.llm_provider === "mock" && <span className="text-hud-warn" role="status">CANNED REPLIES — add a Gemini key in desktop Preferences or configure Ollama</span>}
        <span>MEM <b>{liveHealth?.database ?? "UNKNOWN"}</b></span>
        <time dateTime={now?.toISOString()}>{now ? `${now.toLocaleDateString(undefined, { month: "short", day: "2-digit" })} / ${now.toLocaleTimeString([], { hour12: false })}` : "SYNCING CLOCK"}</time>
      </div>
    </div>
  );
}
