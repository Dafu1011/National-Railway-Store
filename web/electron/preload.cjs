const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("zhifengUpdates", {
  getAppVersion: () => ipcRenderer.invoke("updates:get-app-version"),
  install: (update) => ipcRenderer.invoke("updates:install", update),
});
