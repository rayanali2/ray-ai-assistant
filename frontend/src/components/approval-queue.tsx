"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { useDashboard } from "@/components/dashboard-context";
import type { components } from "@/lib/api-types";

/**
 * Pending tool approvals that need a human decision (ADR-0014).
 *
 * The list is fetched once by the dashboard context and refreshed after every
 * decision, so the status bar and reactor stay in sync with the queue.
 */
export function ApprovalQueue() {
  const router = useRouter();
  const { approvals, refreshApprovals, pendingApprovals } = useDashboard();
  const [acting, setActing] = useState<Set<string>>(new Set());

  if (pendingApprovals === 0) return null;

  async function decide(id: string, action: "approve" | "reject", alwaysAllow = false) {
    setActing((prev) => new Set(prev).add(id));
    try {
      const response = await fetch(`/api/approvals/${id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ always_allow: alwaysAllow }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: "Failed" }));
        alert(String(error.detail ?? "Failed"));
      } else {
        router.refresh();
      }
      await refreshApprovals();
    } finally {
      setActing((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }

  return (
    <section className="rounded-lg border border-hud-warn/30 bg-hud-panel/60 p-4">
      <h3 className="mb-3 font-mono text-[11px] uppercase tracking-widest text-hud-warn">
        Pending approvals
      </h3>
      <ul className="space-y-3">
        {approvals.map((item) => (
          <ApprovalItem key={String(item.id)} item={item} acting={acting} onDecide={decide} />
        ))}
      </ul>
    </section>
  );
}

function ApprovalItem({
  item,
  acting,
  onDecide,
}: {
  item: components["schemas"]["ToolInvocationRead"];
  acting: Set<string>;
  onDecide: (id: string, action: "approve" | "reject", alwaysAllow?: boolean) => void;
}) {
  return (
    <li className="rounded border border-hud-border p-3">
      <p className="text-sm text-hud-text">
        <span className="font-medium">{item.tool_name}</span>
      </p>
      <pre className="mt-2 overflow-x-auto rounded bg-hud-bg p-2 font-mono text-[11px] text-hud-muted">
        {JSON.stringify(item.payload, null, 2)}
      </pre>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={acting.has(String(item.id))}
          onClick={() => onDecide(String(item.id), "approve")}
          className="rounded bg-hud-accent px-3 py-1.5 text-xs font-medium text-hud-bg transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          Approve
        </button>
        <button
          type="button"
          disabled={acting.has(String(item.id))}
          onClick={() => onDecide(String(item.id), "reject")}
          className="rounded border border-hud-border px-3 py-1.5 text-xs font-medium text-hud-muted transition-colors hover:text-hud-text disabled:opacity-50"
        >
          Reject
        </button>
        {item.side_effect && (
          <button
            type="button"
            disabled={acting.has(String(item.id))}
            onClick={() => onDecide(String(item.id), "approve", true)}
            className="rounded border border-hud-border px-3 py-1.5 text-xs font-medium text-hud-muted transition-colors hover:text-hud-text disabled:opacity-50"
          >
            Always allow
          </button>
        )}
      </div>
    </li>
  );
}
