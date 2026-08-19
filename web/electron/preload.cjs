const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("zhifengUpdates", {
  getAppVersion: () => ipcRenderer.invoke("updates:get-app-version"),
  install: (update) => ipcRenderer.invoke("updates:install", update),
  onDownloadProgress: (callback) => {
    const listener = (_event, progress) => callback(progress);
    ipcRenderer.on("updates:download-progress", listener);
    return () => ipcRenderer.removeListener("updates:download-progress", listener);
  },
});
