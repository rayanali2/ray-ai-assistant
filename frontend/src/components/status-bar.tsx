"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { useDashboard } from "@/components/dashboard-context";

const VOICE_LABEL: Record<string, string> = {
  idle: "Idle",
  armed: "Armed",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
};

/**
 * Top bar: who Ray is talking to, and whether Ray is actually working.
 *
 * It reads live state from the dashboard context so the status bar reflects the
 * current voice state, active agent, and pending approvals without requiring a
 * page refresh (docs/09).
 */
export function StatusBar() {
  const { health, user, voiceState, agentName, pendingApprovals } = useDashboard();
  const online = health?.status === "ok";

  return (
    <header className="flex items-center justify-between border-b border-hud-border bg-hud-panel/50 px-6 py-3">
      <div className="flex items-baseline gap-3">
        <Link href="/" className="font-mono text-lg tracking-[0.3em] text-hud-accent">
          RAY
        </Link>
        <span className="hidden text-sm text-hud-muted sm:inline">
          {user ? `${user.name}'s assistant` : "No user seeded"}
        </span>
      </div>

      <nav className="hidden items-center gap-4 text-xs text-hud-muted lg:flex">
        <NavLink href="/projects">Projects</NavLink>
        <NavLink href="/tasks">Tasks</NavLink>
        <NavLink href="/calendar">Calendar</NavLink>
        <NavLink href="/workflows">Workflows</NavLink>
        <NavLink href="/memory">Memory</NavLink>
        <NavLink href="/settings">Settings</NavLink>
      </nav>

      <div className="flex items-center gap-4 font-mono text-[11px] uppercase tracking-widest">
        {agentName !== undefined && (
          <Indicator label={agentName} state="ok" title="Active agent for the last turn" />
        )}
        {voiceState !== "idle" && (
          <Indicator label={VOICE_LABEL[voiceState] ?? voiceState} state="ok" pulse />
        )}
        {pendingApprovals > 0 && (
          <Indicator label={`${pendingApprovals} approval${pendingApprovals > 1 ? "s" : ""}`} state="warn" pulse />
        )}
        <Indicator label={health?.llm_provider ?? "no provider"} state={online ? "ok" : "off"} />
        <Indicator label={`db ${health?.database ?? "unknown"}`} state={online ? "ok" : "error"} />
        <Indicator label={online ? "online" : "offline"} state={online ? "ok" : "error"} pulse={online} />
      </div>
    </header>
  );
}

function NavLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="uppercase tracking-widest transition-colors hover:text-hud-accent">
      {children}
    </Link>
  );
}

function Indicator({
  label,
  state,
  pulse = false,
  title,
}: {
  label: string;
  state: "ok" | "off" | "error" | "warn";
  pulse?: boolean;
  title?: string;
}) {
  const color =
    state === "ok"
      ? "bg-hud-accent"
      : state === "error"
        ? "bg-hud-danger"
        : state === "warn"
          ? "bg-hud-warn"
          : "bg-hud-muted";
  return (
    <span className="flex items-center gap-2 text-hud-muted" title={title}>
      <span className={`h-1.5 w-1.5 rounded-full ${color} ${pulse ? "hud-pulse" : ""}`} />
      {label}
    </span>
  );
}
