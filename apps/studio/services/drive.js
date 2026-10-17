"use strict";

const fs = require("fs");
const path = require("path");
const { execFile } = require("child_process");

const PREFERRED_LABEL = "HuntingSzn";
const LEGACY_LABEL = "Will Hunter Music";
const VOLUME_NAMES = new Set([PREFERRED_LABEL, LEGACY_LABEL]);

const AUDIO_EXTS = new Set([".mp3", ".wav", ".aiff", ".aif", ".flac", ".m4a"]);
const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".webp"]);

function scriptsRoot() {
  // apps/studio/services -> apps/studio -> apps -> Scripts
  return path.resolve(__dirname, "..", "..", "..");
}

function driveRootFromScripts() {
  return path.dirname(scriptsRoot());
}

function getVolumeLabel(root) {
  return new Promise((resolve) => {
    if (process.platform !== "win32") {
      resolve(path.basename(root));
      return;
    }
    const letter = root.replace(/[/\\]+$/, "").slice(0, 2);
    execFile(
      "powershell.exe",
      [
        "-NoProfile",
        "-Command",
        `(Get-Volume -DriveLetter '${letter[0]}' -ErrorAction SilentlyContinue).FileSystemLabel`,
      ],
      { windowsHide: true, timeout: 8000 },
      (err, stdout) => {
        if (err) {
          resolve("");
          return;
        }
        resolve(String(stdout || "").trim());
      }
    );
  });
}

function hasScriptsRepo(root) {
  return fs.existsSync(path.join(root, "Scripts", "pyproject.toml"));
}

async function detectDrive() {
  const candidates = [];

  if (process.platform === "win32") {
    for (let i = 0; i < 26; i += 1) {
      const letter = String.fromCharCode(65 + i);
      const root = `${letter}:\\`;
      try {
        if (!fs.existsSync(root)) continue;
      } catch {
        continue;
      }
      if (!hasScriptsRepo(root)) continue;
      const label = await getVolumeLabel(root);
      if (VOLUME_NAMES.has(label)) {
        candidates.push({ root, label });
      }
    }
  } else if (process.platform === "darwin") {
    for (const name of [PREFERRED_LABEL, LEGACY_LABEL]) {
      const root = path.join("/Volumes", name);
      if (hasScriptsRepo(root)) {
        candidates.push({ root, label: name });
      }
    }
  }

  const preferred = candidates.find((c) => c.label === PREFERRED_LABEL);
  const chosen = preferred || candidates[0] || null;

  if (!chosen) {
    // Fallback: repo parent when it looks like the music drive.
    const fallback = driveRootFromScripts();
    if (hasScriptsRepo(fallback)) {
      const label = (await getVolumeLabel(fallback)) || PREFERRED_LABEL;
      return {
        mounted: true,
        root: fallback,
        label,
        scripts: path.join(fallback, "Scripts"),
      };
    }
    return { mounted: false, root: null, label: null, scripts: scriptsRoot() };
  }

  return {
    mounted: true,
    root: chosen.root,
    label: chosen.label,
    scripts: path.join(chosen.root, "Scripts"),
  };
}

function listAudioFiles(dir, { recursive = false, limit = 200 } = {}) {
  if (!dir || !fs.existsSync(dir)) return [];
  const out = [];
  const walk = (current, depth) => {
    let entries;
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (out.length >= limit) return;
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        if (recursive && depth < 3 && !entry.name.startsWith(".")) {
          walk(full, depth + 1);
        }
        continue;
      }
      if (AUDIO_EXTS.has(path.extname(entry.name).toLowerCase())) {
        out.push(full);
      }
    }
  };
  walk(dir, 0);
  return out.sort((a, b) => a.localeCompare(b));
}

function listDirs(dir) {
  if (!dir || !fs.existsSync(dir)) return [];
  try {
    return fs
      .readdirSync(dir, { withFileTypes: true })
      .filter((e) => e.isDirectory() && !e.name.startsWith("."))
      .map((e) => path.join(dir, e.name))
      .sort((a, b) => a.localeCompare(b));
  } catch {
    return [];
  }
}

function listImages(dir, { limit = 100 } = {}) {
  if (!dir || !fs.existsSync(dir)) return [];
  const out = [];
  const walk = (current, depth) => {
    let entries;
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (out.length >= limit) return;
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        if (depth < 3 && !entry.name.startsWith(".")) walk(full, depth + 1);
        continue;
      }
      if (IMAGE_EXTS.has(path.extname(entry.name).toLowerCase())) {
        out.push(full);
      }
    }
  };
  walk(dir, 0);
  return out.sort((a, b) => a.localeCompare(b));
}

function pathsForDrive(root) {
  if (!root) return null;
  return {
    mySongs: path.join(root, "My Songs"),
    thumbnails: path.join(root, "Thumbnails"),
    releases: path.join(root, "Thumbnails", "Releases"),
    djMusic: path.join(root, "DJ Music"),
    djHuntingSzn: path.join(root, "DJ Music", "HuntingSzn"),
    platinumNotes: path.join(root, "Platnium Notes"),
    downloads: path.join(root, "Downloads"),
    stemInput: path.join(root, "Stem Splitting", "songs-to-split"),
    stemOutput: path.join(root, "Stem Splitting", "stem-output"),
    seratoDb: path.join(root, "_Serato_", "database V2"),
  };
}

module.exports = {
  scriptsRoot,
  detectDrive,
  listAudioFiles,
  listDirs,
  listImages,
  pathsForDrive,
  PREFERRED_LABEL,
};
