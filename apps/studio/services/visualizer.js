"use strict";

const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const http = require("http");

const DEFAULT_REPO = path.join(
  process.env.USERPROFILE || "",
  "Documents",
  "GitHub",
  "visualizer-thumbnail-generator"
);

let backendProc = null;
let frontendProc = null;

function visualizerRepo() {
  return process.env.VISUALIZER_REPO || DEFAULT_REPO;
}

function waitForUrl(url, { timeoutMs = 60000, intervalMs = 500 } = {}) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get(url, (res) => {
        res.resume();
        resolve(true);
      });
      req.on("error", () => {
        if (Date.now() - start > timeoutMs) {
          reject(new Error(`Timed out waiting for ${url}`));
          return;
        }
        setTimeout(tick, intervalMs);
      });
    };
    tick();
  });
}

function startVisualizer({ onLog } = {}) {
  const repo = visualizerRepo();
  if (!fs.existsSync(repo)) {
    return Promise.reject(new Error(`Visualizer repo not found: ${repo}`));
  }
  const log = (msg) => {
    if (onLog) onLog(msg);
  };

  const backendPy = path.join(repo, "backend", ".venv", "Scripts", "python.exe");
  const backendMain = path.join(repo, "backend", "main.py");
  const frontendDir = path.join(repo, "frontend");

  if (!backendProc || backendProc.killed) {
    const py = fs.existsSync(backendPy) ? backendPy : "python";
    backendProc = spawn(py, [backendMain], {
      cwd: path.join(repo, "backend"),
      windowsHide: true,
      env: { ...process.env, PYTHONUTF8: "1" },
    });
    backendProc.stdout.on("data", (b) => log(`[visualizer-backend] ${b}`));
    backendProc.stderr.on("data", (b) => log(`[visualizer-backend] ${b}`));
    backendProc.on("exit", (code) => {
      log(`[visualizer-backend] exited ${code}\n`);
      backendProc = null;
    });
  }

  if (!frontendProc || frontendProc.killed) {
    const npmCmd = process.platform === "win32" ? "npm.cmd" : "npm";
    frontendProc = spawn(npmCmd, ["run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"], {
      cwd: frontendDir,
      windowsHide: true,
      shell: true,
    });
    frontendProc.stdout.on("data", (b) => log(`[visualizer-frontend] ${b}`));
    frontendProc.stderr.on("data", (b) => log(`[visualizer-frontend] ${b}`));
    frontendProc.on("exit", (code) => {
      log(`[visualizer-frontend] exited ${code}\n`);
      frontendProc = null;
    });
  }

  return waitForUrl("http://127.0.0.1:5173")
    .then(() => waitForUrl("http://127.0.0.1:8000").catch(() => true))
    .then(() => ({
      frontend: "http://127.0.0.1:5173",
      backend: "http://127.0.0.1:8000",
      repo,
    }));
}

function stopVisualizer() {
  for (const proc of [frontendProc, backendProc]) {
    if (proc && !proc.killed) proc.kill();
  }
  frontendProc = null;
  backendProc = null;
}

module.exports = { startVisualizer, stopVisualizer, visualizerRepo };
