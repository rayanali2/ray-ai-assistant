import "server-only";

import type { ChatMessage, TraceEntry } from "@/hooks/use-chat";
import type { components } from "@/lib/api-types";

/**
 * Server-side API client.
 *
 * The bearer token is read here and never sent to the browser: the dashboard is
 * rendered on the server, so the token stays in the Node process (docs/12).
 */

const API_URL = process.env.RAY_API_URL ?? "http://127.0.0.1:8000";
const API_TOKEN = process.env.RAY_API_TOKEN ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { Authorization: `Bearer ${API_TOKEN}` },
    // The dashboard must reflect the database right now, not a cached snapshot.
    cache: "no-store",
  });

  if (!response.ok) {
    throw new ApiError(`GET ${path} failed`, response.status);
  }
  return (await response.json()) as T;
}

/**
 * Types are generated from the backend's OpenAPI schema (`pnpm generate:api`), so
 * a change to a response shape breaks the build here instead of at runtime.
 */
type Schemas = components["schemas"];

export type User = Schemas["UserRead"];
export type Project = Schemas["ProjectRead"];
export type Task = Schemas["TaskRead"];
export type CalendarEvent = Schemas["CalendarEventRead"];
export type Memory = Schemas["MemoryRead"];
export type Agent = Schemas["AgentRead"];
export type DashboardSummary = Schemas["DashboardSummary"];
export type VoiceCapabilities = Schemas["VoiceCapabilities"];
export type Health = Schemas["HealthResponse"];
export type ConversationSummary = Schemas["ConversationSummary"];
export type Conversation = Schemas["ConversationRead"];
export type Workflow = Schemas["WorkflowRead"];
export type WorkflowRun = Schemas["WorkflowRunRead"];
export type TaskStatus = Task["status"];
export type TaskPriority = Task["priority"];

export const getDashboard = () => request<DashboardSummary>("/dashboard");

/**
 * The conversation Ray was last having, restored on load.
 *
 * Conversations are persisted server-side, so starting empty after a reload would
 * be throwing away state that exists — "continue and revisit conversations" is a
 * Phase 2 requirement (`docs/10`). The most recent one is enough: a full
 * conversation switcher is a later phase.
 *
 * Never throws, for the same reason as `getHealth`.
 */
export async function getRecentConversation(): Promise<RestoredConversation | null> {
  try {
    const history = await request<ConversationSummary[]>("/chat/history");
    const latest = history[0];
    if (latest === undefined) return null;

    const conversation = await request<Conversation>(`/chat/${latest.id}`);
    return {
      conversationId: conversation.id,
      messages: conversation.messages.map(toChatMessage),
    };
  } catch {
    return null;
  }
}

export interface RestoredConversation {
  conversationId: string;
  messages: ChatMessage[];
}

/**
 * A persisted message becomes the same shape the live stream produces, so the UI
 * cannot tell a restored turn from a streamed one.
 */
function toChatMessage(message: Schemas["MessageRead"]): ChatMessage {
  return {
    id: message.id,
    role: message.role === "user" ? "user" : "assistant",
    content: message.content,
    speechText: message.speech_text ?? undefined,
    agentName: message.agent_name ?? undefined,
    trace: readTrace(message.trace),
  };
}

/** The stored trace is `{"events": [{"stage": …, …detail}]}` (see the orchestrator). */
function readTrace(trace: Schemas["MessageRead"]["trace"]): TraceEntry[] {
  if (trace === null || trace === undefined) return [];
  const events = (trace as { events?: unknown }).events;
  if (!Array.isArray(events)) return [];

  return events.flatMap((event): TraceEntry[] => {
    if (typeof event !== "object" || event === null) return [];
    const { stage, ...detail } = event as { stage?: unknown };
    if (typeof stage !== "string") return [];
    return [{ stage: stage as TraceEntry["stage"], detail: detail as Record<string, unknown> }];
  });
}

/**
 * Health never throws: a dead backend is a state the HUD renders, not a crash.
 */
export async function getHealth(): Promise<Health | null> {
  try {
    return await request<Health>("/health");
  } catch {
    return null;
  }
}

export const getWorkflows = () => request<Workflow[]>("/workflows");

export async function createWorkflow(
  data: Schemas["WorkflowCreate"],
): Promise<Workflow> {
  const response = await fetch(`${API_URL}/workflows`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${API_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new ApiError("POST /workflows failed", response.status);
  }
  return (await response.json()) as Workflow;
}

export async function runWorkflow(workflowId: string): Promise<Schemas["WorkflowRunSummary"]> {
  const response = await fetch(`${API_URL}/workflows/${workflowId}/run`, {
    method: "POST",
    headers: { Authorization: `Bearer ${API_TOKEN}` },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new ApiError(`POST /workflows/${workflowId}/run failed`, response.status);
  }
  return (await response.json()) as Schemas["WorkflowRunSummary"];
}
