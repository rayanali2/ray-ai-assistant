import Link from "next/link";

import type { Agent, CalendarEvent, Memory, Project, Task, Workflow } from "@/lib/api";

import { Count, EmptyState, Panel } from "@/components/panel";

const PRIORITY_COLOR: Record<Task["priority"], string> = {
  urgent: "text-hud-danger",
  high: "text-hud-warn",
  medium: "text-hud-muted",
  low: "text-hud-muted",
};

const STATUS_COLOR: Record<Project["status"] | Task["status"], string> = {
  planning: "text-hud-warn",
  active: "text-hud-accent",
  paused: "text-hud-muted",
  complete: "text-hud-accent",
  archived: "text-hud-muted",
  todo: "text-hud-muted",
  in_progress: "text-hud-accent",
  blocked: "text-hud-warn",
  done: "text-hud-accent",
  cancelled: "text-hud-danger",
};

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDeadline(iso: string): string {
  const date = new Date(iso);
  const days = Math.round((date.getTime() - Date.now()) / 86_400_000);
  if (days < 0) return `${Math.abs(days)}d overdue`;
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  return `${days}d`;
}

export function TaskPanel({ tasks, overdue }: { tasks: Task[]; overdue: number }) {
  return (
    <Panel
      title="Tasks"
      badge={
        overdue > 0 ? <Count value={overdue} tone="danger" /> : <Count value={tasks.length} />
      }
    >
      {tasks.length === 0 ? (
        <EmptyState>Nothing outstanding.</EmptyState>
      ) : (
        <ul className="space-y-2.5">
          {tasks.map((task) => (
            <li key={task.id} className="flex items-start justify-between gap-3 text-sm">
              <span className="flex items-start gap-2">
                <span className={`mt-1 text-[10px] ${PRIORITY_COLOR[task.priority]}`}>●</span>
                <span>
                  <span className="text-hud-text">{task.title}</span>
                  {task.project_id !== null && (
                    <span className="ml-2 font-mono text-[10px] uppercase text-hud-accent/70">
                      project
                    </span>
                  )}
                </span>
              </span>
              <span className="shrink-0 text-right">
                <span className="block font-mono text-[10px] uppercase text-hud-muted">
                  {task.status}
                </span>
                {task.deadline !== null && (
                  <span className="block font-mono text-[10px] text-hud-muted">
                    {formatDeadline(task.deadline)}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function SchedulePanel({ events }: { events: CalendarEvent[] }) {
  return (
    <Panel title="Today" badge={<Count value={events.length} />}>
      {events.length === 0 ? (
        <EmptyState>No events scheduled.</EmptyState>
      ) : (
        <ul className="space-y-2.5">
          {events.map((event) => (
            <li key={event.id} className="flex items-baseline gap-3 text-sm">
              <span className="font-mono text-[11px] text-hud-accent">
                {formatTime(event.start_time)}
              </span>
              <span className="text-hud-text">{event.title}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function ProjectPanel({ projects }: { projects: Project[] }) {
  return (
    <Panel title="Projects" badge={<Count value={projects.length} />}>
      {projects.length === 0 ? (
        <EmptyState>No projects yet.</EmptyState>
      ) : (
        <ul className="space-y-3">
          {projects.map((project) => (
            <li key={project.id}>
              <div className="flex items-baseline justify-between text-sm">
                <span className="text-hud-text">{project.name}</span>
                <span
                  className={`font-mono text-[10px] uppercase ${STATUS_COLOR[project.status] ?? "text-hud-muted"}`}
                >
                  {project.status}
                </span>
              </div>
              {project.technology_stack.length > 0 && (
                <p className="mt-1 flex flex-wrap gap-1">
                  {project.technology_stack.slice(0, 4).map((tech) => (
                    <span
                      key={tech}
                      className="rounded border border-hud-border/60 px-1.5 py-0.5 font-mono text-[9px] uppercase text-hud-muted"
                    >
                      {tech}
                    </span>
                  ))}
                </p>
              )}
              {project.progress !== null && project.progress > 0 && (
                <div className="mt-2">
                  <div className="flex justify-between text-[10px] text-hud-muted">
                    <span className="font-mono uppercase tracking-widest">Progress</span>
                    <span className="font-mono">{project.progress}%</span>
                  </div>
                  <div className="mt-1 h-1 w-full rounded-full bg-hud-border">
                    <div
                      className="h-1 rounded-full bg-hud-accent transition-all duration-500"
                      style={{ width: `${project.progress}%` }}
                    />
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function MemoryPanel({ memories }: { memories: Memory[] }) {
  return (
    <Panel
      title="Memory"
      badge={
        <span className="flex items-center gap-2">
          <Count value={memories.length} />
          <Link
            href="/memory"
            className="text-[10px] uppercase tracking-widest text-hud-muted hover:text-hud-accent"
          >
            Manage
          </Link>
        </span>
      }
    >
      {memories.length === 0 ? (
        <EmptyState>Ray has not learned anything yet.</EmptyState>
      ) : (
        <ul className="space-y-3">
          {memories.slice(0, 6).map((memory) => (
            <li key={memory.id} className="text-sm">
              <span className="font-mono text-[10px] uppercase tracking-widest text-hud-accent/70">
                {memory.category}
              </span>
              <p className="text-hud-text">{memory.content}</p>
              {/* Provenance is shown, not hidden: the user should be able to see
                  why Ray believes something (docs/12). */}
              {memory.why !== "" && (
                <p className="mt-0.5 text-[11px] italic text-hud-muted">{memory.why}</p>
              )}
            </li>
          ))}
          {memories.length > 6 && (
            <li className="font-mono text-[10px] uppercase tracking-widest text-hud-muted">
              <Link href="/memory" className="hover:text-hud-accent">
                + {memories.length - 6} more
              </Link>
            </li>
          )}
        </ul>
      )}
    </Panel>
  );
}

export function LearningPanel({ memories }: { memories: Memory[] }) {
  const learning = memories.filter((memory) => memory.category === "learning");

  return (
    <Panel
      title="Learning"
      badge={
        <span className="flex items-center gap-2">
          <Count value={learning.length} />
          <Link
            href="/memory"
            className="text-[10px] uppercase tracking-widest text-hud-muted hover:text-hud-accent"
          >
            Browse
          </Link>
        </span>
      }
    >
      {learning.length === 0 ? (
        <EmptyState>Ray has no active learning topics.</EmptyState>
      ) : (
        <ul className="space-y-3">
          {learning.slice(0, 5).map((topic) => (
            <li key={topic.id} className="text-sm">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-hud-text">{topic.content}</span>
                {topic.importance > 3 && (
                  <span className="font-mono text-[9px] uppercase text-hud-warn">priority</span>
                )}
              </div>
              {topic.why !== "" && (
                <p className="mt-0.5 text-[11px] italic text-hud-muted">{topic.why}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function AgentPanel({ agents }: { agents: Agent[] }) {
  return (
    <Panel title="Agents" badge={<Count value={agents.filter((a) => a.enabled).length} />}>
      {agents.length === 0 ? (
        <EmptyState>No agents registered.</EmptyState>
      ) : (
        <ul className="space-y-2">
          {agents.map((agent) => (
            <li key={agent.name} className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    agent.enabled ? "bg-hud-accent" : "bg-hud-muted"
                  }`}
                />
                <span className="text-hud-text">{agent.display_name}</span>
              </span>
              <span className="font-mono text-[10px] text-hud-muted">
                {agent.tools.length} tools
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function WorkflowPanel({ workflows }: { workflows: Workflow[] }) {
  const active = workflows.filter((w) => w.enabled).length;

  return (
    <Panel
      title="Workflows"
      badge={
        <span className="flex items-center gap-2">
          <Count value={active} />
          <Link
            href="/workflows"
            className="text-[10px] uppercase tracking-widest text-hud-muted hover:text-hud-accent"
          >
            Manage
          </Link>
        </span>
      }
    >
      {workflows.length === 0 ? (
        <EmptyState>Ray has no scheduled workflows.</EmptyState>
      ) : (
        <ul className="space-y-2.5">
          {workflows.slice(0, 5).map((workflow) => (
            <li key={workflow.id} className="text-sm">
              <div className="flex items-baseline justify-between gap-2">
                <span className="flex items-center gap-2">
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      workflow.enabled ? "bg-hud-accent" : "bg-hud-muted"
                    }`}
                  />
                  <span className="text-hud-text">{workflow.name}</span>
                </span>
                <span className="font-mono text-[10px] text-hud-muted">
                  {workflow.interval_minutes}m
                </span>
              </div>
              <p className="mt-0.5 line-clamp-2 text-[11px] text-hud-muted">{workflow.prompt}</p>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
