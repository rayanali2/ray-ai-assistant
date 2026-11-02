import React, { Children, isValidElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApprovalQueue } from "./approval-queue";

const { refresh, refreshApprovals, dashboard } = vi.hoisted(() => ({
  refresh: vi.fn(),
  refreshApprovals: vi.fn().mockResolvedValue(undefined),
  dashboard: {
    pendingApprovals: 1,
    approvals: [{ id: "pending-task", tool_name: "tasks.create", payload: {}, side_effect: true }],
  },
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/components/dashboard-context", () => ({
  useDashboard: () => ({ ...dashboard, refreshApprovals }),
}));
vi.mock("react", async (importOriginal) => ({
  ...await importOriginal<typeof import("react")>(),
  useState: () => [new Set<string>(), vi.fn()],
}));

type Decide = (id: string, action: "approve" | "reject", alwaysAllow?: boolean) => Promise<void>;

function findDecision(node: ReactNode): Decide | undefined {
  for (const child of Children.toArray(node)) {
    if (!isValidElement<{ children?: ReactNode; onDecide?: Decide }>(child)) continue;
    const decide = child.props.onDecide ?? findDecision(child.props.children);
    if (decide) return decide;
  }
}

function decision() {
  const decide = findDecision(ApprovalQueue());
  if (!decide) throw new Error("Expected a pending approval decision handler");
  return decide;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("React", React);
  dashboard.pendingApprovals = 1;
});
afterEach(() => vi.unstubAllGlobals());

describe("approval dashboard refresh", () => {
  it.each(["approve", "reject"] as const)("refreshes all server panels after %s resolves", async (action) => {
    let resolve!: (response: Response) => void;
    const fetcher = vi.fn().mockReturnValue(new Promise<Response>((done) => { resolve = done; }));
    vi.stubGlobal("fetch", fetcher);
    const pending = decision()("pending-task", action);
    expect(refresh).not.toHaveBeenCalled();
    resolve(Response.json({ status: action === "approve" ? "executed" : "rejected" }));
    await pending;
    expect(fetcher).toHaveBeenCalledWith(`/api/approvals/pending-task/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ always_allow: false }),
    });
    expect(refresh).toHaveBeenCalledOnce();
    expect(refreshApprovals).toHaveBeenCalledOnce();
  });

  it("also refreshes after an always-allow approval", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ status: "executed" }));
    vi.stubGlobal("fetch", fetcher);
    await decision()("pending-task", "approve", true);
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ always_allow: true });
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("does not refresh server panels when the decision fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: "Not found" }, { status: 404 })));
    const alert = vi.fn();
    vi.stubGlobal("alert", alert);
    await decision()("pending-task", "approve");
    expect(alert).toHaveBeenCalledWith("Not found");
    expect(refresh).not.toHaveBeenCalled();
    expect(refreshApprovals).toHaveBeenCalledOnce();
  });

  it("does not refresh when the request cannot reach the backend", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Offline")));
    await expect(decision()("pending-task", "approve")).rejects.toThrow("Offline");
    expect(refresh).not.toHaveBeenCalled();
  });

  it("renders nothing and makes no requests for an empty queue", () => {
    dashboard.pendingApprovals = 0;
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    expect(ApprovalQueue()).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
  });
});
