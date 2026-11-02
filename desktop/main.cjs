const { app, BrowserWindow, Menu, Tray, nativeImage, ipcMain, dialog, shell, globalShortcut, session, screen, systemPreferences } = require("electron");
const { spawn, execFile } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { promisify } = require("node:util");
const { ORIGIN, isCheckout, readConfig, writeConfig, findCheckout, buildPath, isLocal, externalURL, windowBounds } = require("./core.cjs");

app.setName("Ray");
const configFile = path.join(app.getPath("appData"), "Ray", "config.json");
const logDir = path.join(path.dirname(configFile), "logs");
fs.mkdirSync(logDir, { recursive: true });
const logFile = path.join(logDir, "desktop.log");
let config = readConfig(configFile);
let repo = null;
let env = process.env;
let mainWindow = null;
let controlWindow = null;
let tray = null;
let busy = false;
let quitting = false;
let listenReady = false;
let pendingListen = false;
let status = { mode: "splash", message: "Initializing Ray…", logs: "", busy: true };

function log(text) {
  const value = String(text);
  fs.appendFileSync(logFile, value);
  status.logs = (status.logs + value).slice(-48000);
  publish();
}

function publish(update = {}) {
  status = { ...status, ...update, busy, allowInstall: !repo };
  if (controlWindow && !controlWindow.isDestroyed()) controlWindow.webContents.send("ray:status", status);
}

function saveConfig(update) {
  config = { ...config, ...update };
  writeConfig(configFile, config);
}

function resource(name) { return app.isPackaged ? path.join(process.resourcesPath, name) : path.join(__dirname, name === "install.sh" ? "../scripts/install.sh" : "../macos/Ray.app/Contents/Resources/icon.png"); }

function run(command, args, { cwd = repo || os.homedir(), timeout = 120000, quiet = false } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env, detached: process.platform !== "win32", stdio: ["ignore", "pipe", "pipe"] });
    let output = "";
    let timedOut = false;
    let killTimer;
    const timer = setTimeout(() => {
      timedOut = true;
      try { if (process.platform === "win32") child.kill(); else process.kill(-child.pid, "SIGTERM"); } catch { /* Process already exited. */ }
      killTimer = setTimeout(() => { try { if (process.platform === "win32") child.kill("SIGKILL"); else process.kill(-child.pid, "SIGKILL"); } catch { /* Process already exited. */ } }, 5000);
    }, timeout);
    for (const stream of [child.stdout, child.stderr]) stream.on("data", (data) => {
      output = (output + data).slice(-64000);
      if (!quiet) log(data.toString());
    });
    child.on("error", (error) => { clearTimeout(timer); clearTimeout(killTimer); reject(error); });
    child.on("close", (code) => {
      clearTimeout(timer);
      clearTimeout(killTimer);
      if (code === 0 && !timedOut) resolve(output);
      else reject(new Error(timedOut ? `${path.basename(command)} timed out.` : `${path.basename(command)} exited with code ${code}.`));
    });
  });
}

async function loginEnvironment() {
  let loginPath = "";
  try {
    const result = await promisify(execFile)(process.env.SHELL || (process.platform === "darwin" ? "/bin/zsh" : "/bin/bash"), ["-ilc", 'printf "\\nRAY_LOGIN_PATH=%s\\n" "$PATH"'], { timeout: 10000, maxBuffer: 1024 * 1024 });
    loginPath = result.stdout.split("\n").find((line) => line.startsWith("RAY_LOGIN_PATH="))?.slice(15) || "";
  } catch { log("Login shell PATH unavailable; using standard tool locations.\n"); }
  env = { ...process.env, PATH: buildPath(loginPath, os.homedir(), process.env.PATH) };
}

