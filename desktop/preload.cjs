const { contextBridge, ipcRenderer } = require("electron");

if (location.origin === "http://127.0.0.1:3000") {
  contextBridge.exposeInMainWorld("rayDesktop", {
    onListen(callback) {
      if (typeof callback !== "function") return () => {};
      const listener = () => callback();
      ipcRenderer.on("ray:listen", listener);
      ipcRenderer.send("ray:listen-ready");
      return () => ipcRenderer.removeListener("ray:listen", listener);
    },
  });
}
