const fs = require("node:fs");
const path = require("node:path");

const ORIGIN = "http://127.0.0.1:3000";

function isCheckout(folder) {
  try { return typeof folder === "string" && path.isAbsolute(folder) && fs.statSync(path.join(folder, "scripts/ray")).isFile(); }
  catch { return false; }
}

function readConfig(file) {
  try { const value = JSON.parse(fs.readFileSync(file, "utf8")); return value && typeof value === "object" && !Array.isArray(value) ? value : {}; }
  catch { return {}; }
}

function writeConfig(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temp = `${file}.tmp`;
  fs.writeFileSync(temp, JSON.stringify(value, null, 2), { mode: 0o600 });
  fs.renameSync(temp, file);
}

function findCheckout(home, config, env = process.env) {
  return [env.RAY_HOME, config.repoPath, path.join(home, "ray-ai-assistant"), path.join(home, "Ray")].find(isCheckout) ?? null;
}

function buildPath(loginPath, home, inherited = "") {
  return [...new Set([
    path.join(home, ".local/bin"),
    path.join(home, ".local/share/pnpm"),
    path.join(home, ".local/share/pnpm/bin"),
    "/opt/homebrew/bin", "/usr/local/bin",
    path.join(home, ".cargo/bin"), "/Applications/Docker.app/Contents/Resources/bin",
    ...(loginPath || "").split(path.delimiter), ...inherited.split(path.delimiter), "/usr/bin", "/bin", "/usr/sbin", "/sbin",
  ].filter(Boolean))].join(path.delimiter);
}

function geminiEnvironment(key) {
  if (typeof key !== "string" || key.length > 512 || (key && !/^[A-Za-z0-9_-]+$/.test(key))) throw new Error("Paste only the API key, without quotes or spaces.");
  return key ? { RAY_GEMINI_API_KEY: key } : {};
}

function isLocal(url) {
  try { return new URL(url).origin === ORIGIN; } catch { return false; }
}

function externalURL(url) {
  try { return ["https:", "http:", "mailto:"].includes(new URL(url).protocol); } catch { return false; }
}

function windowBounds(saved, displays) {
  if (!saved || ![saved.x, saved.y, saved.width, saved.height].every(Number.isFinite)) return { width: 1360, height: 900 };
  const visible = displays.some(({ workArea: area }) => saved.x < area.x + area.width && saved.x + saved.width > area.x + 80 && saved.y >= area.y && saved.y < area.y + area.height - 40);
  if (!visible) return { width: 1360, height: 900 };
  return { x: saved.x, y: saved.y, width: Math.max(800, Math.min(2560, saved.width)), height: Math.max(600, Math.min(1800, saved.height)) };
}

module.exports = { ORIGIN, isCheckout, readConfig, writeConfig, findCheckout, buildPath, isLocal, externalURL, windowBounds, geminiEnvironment };
