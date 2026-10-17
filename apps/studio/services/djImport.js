"use strict";

const fs = require("fs");
const path = require("path");

const AUDIO_EXTS = new Set([".mp3", ".wav", ".aiff", ".aif", ".flac", ".m4a"]);

function listImportCandidates(sourceDir) {
  if (!sourceDir || !fs.existsSync(sourceDir)) return [];
  const files = [];
  const walk = (dir) => {
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!entry.name.startsWith(".")) walk(full);
        continue;
      }
      const ext = path.extname(entry.name).toLowerCase();
      if (!AUDIO_EXTS.has(ext)) continue;
      // Prefer cleaned files: skip leftover *_pn* if a non-_pn twin exists later.
      files.push(full);
    }
  };
  walk(sourceDir);
  return files.sort((a, b) => a.localeCompare(b));
}

function previewImport({ sourceDir, destDir }) {
  const sources = listImportCandidates(sourceDir);
  const plan = sources.map((src) => {
    const dest = path.join(destDir, path.basename(src));
    return {
      source: src,
      dest,
      exists: fs.existsSync(dest),
    };
  });
  return {
    count: plan.length,
    wouldCopy: plan.filter((p) => !p.exists).length,
    wouldSkip: plan.filter((p) => p.exists).length,
    files: plan,
  };
}

function runImport({ sourceDir, destDir, overwrite = false }) {
  const preview = previewImport({ sourceDir, destDir });
  if (!fs.existsSync(destDir)) {
    fs.mkdirSync(destDir, { recursive: true });
  }
  const results = [];
  for (const item of preview.files) {
    if (item.exists && !overwrite) {
      results.push({ ...item, action: "skipped" });
      continue;
    }
    fs.copyFileSync(item.source, item.dest);
    results.push({ ...item, action: item.exists ? "overwrote" : "copied" });
  }
  return {
    copied: results.filter((r) => r.action === "copied" || r.action === "overwrote").length,
    skipped: results.filter((r) => r.action === "skipped").length,
    files: results,
  };
}

module.exports = { previewImport, runImport, listImportCandidates };
