const output = document.querySelector("#output");
window.raySetup.onStatus((status) => {
  document.body.dataset.mode = status.mode;
  document.querySelector("#message").textContent = status.message;
  document.querySelector("#hint").textContent = status.mode === "setup"
    ? "Install into ~/ray-ai-assistant without Homebrew. Ray installs uv, Python, Node and pnpm; Docker Desktop needs its own setup. Add a key for real AI chat."
    : status.mode === "error" ? "Review the diagnostic output, open logs, then retry. Services are not stopped when you close Ray."
    : "Your checkout and data stay on this computer.";
  document.querySelector("#key-label").hidden = status.mode !== "setup" && !(status.mode === "error" && status.allowInstall);
  for (const action of ["choose", "install", "save-key", "retry", "doctor", "logs"]) {
    const button = document.querySelector(`#${action}`);
    button.hidden = ["choose", "install"].includes(action) ? !["setup", "error"].includes(status.mode) || (action === "install" && !status.allowInstall)
      : action === "save-key" ? status.mode !== "setup" || status.allowInstall
      : action === "retry" ? status.mode !== "error" || status.allowInstall
      : action === "doctor" ? !["error", "doctor"].includes(status.mode) : false;
    button.disabled = status.busy && action !== "logs";
  }
  const atBottom = output.scrollHeight - output.scrollTop - output.clientHeight < 30;
  output.textContent = status.logs;
  if (atBottom) output.scrollTop = output.scrollHeight;
});
for (const button of document.querySelectorAll("[data-action]")) {
  button.addEventListener("click", () => {
    const field = document.querySelector("#gemini-key");
    const key = ["install", "save-key"].includes(button.dataset.action) ? field.value.trim() : "";
    field.value = "";
    window.raySetup.action(button.dataset.action, key).catch((error) => { output.textContent += `\n${error.message}`; });
  });
}
document.querySelector("#close").addEventListener("click", () => window.raySetup.action("close"));
