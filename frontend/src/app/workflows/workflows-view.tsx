"use client";

import { useState } from "react";

import type { Workflow } from "@/lib/api";

type WorkflowCreate = {
  name: string;
  description: string;
  prompt: string;
  interval_minutes: number;
  enabled: boolean;
};

export function WorkflowsView({ workflows: initial }: { workflows: Workflow[] }) {
  const [workflows, setWorkflows] = useState<Workflow[]>(initial);
  const [form, setForm] = useState<WorkflowCreate>({
    name: "",
    description: "",
    prompt: "",
    interval_minutes: 60,
    enabled: true,
  });
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const response = await fetch("/api/workflows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    if (!response.ok) {
      setError(`Create failed: ${response.status}`);
      return;
    }
    const created = (await response.json()) as Workflow;
    setWorkflows((prev) => [...prev, created]);
    setForm({ name: "", description: "", prompt: "", interval_minutes: 60, enabled: true });
  }

  async function run(workflowId: string) {
    setRunning(workflowId);
    setError(null);
    try {
      const response = await fetch(`/api/workflows/${workflowId}/run`, { method: "POST" });
      if (!response.ok) {
        setError(`Run failed: ${response.status}`);
        return;
      }
      const summary = (await response.json()) as { success: boolean; output: string; error: string };
      if (!summary.success) {
        setError(summary.error || "Workflow paused for approval or failed.");
      }
      // Refresh the list so the new run and next_run_at are visible.
      const list = await fetch("/api/workflows", { cache: "no-store" });
      if (list.ok) {
        setWorkflows((await list.json()) as Workflow[]);
      }
    } finally {
      setRunning(null);
    }
  }

  return (
    <section className="mx-auto max-w-3xl space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="font-mono text-xs uppercase tracking-[0.18em] text-hud-muted">Workflows</h1>
        <span className="font-mono text-xs text-hud-accent">{workflows.length} active</span>
      </div>

      {error !== null && (
        <p className="rounded border border-hud-danger/30 bg-hud-danger/10 px-3 py-2 text-sm text-hud-danger">
          {error}
        </p>
      )}

      <form
        onSubmit={create}
        className="space-y-3 rounded-lg border border-hud-border bg-hud-panel/70 p-4"
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <input
            type="text"
            required
            placeholder="Name"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            className="rounded border border-hud-border bg-hud-bg px-3 py-2 text-sm text-hud-text placeholder:text-hud-muted focus:border-hud-accent focus:outline-none"
          />
          <input
            type="number"
            min={1}
            required
            placeholder="Interval (minutes)"
            value={form.interval_minutes}
            onChange={(e) => setForm((f) => ({ ...f, interval_minutes: Number(e.target.value) }))}
            className="rounded border border-hud-border bg-hud-bg px-3 py-2 text-sm text-hud-text placeholder:text-hud-muted focus:border-hud-accent focus:outline-none"
          />
        </div>
        <input
          type="text"
          placeholder="Description (optional)"
          value={form.description}
          onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
          className="w-full rounded border border-hud-border bg-hud-bg px-3 py-2 text-sm text-hud-text placeholder:text-hud-muted focus:border-hud-accent focus:outline-none"
        />
        <textarea
          required
          rows={3}
          placeholder="Prompt Ray will run on each cycle..."
          value={form.prompt}
          onChange={(e) => setForm((f) => ({ ...f, prompt: e.target.value }))}
          className="w-full rounded border border-hud-border bg-hud-bg px-3 py-2 text-sm text-hud-text placeholder:text-hud-muted focus:border-hud-accent focus:outline-none"
        />
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 text-sm text-hud-muted">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
              className="accent-hud-accent"
            />
            Enabled
          </label>
          <button
            type="submit"
            className="rounded bg-hud-accent px-4 py-2 text-sm font-medium text-hud-bg hover:bg-hud-accent/90"
          >
            Add workflow
          </button>
        </div>
      </form>

      {workflows.length === 0 ? (
        <p className="text-center text-sm text-hud-muted">No workflows yet.</p>
      ) : (
        <ul className="space-y-3">
          {workflows.map((workflow) => (
            <li
              key={workflow.id}
              className="rounded-lg border border-hud-border bg-hud-panel/70 p-4"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span
                      className={`h-2 w-2 rounded-full ${workflow.enabled ? "bg-hud-accent" : "bg-hud-muted"}`}
                    />
                    <h2 className="truncate text-sm font-medium text-hud-text">{workflow.name}</h2>
                  </div>
                  {workflow.description ? (
                    <p className="mt-1 text-xs text-hud-muted">{workflow.description}</p>
                  ) : null}
                  <p className="mt-2 font-mono text-xs text-hud-accent/80 line-clamp-3">
                    {workflow.prompt}
                  </p>
                  <p className="mt-2 text-xs text-hud-muted">
                    Every {workflow.interval_minutes} min &middot; next run{" "}
                    {new Date(workflow.next_run_at).toLocaleString()}
                  </p>
                </div>
                <button
                  onClick={() => run(workflow.id)}
                  disabled={running === workflow.id}
                  className="shrink-0 rounded border border-hud-border bg-hud-bg px-3 py-1.5 text-xs text-hud-text hover:border-hud-accent hover:text-hud-accent disabled:opacity-50"
                >
                  {running === workflow.id ? "Running..." : "Run now"}
                </button>
              </div>

              {workflow.runs.length > 0 && (
                <div className="mt-3 border-t border-hud-border pt-3">
                  <p className="text-xs text-hud-muted">Last run</p>
                  {workflow.runs.slice(0, 1).map((run) => (
                    <div key={run.id} className="mt-1 text-sm">
                      <span
                        className={`font-mono text-[10px] uppercase ${run.success ? "text-hud-accent" : "text-hud-danger"}`}
                      >
                        {run.success ? "success" : "failed"}
                      </span>
                      <p className="mt-1 line-clamp-2 text-xs text-hud-text">
                        {run.output || run.error}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