function controls(mode = "splash", message = "Initializing Ray…") {
  publish({ mode, message });
  if (!controlWindow || controlWindow.isDestroyed()) {
    controlWindow = new BrowserWindow({ width: 640, height: 720, resizable: true, minWidth: 520, minHeight: 580, frame: false, backgroundColor: "#030a10", title: "Ray", webPreferences: { preload: path.join(__dirname, "setup-preload.cjs"), contextIsolation: true, nodeIntegration: false, sandbox: true } });
    controlWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    controlWindow.webContents.on("will-navigate", (event) => event.preventDefault());
    controlWindow.on("closed", () => { controlWindow = null; });
    void controlWindow.loadFile(path.join(__dirname, "ui/index.html"));
  }
  controlWindow.show();
  controlWindow.focus();
}

function openLogs() { void shell.openPath(logDir); }

async function ensureDocker() {
  publish({ message: "Checking Docker engine…" });
  try { await run("docker", ["info", "--format", "{{.ServerVersion}}"], { quiet: true, timeout: 8000 }); return; } catch { /* Start Desktop on macOS below. */ }
  if (process.platform !== "darwin") throw new Error("Docker is not running. Start Docker, then retry.");
  publish({ message: "Starting Docker Desktop…" });
  await run("/usr/bin/open", ["-a", "Docker"], { timeout: 10000 });
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    try { await run("docker", ["info", "--format", "{{.ServerVersion}}"], { quiet: true, timeout: 5000 }); return; } catch { /* Engine may still be starting. */ }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error("Docker Desktop did not become ready within 90 seconds.");
}

async function waitForServices() {
  publish({ message: "Waiting for backend and HUD uplinks…" });
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    const ready = await Promise.all([
      fetch("http://127.0.0.1:8000/health", { signal: AbortSignal.timeout(3000) }).then(async (response) => response.ok && (await response.json()).status === "ok").catch(() => false),
      fetch(ORIGIN, { signal: AbortSignal.timeout(5000) }).then((response) => response.ok).catch(() => false),
    ]);
    if (ready.every(Boolean)) return;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("Ray did not become ready within two minutes. Check logs and doctor output below.");
}

function showMain() {
  if (mainWindow && !mainWindow.isDestroyed()) { mainWindow.show(); mainWindow.restore(); mainWindow.focus(); return; }
  const partition = session.fromPartition("persist:ray");
  partition.setPermissionCheckHandler((contents, permission, origin, details) => contents === mainWindow?.webContents && isLocal(origin) && isLocal(contents.getURL()) && permission === "media" && details.mediaType === "audio");
  partition.setPermissionRequestHandler(async (contents, permission, callback, details) => {
    const allowed = contents === mainWindow?.webContents && isLocal(contents.getURL()) && isLocal(details.requestingUrl) && details.isMainFrame !== false && permission === "media" && details.mediaTypes?.length > 0 && details.mediaTypes.every((type) => type === "audio");
    if (!allowed) { callback(false); return; }
    try { callback(process.platform !== "darwin" || await systemPreferences.askForMediaAccess("microphone")); } catch { callback(false); }
  });
  mainWindow = new BrowserWindow({ ...windowBounds(config.window, screen.getAllDisplays()), minWidth: 800, minHeight: 600, backgroundColor: "#030a10", title: "Ray", titleBarStyle: "hiddenInset", webPreferences: { partition: "persist:ray", preload: path.join(__dirname, "preload.cjs"), contextIsolation: true, nodeIntegration: false, sandbox: true } });
  const wc = mainWindow.webContents;
  wc.setWindowOpenHandler(({ url }) => { if (externalURL(url) && !isLocal(url)) void shell.openExternal(url); return { action: "deny" }; });
  const navigate = (event, url) => { if (!isLocal(url)) { event.preventDefault(); if (externalURL(url)) void shell.openExternal(url); } };
  wc.on("will-navigate", navigate);
  wc.on("will-redirect", navigate);
  wc.on("did-start-loading", () => { listenReady = false; });
  wc.on("did-fail-load", (_event, code, description, url, mainFrame) => { if (mainFrame && code !== -3) { controls("error", `HUD could not load: ${description}`); log(`Navigation failed (${code}) for ${isLocal(url) ? "HUD" : "external page"}.\n`); } });
  mainWindow.on("close", (event) => {
    saveConfig({ window: mainWindow.getNormalBounds() });
    if (!quitting) { event.preventDefault(); mainWindow.hide(); }
  });
  mainWindow.on("closed", () => { mainWindow = null; listenReady = false; });
  wc.once("did-finish-load", () => { controlWindow?.close(); mainWindow?.show(); });
  void mainWindow.loadURL(ORIGIN).catch((error) => log(`${error.message}\n`));
}

