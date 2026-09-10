import { ApprovalQueue } from "@/components/approval-queue";
import { Conversation } from "@/components/conversation";
import { DashboardProvider } from "@/components/dashboard-context";
import {
  AgentPanel,
  LearningPanel,
  MemoryPanel,
  ProjectPanel,
  SchedulePanel,
  TaskPanel,
  WorkflowPanel,
} from "@/components/panels";
import { StatusBar } from "@/components/status-bar";
import {
  getDashboard,
  getHealth,
  getRecentConversation,
  getWorkflows,
  type DashboardSummary,
  type Health,
} from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const [health, dashboard, conversation, workflows] = await Promise.all([
    getHealth(),
    safeDashboard(),
    getRecentConversation(),
    getWorkflows().catch(() => []),
  ]);

  if (dashboard === null) {
    return <BackendUnavailable health={health} />;
  }

  return (
    <DashboardProvider health={health} user={dashboard.user}>
      <main className="flex h-screen flex-col">
        <StatusBar />

        <div className="px-4 pt-4">
          <ApprovalQueue />
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 p-4 lg:grid-cols-[1fr_360px]">
          <Conversation
            health={health}
            userName={dashboard.user?.name ?? "there"}
            restored={conversation}
          />

          {/* The panel rail: everything Ray knows, always visible (docs/09). */}
          <aside className="grid min-h-0 grid-rows-[1.2fr_0.8fr_0.8fr_1.2fr_0.8fr_0.8fr_0.8fr] gap-4 overflow-y-auto">
            <TaskPanel tasks={dashboard.tasks} overdue={dashboard.overdue_count} />
            <SchedulePanel events={dashboard.today_events} />
            <ProjectPanel projects={dashboard.projects} />
            <MemoryPanel memories={dashboard.memories} />
            <LearningPanel memories={dashboard.memories} />
            <WorkflowPanel workflows={workflows} />
            <AgentPanel agents={dashboard.agents} />
          </aside>
        </div>
      </main>
    </DashboardProvider>
  );
}

async function safeDashboard(): Promise<DashboardSummary | null> {
  try {
    return await getDashboard();
  } catch {
    return null;
  }
}

function BackendUnavailable({ health }: { health: Health | null }) {
  return (
    <main className="flex h-screen flex-col items-center justify-center gap-4 text-center">
      <span className="font-mono text-2xl tracking-[0.3em] text-hud-accent">RAY</span>
      <p className="text-hud-text">Ray&apos;s backend is not reachable.</p>
      <pre className="rounded-md border border-hud-border bg-hud-panel px-5 py-3 text-left text-xs text-hud-muted">
        {`docker compose up -d
cd backend
uv run alembic upgrade head
uv run python scripts/seed.py
uv run uvicorn ray.main:app --reload`}
      </pre>
      <p className="text-xs text-hud-muted">
        {health === null
          ? "No response from the API. Check RAY_API_URL."
          : "API is up but the request was rejected — check RAY_API_TOKEN matches the backend."}
      </p>
    </main>
  );
}
