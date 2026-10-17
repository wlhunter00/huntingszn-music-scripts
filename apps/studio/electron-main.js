"use strict";

const { app, BrowserWindow, ipcMain, shell, dialog } = require("electron");
const path = require("path");
const {
  detectDrive,
  listAudioFiles,
  listDirs,
  listImages,
  pathsForDrive,
  scriptsRoot,
} = require("./services/drive");
const { runUv, stopActive, isBusy } = require("./services/runUv");
const { openApp, seratoIsRunning } = require("./services/openApp");
const { previewImport, runImport } = require("./services/djImport");
const { startVisualizer, stopVisualizer } = require("./services/visualizer");

let mainWindow = null;
let killCurrent = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 900,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
    title: "HuntingSzn Studio",
  });
  mainWindow.loadFile(path.join(__dirname, "src", "index.html"));
}

function sendLog(text) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("run:log", text);
  }
}

function sendExit(code) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("run:exit", code);
  }
}

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  stopActive();
  stopVisualizer();
  if (process.platform !== "darwin") app.quit();
});

ipcMain.handle("drive:status", async () => {
  const drive = await detectDrive();
  return {
    ...drive,
    paths: pathsForDrive(drive.root),
    scriptsRoot: scriptsRoot(),
    busy: isBusy(),
  };
});

ipcMain.handle("drive:listMySongs", async () => {
  const drive = await detectDrive();
  if (!drive.mounted) return [];
  return listAudioFiles(path.join(drive.root, "My Songs"), { recursive: false });
});

ipcMain.handle("drive:listDjFolders", async () => {
  const drive = await detectDrive();
  if (!drive.mounted) return [];
  return listDirs(path.join(drive.root, "DJ Music"));
});

ipcMain.handle("drive:listReleases", async () => {
  const drive = await detectDrive();
  if (!drive.mounted) return [];
  return listDirs(path.join(drive.root, "Thumbnails", "Releases"));
});

ipcMain.handle("drive:listReleaseImages", async (_e, releaseDir) => {
  return listImages(releaseDir, { limit: 80 });
});

ipcMain.handle("drive:listPnAudio", async () => {
  const drive = await detectDrive();
  if (!drive.mounted) return [];
  return listAudioFiles(path.join(drive.root, "Platnium Notes"), {
    recursive: true,
    limit: 300,
  });
});

ipcMain.handle("drive:listHuntingSznMp3s", async () => {
  const drive = await detectDrive();
  if (!drive.mounted) return [];
  return listAudioFiles(path.join(drive.root, "DJ Music", "HuntingSzn"), {
    recursive: true,
    limit: 300,
  });
});

ipcMain.handle("dialog:pickFiles", async (_e, { filters, multi } = {}) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: multi ? ["openFile", "multiSelections"] : ["openFile"],
    filters: filters || [{ name: "All", extensions: ["*"] }],
  });
  return result.canceled ? [] : result.filePaths;
});

ipcMain.handle("dialog:pickFolder", async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openDirectory"],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle("run:command", async (_e, { pkg, args, env }) => {
  if (isBusy()) {
    return { ok: false, error: "A command is already running." };
  }
  const { emitter, kill } = runUv({ pkg, args, env });
  killCurrent = kill;
  emitter.on("log", sendLog);
  emitter.on("error", (err) => {
    sendLog(`\nERROR: ${err.message}\n`);
    sendExit(1);
  });
  emitter.on("exit", (code) => {
    killCurrent = null;
    sendExit(code);
  });
  return { ok: true };
});

ipcMain.handle("run:stop", async () => {
  const stopped = stopActive();
  if (killCurrent) killCurrent();
  killCurrent = null;
  return { stopped };
});

ipcMain.handle("app:open", async (_e, name) => openApp(name));

ipcMain.handle("app:seratoRunning", async () => seratoIsRunning());

ipcMain.handle("djImport:preview", async (_e, payload) => previewImport(payload));

ipcMain.handle("djImport:run", async (_e, payload) => runImport(payload));

ipcMain.handle("visualizer:start", async () => {
  try {
    const info = await startVisualizer({
      onLog: (msg) => sendLog(typeof msg === "string" ? msg : String(msg)),
    });
    await shell.openExternal(info.frontend);
    return { ok: true, ...info };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("shell:openPath", async (_e, target) => {
  if (!target) return { ok: false };
  await shell.openPath(target);
  return { ok: true };
});

ipcMain.handle("shell:showItem", async (_e, target) => {
  if (!target) return { ok: false };
  shell.showItemInFolder(target);
  return { ok: true };
});
