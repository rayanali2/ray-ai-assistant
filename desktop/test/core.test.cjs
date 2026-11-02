const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { isCheckout, readConfig, writeConfig, findCheckout, buildPath, isLocal, externalURL, windowBounds } = require("../core.cjs");

test("checkout search validates candidates and respects precedence", (t) => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "ray-desktop-test-"));
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));
  const make = (name) => { const root = path.join(home, name); fs.mkdirSync(path.join(root, "scripts"), { recursive: true }); fs.writeFileSync(path.join(root, "scripts/ray"), ""); return root; };
  assert.equal(findCheckout(home, {}, {}), null);
  assert.equal(isCheckout("relative"), false);
  assert.equal(isCheckout(null), false);
  const fallback = make("Ray");
  assert.equal(findCheckout(home, {}, {}), fallback);
  const conventional = make("ray-ai-assistant");
  assert.equal(findCheckout(home, {}, {}), conventional);
  const configured = make("configured");
  const exported = make("exported");
  assert.equal(findCheckout(home, { repoPath: configured }, {}), configured);
  assert.equal(findCheckout(home, { repoPath: configured }, { RAY_HOME: exported }), exported);
  assert.equal(findCheckout(home, { repoPath: configured }, { RAY_HOME: "/missing" }), configured);
  const file = path.join(home, "config.json");
  assert.deepEqual(readConfig(file), {});
  fs.writeFileSync(file, "invalid");
  assert.deepEqual(readConfig(file), {});
  writeConfig(file, { repoPath: configured, window: { width: 1200 } });
  assert.equal(readConfig(file).repoPath, configured);
});

test("PATH includes login shell, GUI tool locations and inherited tools", () => {
  const value = buildPath("/custom/node/bin:/usr/bin", "/Users/ray", "/usr/bin:/other").split(":");
  for (const item of ["/custom/node/bin", "/opt/homebrew/bin", "/usr/local/bin", "/Users/ray/.local/bin", "/Users/ray/.cargo/bin", "/Applications/Docker.app/Contents/Resources/bin", "/other"]) assert.ok(value.includes(item));
  assert.equal(value.filter((item) => item === "/usr/bin").length, 1);
});

test("localhost navigation is exact and external URL schemes are restricted", () => {
  assert.equal(isLocal("http://127.0.0.1:3000/settings"), true);
  for (const url of ["http://localhost:3000", "http://127.0.0.1:3001", "https://127.0.0.1:3000", "http://127.0.0.1.evil:3000", "file:///tmp/file", "bad"]) assert.equal(isLocal(url), false);
  assert.equal(externalURL("https://example.com"), true);
  assert.equal(externalURL("mailto:ray@example.com"), true);
  assert.equal(externalURL("javascript:alert(1)"), false);
  assert.equal(externalURL("file:///etc/passwd"), false);
});

test("offscreen, corrupt and valid remembered bounds", () => {
  const displays = [{ workArea: { x: 0, y: 0, width: 1920, height: 1080 } }];
  assert.deepEqual(windowBounds(null, displays), { width: 1360, height: 900 });
  assert.deepEqual(windowBounds({ x: 3000, y: 0, width: 1000, height: 700 }, displays), { width: 1360, height: 900 });
  assert.deepEqual(windowBounds({ x: 20, y: 20, width: 1200, height: 800 }, displays), { x: 20, y: 20, width: 1200, height: 800 });
});
