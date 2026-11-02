import type { ReactNode } from "react";

/**
 * The HUD's one container. Every panel shares a frame so the dashboard reads as
 * a single instrument rather than a page of cards.
 */
export function Panel({
  title,
  badge,
  children,
  className = "",
}: {
  title: string;
  badge?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`hud-frame flex flex-col border border-hud-border bg-hud-panel/70 backdrop-blur-sm ${className}`}
    >
      <header className="flex items-center justify-between border-b border-hud-border px-4 py-2.5">
        <h2 className="hud-heading font-mono text-[11px] uppercase tracking-[0.18em] text-hud-accent">
          {title}
        </h2>
        {badge}
      </header>
      <div className="flex-1 overflow-y-auto p-4">{children}</div>
    </section>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-hud-muted">{children}</p>;
}

export function Count({ value, tone = "accent" }: { value: number; tone?: "accent" | "danger" }) {
  const color = tone === "danger" ? "text-hud-danger" : "text-hud-accent";
  return <span className={`font-mono text-xs ${color}`}>{value}</span>;
}
