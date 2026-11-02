"use client";

import { useEffect, useRef, useState } from "react";
import { Reactor } from "@/components/reactor";
import type { Health } from "@/lib/api";

export function BootSequence({ health, agentCount }: { health: Health | null; agentCount: number }) {
  const [visible, setVisible] = useState(false);
  const started = useRef(false);
  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    try {
      if (sessionStorage.getItem("ray-hud-booted") && !started.current) return;
      sessionStorage.setItem("ray-hud-booted", "1");
      started.current = true;
    } catch { /* Private browsing may disable session storage. */ }
    if (reduced.matches) return;
    setVisible(true);
    const skip = () => setVisible(false);
    const timer = window.setTimeout(skip, 2500);
    window.addEventListener("keydown", skip);
    reduced.addEventListener("change", skip);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", skip);
      reduced.removeEventListener("change", skip);
    };
  }, []);

  if (!visible) return null;
  return (
    <button type="button" className="boot-overlay" onClick={() => setVisible(false)} aria-label="Skip Ray initialization">
      <span className="boot-overline">RAY / PERSONAL INTELLIGENCE SYSTEM</span>
      <Reactor state="thinking" className="boot-reactor" />
      <span className="boot-title">Initializing Ray…</span>
      <span className="boot-line" style={{ animationDelay: ".3s" }}>
        {health?.database === "connected" ? "Memory core online" : "Memory core awaiting connection"}
      </span>
      <span className="boot-line" style={{ animationDelay: ".8s" }}>
        {agentCount > 0 ? `${agentCount} agents online` : "Agent registry awaiting connection"}
      </span>
      <span className="boot-line" style={{ animationDelay: "1.2s" }}>
        {health?.status === "ok" ? `Uplink established / ${health.llm_provider}` : "Backend uplink unavailable"}
      </span>
      <span className="boot-progress" />
      <span className="boot-skip">CLICK OR PRESS ANY KEY TO CONTINUE</span>
    </button>
  );
}
