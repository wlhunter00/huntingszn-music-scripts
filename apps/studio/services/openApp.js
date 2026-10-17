"use strict";

const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");

const APP_PATHS = {
  mik: [
    path.join(process.env["ProgramFiles"] || "C:\\Program Files", "Mixed In Key", "Mixed in Key 11", "MixedInKey.exe"),
  ],
  platinumNotes: [
    path.join(
      process.env.LOCALAPPDATA || "",
      "Programs",
      "Mixed In Key",
      "Platinum Notes 10",
      "Platinum Notes.exe"
    ),
  ],
  serato: [
    path.join(
      process.env["ProgramFiles"] || "C:\\Program Files",
      "Serato",
      "Serato DJ Pro",
      "Serato DJ Pro.exe"
    ),
  ],
  viwizard: [
    path.join(
      process.env["ProgramFiles(x86)"] || "C:\\Program Files (x86)",
      "Viwizard Spotify Music Converter",
      "Spotify Music Converter.exe"
    ),
  ],
};

function resolveExe(name) {
  const candidates = APP_PATHS[name] || [];
  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  return null;
}

function openApp(name) {
  const exe = resolveExe(name);
  if (!exe) {
    return { ok: false, error: `Executable not found for ${name}` };
  }
  const child = spawn(exe, [], {
    detached: true,
    stdio: "ignore",
    windowsHide: false,
  });
  child.unref();
  return { ok: true, path: exe };
}

function seratoIsRunning() {
  return new Promise((resolve) => {
    if (process.platform !== "win32") {
      resolve(false);
      return;
    }
    const { execFile } = require("child_process");
    execFile(
      "tasklist",
      ["/fo", "csv", "/nh"],
      { windowsHide: true, timeout: 10000 },
      (err, stdout) => {
        if (err) {
          resolve(false);
          return;
        }
        const lower = String(stdout || "").toLowerCase();
        resolve(
          lower.includes("serato dj pro") ||
            lower.includes("seratodj") ||
            /"serato\.exe"/i.test(stdout || "")
        );
      }
    );
  });
}

module.exports = { openApp, resolveExe, seratoIsRunning, APP_PATHS };
