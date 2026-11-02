import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { Telemetry } from "./telemetry";

vi.stubGlobal("React", React);
let health: { status: string; database: string; llm_provider: string } | null = null;
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
});
