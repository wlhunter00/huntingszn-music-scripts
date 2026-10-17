"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("studio", {
  driveStatus: () => ipcRenderer.invoke("drive:status"),
  listMySongs: () => ipcRenderer.invoke("drive:listMySongs"),
  listDjFolders: () => ipcRenderer.invoke("drive:listDjFolders"),
  listReleases: () => ipcRenderer.invoke("drive:listReleases"),
  listReleaseImages: (dir) => ipcRenderer.invoke("drive:listReleaseImages", dir),
  listPnAudio: () => ipcRenderer.invoke("drive:listPnAudio"),
  listHuntingSznMp3s: () => ipcRenderer.invoke("drive:listHuntingSznMp3s"),
  pickFiles: (opts) => ipcRenderer.invoke("dialog:pickFiles", opts),
  pickFolder: () => ipcRenderer.invoke("dialog:pickFolder"),
  runCommand: (opts) => ipcRenderer.invoke("run:command", opts),
  stopCommand: () => ipcRenderer.invoke("run:stop"),
  openApp: (name) => ipcRenderer.invoke("app:open", name),
  seratoRunning: () => ipcRenderer.invoke("app:seratoRunning"),
  previewImport: (payload) => ipcRenderer.invoke("djImport:preview", payload),
  runImport: (payload) => ipcRenderer.invoke("djImport:run", payload),
  startVisualizer: () => ipcRenderer.invoke("visualizer:start"),
  openPath: (target) => ipcRenderer.invoke("shell:openPath", target),
  showItem: (target) => ipcRenderer.invoke("shell:showItem", target),
  onLog: (cb) => {
    const listener = (_e, text) => cb(text);
    ipcRenderer.on("run:log", listener);
    return () => ipcRenderer.removeListener("run:log", listener);
  },
  onExit: (cb) => {
    const listener = (_e, code) => cb(code);
    ipcRenderer.on("run:exit", listener);
    return () => ipcRenderer.removeListener("run:exit", listener);
  },
});