async function doctor() {
  if (!repo) { log("Choose a checkout before running doctor.\n"); return; }
  log("\n--- ray doctor ---\n");
  try { await run(path.join(repo, "scripts/ray"), ["doctor"], { timeout: 45000 }); } catch (error) { log(`${error.message}\n`); }
}

async function operation(work) {
  if (busy) return;
  busy = true; publish();
  try { await work(); }
  catch (error) {
    controls("error", error.message);
    log(`\n${error.message}\nDesktop log: ${logFile}\n`);
    if (repo) {
      const serviceLog = path.join(repo, ".ray/ray.log");
      log(`Service log: ${serviceLog}\n`);
      try { const fd = fs.openSync(serviceLog, "r"); try { const size = fs.fstatSync(fd).size; const buffer = Buffer.alloc(Math.min(size, 24000)); fs.readSync(fd, buffer, 0, buffer.length, Math.max(0, size - buffer.length)); log(buffer.toString()); } finally { fs.closeSync(fd); } } catch { /* No service log yet. */ }
    }
    await doctor();
  } finally { busy = false; publish(); }
}

async function start() {
  if (!repo) { controls("setup", "Connect your Ray checkout"); return; }
  controls();
  await ensureDocker();
  publish({ message: "Starting Ray services…" });
  await run(path.join(repo, "scripts/ray"), ["start", "--no-browser"], { timeout: 120000 });
  await waitForServices();
  showMain();
  if (isLocal(mainWindow?.webContents.getURL()) && !mainWindow.webContents.isLoadingMainFrame()) controlWindow?.close();
}

async function chooseRepo() {
  const result = await dialog.showOpenDialog({ title: "Choose your Ray checkout", properties: ["openDirectory"] });
  if (result.canceled) return;
  const selected = result.filePaths[0];
  if (!isCheckout(selected)) { controls("setup", "That folder does not contain scripts/ray. Choose the Ray checkout root."); return; }
  if (repo && path.resolve(repo) !== path.resolve(selected)) {
    const confirmation = await dialog.showMessageBox({ type: "question", title: "Switch Ray checkout?", message: "Stop the current checkout’s Ray services and switch folders?", detail: "PostgreSQL will remain running. The new checkout must already be installed.", buttons: ["Cancel", "Switch checkout"], defaultId: 0, cancelId: 0 });
    if (confirmation.response !== 1) return;
    await stop();
    if (mainWindow) {
      saveConfig({ window: mainWindow.getNormalBounds() });
      mainWindow.destroy();
    }
  }
  repo = selected;
  saveConfig({ repoPath: repo });
  log(`Selected checkout: ${repo}\n`);
  await start();
}

async function install() {
  controls("splash", "Installing Ray into ~/ray-ai-assistant…");
  await ensureDocker();
  publish({ message: "Installing Ray into ~/ray-ai-assistant…" });
  await run("/bin/bash", [resource("install.sh")], { cwd: os.homedir(), timeout: 20 * 60 * 1000 });
  const installed = path.join(os.homedir(), "ray-ai-assistant");
  if (!isCheckout(installed)) throw new Error("Installer finished without a checkout at ~/ray-ai-assistant.");
  repo = installed;
  saveConfig({ repoPath: repo });
  await start();
}

