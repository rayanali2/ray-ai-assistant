import type { components } from "@/lib/api-types";

type Schemas = components["schemas"];
export type Integration = Schemas["IntegrationRead"];
export type IntegrationCreate = Schemas["IntegrationCreate"];
export type IntegrationUpdate = Schemas["IntegrationUpdate"];
export type IntegrationType = Schemas["IntegrationType"];
export type IntegrationStatus = Schemas["IntegrationStatus"];

export const INTEGRATION_TYPES: IntegrationType[] = ["github", "calendar", "knowledge", "files"];

const PROVIDERS: Record<IntegrationType, string[]> = {
  github: ["github"],
  calendar: ["local", "google"],
  knowledge: ["obsidian", "notion"],
  files: ["local"],
};

export const providersForType = (type: IntegrationType) => PROVIDERS[type] ?? [];

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/integrations${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const text = await response.text().catch(() => `Request failed (${response.status})`);
    throw new Error(text);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export const listIntegrations = () => call<Integration[]>("");
export const getConnections = () => call<Record<string, string>>("/connections");
export const getGoogleAuthUrl = () => call<{ url: string }>("/google/auth-url");

export const createIntegration = (body: IntegrationCreate) =>
  call<Integration>("", { method: "POST", body: JSON.stringify(body) });

export const updateIntegration = (id: string, body: IntegrationUpdate) =>
  call<Integration>(`/${id}`, { method: "PATCH", body: JSON.stringify(body) });

export const deleteIntegration = (id: string) => call<void>(`/${id}`, { method: "DELETE" });

export const checkIntegration = (id: string) =>
  call<{ ok: boolean; message: string }>(`/${id}/check`, { method: "POST" });
