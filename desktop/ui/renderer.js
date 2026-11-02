const output = document.querySelector("#output");
window.raySetup.onStatus((status) => {
  document.body.dataset.mode = status.mode;
  document.querySelector("#message").textContent = status.message;
  document.querySelector("#hint").textContent = status.mode === "setup"
    ? "Choose a checkout containing scripts/ray, or install into ~/ray-ai-assistant. Docker Desktop, Git, Node, pnpm and uv are required."
    : status.mode === "error" ? "Review the diagnostic output, open logs, then retry. Services are not stopped when you close Ray."
    : "Your checkout and data stay on this computer.";
  for (const action of ["choose", "install", "retry", "doctor", "logs"]) {
    const button = document.querySelector(`#${action}`);
    button.hidden = ["choose", "install"].includes(action) ? status.mode !== "setup" || (action === "install" && !status.allowInstall)
      : action === "retry" ? status.mode !== "error"
      : action === "doctor" ? !["error", "doctor"].includes(status.mode) : false;
    button.disabled = status.busy && action !== "logs";
  }
  const atBottom = output.scrollHeight - output.scrollTop - output.clientHeight < 30;
  output.textContent = status.logs;
  if (atBottom) output.scrollTop = output.scrollHeight;
});
for (const button of document.querySelectorAll("[data-action]")) {
  button.addEventListener("click", () => {
    window.raySetup.action(button.dataset.action).catch((error) => { output.textContent += `\n${error.message}`; });
  });
}
document.querySelector("#close").addEventListener("click", () => window.raySetup.action("close"));
