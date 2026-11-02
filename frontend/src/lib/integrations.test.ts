import { afterEach, describe, expect, it, vi } from "vitest";

import { getConnections, getGoogleAuthUrl } from "@/lib/integrations";

afterEach(() => vi.unstubAllGlobals());

describe("integration connection endpoints", () => {
  it("loads local connection status through the authenticated frontend proxy", async () => {
    const statuses = { google: "not connected", notion: "token configured" };
    const fetcher = vi.fn().mockResolvedValue(Response.json(statuses));
    vi.stubGlobal("fetch", fetcher);
    expect(await getConnections()).toEqual(statuses);
    expect(fetcher.mock.calls[0][0]).toBe("/api/integrations/connections");
  });

  it("handles an empty status map", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({})));
    expect(await getConnections()).toEqual({});
  });

  it("obtains the consent URL without exposing a bearer token", async () => {
    const url = "https://accounts.google.com/o/oauth2/v2/auth?state=opaque";
    const fetcher = vi.fn().mockResolvedValue(Response.json({ url }));
    vi.stubGlobal("fetch", fetcher);
    expect(await getGoogleAuthUrl()).toEqual({ url });
    expect(fetcher.mock.calls[0][0]).toBe("/api/integrations/google/auth-url");
    expect(fetcher.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });

  it("surfaces missing-configuration errors to Settings", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Set RAY_GOOGLE_CLIENT_ID", { status: 400 })));
    await expect(getGoogleAuthUrl()).rejects.toThrow("RAY_GOOGLE_CLIENT_ID");
  });
});
