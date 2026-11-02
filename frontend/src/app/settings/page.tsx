"use client";

import { useEffect, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Panel, EmptyState, Count } from "@/components/panel";
import {
  checkIntegration,
  createIntegration,
  deleteIntegration,
  INTEGRATION_TYPES,
  listIntegrations,
  getConnections,
  getGoogleAuthUrl,
  providersForType,
  updateIntegration,
  type Integration,
  type IntegrationCreate,
  type IntegrationType,
} from "@/lib/integrations";
import { listPermissions, listTools, MODES, updatePermission, type PermissionMode, type ToolInfo, type ToolPermission } from "@/lib/tools";
import { exportData, getDiagnostics, type Diagnostics } from "@/lib/system";
import { getCurrentUser, updateCurrentUser, type User, type UserUpdate } from "@/lib/user";

const PROVIDER_LABELS: Record<string, string> = {
  github: "GitHub",
  local: "Local",
  google: "Google Calendar",
  obsidian: "Obsidian vault",
  notion: "Notion",
};

const TYPE_LABELS: Record<IntegrationType, string> = {
  github: "GitHub",
  calendar: "Calendar",
  knowledge: "Knowledge",
  files: "Local files",
};

export default function SettingsPage() {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [connections, setConnections] = useState<Record<string, string>>({});
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [permissions, setPermissions] = useState<ToolPermission[]>([]);
  const [user, setUser] = useState<User | null>(null);
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [type, setType] = useState<IntegrationType>("files");
  const [provider, setProvider] = useState("");
  const [config, setConfig] = useState<Record<string, string>>({});
  const [credentials, setCredentials] = useState("");

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [preferencesJson, setPreferencesJson] = useState("{}");
  const [settingsJson, setSettingsJson] = useState("{}");

  const load = async () => {
    setLoading(true);
    try {
      const [integrationsData, toolsData, permissionsData, userData, diagnosticsData] = await Promise.all([
        listIntegrations(),
        listTools(),
        listPermissions(),
        getCurrentUser().catch(() => null),
        getDiagnostics().catch(() => null),
      ]);
      setIntegrations(integrationsData);
      setConnections(await getConnections());
      setTools(toolsData);
      setPermissions(permissionsData);
      setDiagnostics(diagnosticsData);
      setUser(userData);
      if (userData) {
        setName(userData.name);
        setEmail(userData.email ?? "");
        setPreferencesJson(JSON.stringify(userData.preferences ?? {}, null, 2));
        setSettingsJson(JSON.stringify(userData.settings ?? {}, null, 2));
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load settings");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    setProvider(providersForType(type)[0] ?? "");
    setConfig({});
  }, [type]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const body: IntegrationCreate = {
      type,
      provider,
      enabled: true,
      credentials_reference: credentials.trim() || null,
      config,
    };
    await createIntegration(body);
    setCredentials("");
    setConfig({});
    await load();
  };

  const handleToggle = async (integration: Integration) => {
    await updateIntegration(integration.id, { enabled: !integration.enabled });
    await load();
  };

  const handleCheck = async (id: string) => {
    await checkIntegration(id);
    await load();
  };

  const handleDelete = async (id: string) => {
    await deleteIntegration(id);
    await load();
  };

  const handlePermissionChange = async (toolName: string, mode: PermissionMode) => {
    await updatePermission(toolName, mode);
    await load();
  };

  const parseJson = (text: string): Record<string, unknown> | null => {
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        return null;
      }
      return parsed as Record<string, unknown>;
    } catch {
      return null;
    }
  };

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    const preferences = parseJson(preferencesJson);
    const settings = parseJson(settingsJson);
    if (preferences === null || settings === null) {
      setError("Preferences and settings must be valid JSON objects.");
      return;
    }
    const payload: UserUpdate = {
      name: name.trim() || null,
      email: email.trim() || null,
      preferences,
      settings,
    };
    await updateCurrentUser(payload);
    await load();
  };

  const handleExport = async () => {
    const snapshot = await exportData();
    const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const date = new Date().toISOString().split("T")[0];
    link.href = url;
    link.download = `ray-export-${date}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const configFields = (selectedProvider: string) => {
    if (type === "files") return [{ key: "allowed_paths", label: "Allowed directories (comma-separated)" }];
    if (type === "knowledge" && selectedProvider === "obsidian") return [{ key: "vault_path", label: "Vault path" }];
    if (type === "github") return [{ key: "owner", label: "Default owner (optional)" }, { key: "repo", label: "Default repo (optional)" }];
    return [];
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col gap-4 p-6">
      <PageHeader title="Settings" />

      {error && <p className="rounded-md bg-hud-danger/10 p-3 text-sm text-hud-danger">{error}</p>}

      <Panel title="Profile & preferences">
        {user === null ? (
          <EmptyState>Loading profile...</EmptyState>
        ) : (
          <form onSubmit={handleSaveProfile} className="flex flex-col gap-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Name"
                className="rounded-md border border-hud-border bg-hud-panel px-3 py-2 text-sm text-hud-text outline-none placeholder:text-hud-muted focus:border-hud-accent"
              />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Email"
                className="rounded-md border border-hud-border bg-hud-panel px-3 py-2 text-sm text-hud-text outline-none placeholder:text-hud-muted focus:border-hud-accent"
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs text-hud-muted">Preferences (JSON)</label>
                <textarea
                  value={preferencesJson}
                  onChange={(e) => setPreferencesJson(e.target.value)}
                  rows={6}
                  className="w-full rounded-md border border-hud-border bg-hud-panel px-3 py-2 font-mono text-xs text-hud-text outline-none focus:border-hud-accent"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-hud-muted">Settings (JSON)</label>
                <textarea
                  value={settingsJson}
                  onChange={(e) => setSettingsJson(e.target.value)}
                  rows={6}
                  className="w-full rounded-md border border-hud-border bg-hud-panel px-3 py-2 font-mono text-xs text-hud-text outline-none focus:border-hud-accent"
                />
              </div>
            </div>
            <div className="flex justify-end">
              <button
                type="submit"
                disabled={loading}
                className="rounded-md bg-hud-accent px-4 py-2 text-sm font-medium text-black hover:bg-hud-accent/90 disabled:opacity-50"
              >
                Save profile
              </button>
            </div>
          </form>
        )}
      </Panel>

      <Panel title="Diagnostics" badge={diagnostics ? <Count value={diagnostics.suggestions.length} /> : undefined}>
        {diagnostics === null ? (
          <EmptyState>Loading diagnostics...</EmptyState>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <span
                className={`h-2 w-2 rounded-full ${diagnostics.overall === "ok" ? "bg-hud-accent" : "bg-hud-warn"}`}
              />
              <span className="text-sm font-medium text-hud-text capitalize">{diagnostics.overall.replace("_", " ")}</span>
            </div>
            <ul className="grid gap-2 sm:grid-cols-2">
              {Object.entries(diagnostics.checks).map(([key, value]) => (
                <li key={key} className="rounded-md border border-hud-border bg-hud-panel/50 p-2">
                  <p className="text-[10px] uppercase tracking-wider text-hud-muted">{key}</p>
                  <p className="text-sm text-hud-text">{value}</p>
                </li>
              ))}
            </ul>
            {diagnostics.suggestions.length > 0 && (
              <ul className="space-y-1">
                {diagnostics.suggestions.map((s, i) => (
                  <li key={i} className="text-sm text-hud-warn">{s}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Panel>

      <Panel title="Data export">
        <p className="mb-3 text-sm text-hud-muted">
          Download a complete snapshot of your data. Secrets are not included — only references to where they are stored.
        </p>
        <button
          onClick={handleExport}
          disabled={loading}
          className="rounded-md border border-hud-border px-4 py-2 text-sm text-hud-text hover:border-hud-accent hover:text-hud-accent disabled:opacity-50"
        >
          Download JSON export
        </button>
      </Panel>

      <Panel title="Integrations" badge={<Count value={integrations.length} />}>
        <div className="mb-4 space-y-2 text-sm text-hud-muted">
          {Object.entries(connections).map(([name, status]) => <p key={name}>{PROVIDER_LABELS[name] ?? name}: {status}</p>)}
          <button
            type="button"
            onClick={async () => {
              try {
                const { url } = await getGoogleAuthUrl();
                window.location.assign(url);
              } catch (err) {
                setError(err instanceof Error ? err.message : "Could not connect Google Calendar");
              }
            }}
            className="rounded-md border border-hud-border px-3 py-2 text-hud-text hover:border-hud-accent"
          >Connect Google Calendar</button>
          <p>Set RAY_NOTION_TOKEN on the backend, share pages via Connections, then add a Notion integration below and Check it. Refresh this page after connecting.</p>
        </div>
        <div className="mb-4 rounded-md border border-hud-border bg-hud-panel/50 p-4">
          <h3 className="mb-2 font-mono text-[11px] uppercase tracking-widest text-hud-muted">Add integration</h3>
          <form onSubmit={handleCreate} className="flex flex-col gap-3">
            <div className="grid gap-3 sm:grid-cols-3">
              <select
                value={type}
                onChange={(e) => setType(e.target.value as IntegrationType)}
                className="rounded-md border border-hud-border bg-hud-panel px-3 py-2 text-sm text-hud-text"
              >
                {INTEGRATION_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {TYPE_LABELS[t]}
                  </option>
                ))}
              </select>
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                className="rounded-md border border-hud-border bg-hud-panel px-3 py-2 text-sm text-hud-text"
              >
                {providersForType(type).map((p) => (
                  <option key={p} value={p}>
                    {PROVIDER_LABELS[p] ?? p}
                  </option>
                ))}
              </select>
              <input
                value={credentials}
                onChange={(e) => setCredentials(e.target.value)}
                placeholder="Credentials reference (env var name, optional)"
                className="rounded-md border border-hud-border bg-hud-panel px-3 py-2 text-sm text-hud-text outline-none placeholder:text-hud-muted focus:border-hud-accent"
              />
            </div>
            {configFields(provider).map(({ key, label }) => (
              <input
                key={key}
                value={config[key] ?? ""}
                onChange={(e) => setConfig({ ...config, [key]: e.target.value })}
                placeholder={label}
                className="rounded-md border border-hud-border bg-hud-panel px-3 py-2 text-sm text-hud-text outline-none placeholder:text-hud-muted focus:border-hud-accent"
              />
            ))}
            <div className="flex justify-end">
              <button
                type="submit"
                disabled={loading}
                className="rounded-md bg-hud-accent px-4 py-2 text-sm font-medium text-black hover:bg-hud-accent/90 disabled:opacity-50"
              >
                Add integration
              </button>
            </div>
          </form>
        </div>

        {integrations.length === 0 ? (
          <EmptyState>No integrations configured yet.</EmptyState>
        ) : (
          <ul className="space-y-3">
            {integrations.map((integration) => (
              <li
                key={integration.id}
                className="flex flex-col gap-2 rounded-md border border-hud-border bg-hud-panel/50 p-4 sm:flex-row sm:items-center sm:justify-between"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`h-2 w-2 rounded-full ${integration.enabled ? "bg-hud-accent" : "bg-hud-muted"}`}
                    />
                    <span className="text-sm font-medium text-hud-text">
                      {TYPE_LABELS[integration.type]} — {PROVIDER_LABELS[integration.provider] ?? integration.provider}
                    </span>
                    <span className="font-mono text-[10px] uppercase text-hud-muted">{integration.status}</span>
                  </div>
                  <p className="mt-0.5 text-xs text-hud-muted">
                    Last sync: {integration.last_sync ? new Date(integration.last_sync).toLocaleString() : "never"}
                    {integration.last_error ? ` · Error: ${integration.last_error}` : ""}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleCheck(integration.id)}
                    className="rounded-md border border-hud-border px-2 py-1 text-xs text-hud-text hover:border-hud-accent hover:text-hud-accent"
                  >
                    Check
                  </button>
                  <button
                    onClick={() => handleToggle(integration)}
                    className="rounded-md border border-hud-border px-2 py-1 text-xs text-hud-text hover:border-hud-accent hover:text-hud-accent"
                  >
                    {integration.enabled ? "Disable" : "Enable"}
                  </button>
                  <button
                    onClick={() => handleDelete(integration.id)}
                    className="rounded-md border border-hud-danger/30 px-2 py-1 text-xs text-hud-danger hover:bg-hud-danger/10"
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="Tool permissions">
        {tools.length === 0 ? (
          <EmptyState>No tools registered.</EmptyState>
        ) : (
          <ul className="space-y-2">
            {tools.map((tool) => {
              const permission = permissions.find((p) => p.tool_name === tool.name)?.mode ?? "ask";
              return (
                <li
                  key={tool.name}
                  className="flex flex-col justify-between gap-2 rounded-md border border-hud-border bg-hud-panel/50 p-3 sm:flex-row sm:items-center"
                >
                  <div>
                    <p className="text-sm text-hud-text">{tool.name}</p>
                    <p className="text-xs text-hud-muted">{tool.description}</p>
                    {tool.side_effect && (
                      <p className="text-[10px] text-hud-warn">Side-effecting tool — requires approval.</p>
                    )}
                  </div>
                  <select
                    value={permission}
                    disabled={tool.side_effect && !tool.standing_allow_eligible}
                    onChange={(e) => handlePermissionChange(tool.name, e.target.value as PermissionMode)}
                    className="rounded-md border border-hud-border bg-hud-panel px-2 py-1 text-xs text-hud-text disabled:opacity-50"
                  >
                    {MODES.map((mode) => (
                      <option key={mode} value={mode}>
                        {mode}
                      </option>
                    ))}
                  </select>
                </li>
              );
            })}
          </ul>
        )}
      </Panel>
    </main>
  );
}