function quit() { quitting = true; app.quit(); }
async function stop() {
  if (!repo) throw new Error("Choose a Ray checkout first.");
  await run(path.join(repo, "scripts/ray"), ["stop"]);
}

function menuItems() {
  return [
    { label: "Show Ray", click: () => mainWindow ? showMain() : operation(start) },
    { type: "separator" },
    { label: "Start services", click: () => operation(start) },
    { label: "Stop services", click: () => operation(stop) },
    { label: "Restart services", click: () => operation(async () => { await stop(); await start(); }) },
    { label: "Open logs folder", click: openLogs },
    { label: "Run doctor", click: () => operation(async () => { controls("doctor", "Ray diagnostics"); await doctor(); }) },
    { label: "Preferences…", accelerator: "CommandOrControl+,", click: () => { if (!busy) controls("setup", `Checkout: ${repo || "not selected"}. Change folder below. RAY_HOME takes precedence on next launch.`); } },
    { type: "separator" },
    { label: "Quit (keep services running)", accelerator: "CommandOrControl+Q", click: quit },
    { label: "Quit and stop services", click: () => operation(async () => { if (repo) await stop(); quit(); }) },
  ];
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", () => { if (mainWindow) showMain(); else controls(repo ? "splash" : "setup", status.message); });
  app.whenReady().then(async () => {
    const image = nativeImage.createFromDataURL("data:image/png;base64," + fs.readFileSync(resource("icon.png")).toString("base64")).resize({ width: 18, height: 18 });
    tray = new Tray(image);
    tray.setToolTip("Ray — personal AI assistant");
    tray.setContextMenu(Menu.buildFromTemplate(menuItems()));
    tray.on("click", () => { if (mainWindow) showMain(); else void operation(start); });
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      { label: "Ray", submenu: [{ role: "about" }, ...menuItems()] },
      { role: "editMenu" }, { role: "viewMenu" }, { role: "windowMenu" },
    ]));
    ipcMain.on("ray:setup-ready", (event) => { if (event.sender === controlWindow?.webContents) publish(); });
    ipcMain.handle("ray:setup-action", async (event, action) => {
      if (event.sender !== controlWindow?.webContents) return;
      if (action === "logs") openLogs();
      else if (action === "close") controlWindow?.close();
      else if (action === "choose") await operation(chooseRepo);
      else if (action === "install" && !repo) await operation(install);
      else if (action === "retry") await operation(start);
      else if (action === "doctor") await operation(doctor);
    });
    ipcMain.on("ray:listen-ready", (event) => {
      if (event.sender !== mainWindow?.webContents || !isLocal(event.senderFrame?.url)) return;
      listenReady = true;
      if (pendingListen) { pendingListen = false; event.sender.send("ray:listen"); }
    });
    const shortcut = globalShortcut.register("CommandOrControl+Shift+Space", () => {
      pendingListen = true;
      if (mainWindow) { showMain(); if (listenReady) { pendingListen = false; mainWindow.webContents.send("ray:listen"); } }
      else void operation(start);
    });
    if (!shortcut) log("Could not register Cmd/Ctrl+Shift+Space; another application may own it.\n");
    controls();
    await loginEnvironment();
    repo = findCheckout(os.homedir(), config);
    if (repo) { saveConfig({ repoPath: repo }); await operation(start); }
    else controls("setup", "Connect your Ray checkout");
  }).catch((error) => { log(`${error.stack}\n`); dialog.showErrorBox("Ray could not start", `${error.message}\nLogs: ${logDir}`); });
}

app.on("activate", () => { if (mainWindow) showMain(); else controls(repo ? "splash" : "setup", status.message); });
app.on("window-all-closed", () => { /* The tray owns the application lifecycle. */ });
app.on("before-quit", () => { quitting = true; });
app.on("will-quit", () => globalShortcut.unregisterAll());
