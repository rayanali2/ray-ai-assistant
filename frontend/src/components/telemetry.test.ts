import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { Telemetry } from "./telemetry";

vi.stubGlobal("React", React);
let health: { status: string; database: string; llm_provider: string; diagnostics?: Record<string, string> } | null = null;
vi.mock("@/components/dashboard-context", () => ({ useDashboard: () => ({ health }) }));

describe("provider telemetry", () => {
  it("warns when the last answer used mock", () => {
    health = { status: "ok", database: "connected", llm_provider: "mock" };
    const html = renderToStaticMarkup(React.createElement(Telemetry));
    expect(html).toContain("CANNED REPLIES");
    expect(html).toContain("desktop Preferences");
  });
  it("does not warn for real providers", () => {
    health = { status: "ok", database: "connected", llm_provider: "gemini" };
    expect(renderToStaticMarkup(React.createElement(Telemetry))).not.toContain("CANNED REPLIES");
  });
  it("handles unavailable health", () => {
    health = null;
    const html = renderToStaticMarkup(React.createElement(Telemetry));
    expect(html).toContain("UNAVAILABLE");
    expect(html).toContain("OFFLINE");
  });
  it("shows quota exhaustion instead of suggesting an already configured key", () => {
    health = { status: "ok", database: "connected", llm_provider: "mock", diagnostics: { gemini_quota: "Gemini daily quota used up — resets in 11h" } };
    const html = renderToStaticMarkup(React.createElement(Telemetry));
    expect(html).toContain("daily quota used up");
    expect(html).toContain("resets in 11h");
    expect(html).toContain("CANNED REPLIES");
    expect(html).not.toContain("add a Gemini key");
  });
  it("shows a primary-model cooldown even if a live fallback answered", () => {
    health = { status: "ok", database: "connected", llm_provider: "gemini", diagnostics: { gemini_quota: "Gemini per-minute quota used up — resets in 20s" } };
    const html = renderToStaticMarkup(React.createElement(Telemetry));
    expect(html).toContain("per-minute quota");
    expect(html).not.toContain("CANNED REPLIES");
  });
});
