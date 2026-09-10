import Link from "next/link";

import { DashboardProvider } from "@/components/dashboard-context";
import { StatusBar } from "@/components/status-bar";
import { getDashboard, getHealth, getWorkflows } from "@/lib/api";

import { WorkflowsView } from "./workflows-view";

export const dynamic = "force-dynamic";

export default async function WorkflowsPage() {
  const [health, dashboard, workflows] = await Promise.all([
    getHealth(),
    getDashboard().catch(() => null),
    getWorkflows().catch(() => []),
  ]);

  if (dashboard === null) {
    return <BackendUnavailable health={health} />;
  }

  return (
    <DashboardProvider health={health} user={dashboard.user}>
      <main className="flex h-screen flex-col">
        <StatusBar />
        <div className="flex-1 overflow-y-auto p-4 lg:p-6">
          <WorkflowsView workflows={workflows} />
        </div>
      </main>
    </DashboardProvider>
  );
}

function BackendUnavailable({ health }: { health: { status: string } | null }) {
  return (
    <main className="flex h-screen flex-col items-center justify-center gap-4 text-center">
      <span className="font-mono text-2xl tracking-[0.3em] text-hud-accent">RAY</span>
      <p className="text-hud-text">Ray&apos;s backend is not reachable.</p>
      <p className="text-xs text-hud-muted">
        {health === null
          ? "No response from the API. Check RAY_API_URL."
          : "API is up but the request was rejected — check RAY_API_TOKEN matches the backend."}
      </p>
      <Link href="/" className="text-sm text-hud-accent hover:underline">
        Back to dashboard
      </Link>
    </main>
  );
}
