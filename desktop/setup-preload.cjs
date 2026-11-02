const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("raySetup", {
  action: (name) => ipcRenderer.invoke("ray:setup-action", name),
  onStatus(callback) {
    const handler = (_event, status) => callback(status);
    ipcRenderer.on("ray:status", handler);
    ipcRenderer.send("ray:setup-ready");
    return () => ipcRenderer.removeListener("ray:status", handler);
  },
});
