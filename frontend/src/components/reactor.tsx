"use client";

import { useId, type CSSProperties } from "react";
import type { VoiceState } from "@/hooks/use-voice";

export type ReactorState = VoiceState | "approval";

interface ReactorProps {
  state: ReactorState;
  className?: string;
  level?: number;
}

const LABEL: Record<ReactorState, string> = {
  idle: "Idle",
  armed: "Armed",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
  approval: "Approval needed",
};

export function Reactor({ state, level = 0, className = "" }: ReactorProps) {
  const id = useId().replaceAll(":", "");
  const amplitude = Number.isFinite(level) ? Math.max(0, Math.min(1, level)) : 0;
  return (
    <div
      className={`reactor reactor-${state} ${className}`}
      style={{ "--level": amplitude } as CSSProperties}
      role="img"
      aria-label={`Ray is ${LABEL[state]}`}
    >
      <svg viewBox="0 0 400 400" aria-hidden="true" className="reactor-svg">
        <defs>
          <radialGradient id={`${id}-core`}>
            <stop offset="0" stopColor="#fffdf1" />
            <stop offset=".3" stopColor="currentColor" stopOpacity=".9" />
            <stop offset="1" stopColor="currentColor" stopOpacity="0" />
          </radialGradient>
          <linearGradient id={`${id}-sweep`} x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="currentColor" stopOpacity="0" />
            <stop offset="1" stopColor="currentColor" stopOpacity=".18" />
          </linearGradient>
        </defs>
        <circle cx="200" cy="200" r="187" fill="none" stroke="currentColor" opacity=".12" />
        <g className="reactor-rotation reactor-slow" stroke="currentColor">
          {Array.from({ length: 120 }, (_, i) => (
            <line key={i} x1="200" y1={i % 10 === 0 ? 14 : 20} x2="200" y2="25"
              strokeWidth={i % 10 === 0 ? 1.5 : .6} opacity={i % 10 === 0 ? .8 : .3}
              transform={`rotate(${i * 3} 200 200)`} />
          ))}
        </g>
        <g fill="currentColor" fontSize="7" fontFamily="monospace" textAnchor="middle" opacity=".65">
          <text x="200" y="42">000</text><text x="359" y="203">090</text>
          <text x="200" y="365">180</text><text x="40" y="203">270</text>
        </g>
        <g className="reactor-rotation reactor-sweep">
          <path d="M200 200 L200 44 A156 156 0 0 1 356 200 Z" fill={`url(#${id}-sweep)`} />
          <line x1="200" y1="200" x2="356" y2="200" stroke="currentColor" opacity=".2" />
        </g>
        <g fill="none" stroke="currentColor">
          <circle className="reactor-rotation reactor-ring-outer" cx="200" cy="200" r="155"
            strokeWidth="7" strokeDasharray="92 12 6 12 40 18" opacity=".6" />
          <circle cx="200" cy="200" r="144" strokeWidth=".6" opacity=".4" />
          <circle className="reactor-rotation reactor-ring-inner" cx="200" cy="200" r="132"
            strokeWidth="2" strokeDasharray="45 9 3 9" opacity=".8" />
          <circle className="reactor-rotation reactor-slow" cx="200" cy="200" r="116"
            strokeWidth="9" strokeDasharray="2 12" opacity=".18" />
          <circle cx="200" cy="200" r="83" strokeWidth="1" opacity=".35" />
          <g className="reactor-spectrum" strokeWidth="2.5" strokeLinecap="round">
            {Array.from({ length: 64 }, (_, i) => {
              const height = 3 + amplitude * (8 + 21 * Math.abs(Math.sin(i * 1.73)));
              return <line key={i} x1="200" y1="107" x2="200" y2={107 - height}
                transform={`rotate(${i * 360 / 64} 200 200)`} opacity={.35 + amplitude * .6} />;
            })}
          </g>
          <g className="reactor-rotation reactor-orbits">
            {[0, 120, 240].map((angle) => <circle key={angle} cx="200" cy="68" r="3"
              fill="currentColor" transform={`rotate(${angle} 200 200)`} />)}
          </g>
        </g>
        <g className="reactor-energy">
          <circle cx="200" cy="200" r="80" fill={`url(#${id}-core)`} />
          <circle cx="200" cy="200" r="53" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M200 161 L234 220 H166 Z" fill="currentColor" fillOpacity=".1" stroke="currentColor" strokeWidth="2" />
          <path d="M200 174 L222 213 H178 Z" fill="#f4ffff" opacity=".8" />
        </g>
        <g stroke="currentColor" opacity=".25" strokeWidth=".7">
          <path d="M0 200H35 M365 200H400 M200 0V10 M200 390V400" />
          <path d="M52 52h20 M52 52v20 M348 52h-20 M348 52v20 M52 348h20 M52 348v-20 M348 348h-20 M348 348v-20" />
        </g>
      </svg>
      <span className="reactor-label font-mono text-[10px] uppercase tracking-[0.2em]">
        {LABEL[state]}
      </span>
    </div>
  );
}
