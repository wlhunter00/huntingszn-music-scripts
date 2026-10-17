"use strict";

const { spawn } = require("child_process");
const path = require("path");
const { EventEmitter } = require("events");
const { scriptsRoot } = require("./drive");

let active = null;

function resolveUv() {
  if (process.env.UV_BIN) return process.env.UV_BIN;
  if (process.platform === "win32") {
    const local = path.join(process.env.USERPROFILE || "", ".local", "bin", "uv.exe");
    return local;
  }
  return "uv";
}

/**
 * Run `uv run --package <pkg> ...args` from Scripts root.
 * Streams stdout/stderr via returned emitter events: log, exit, error.
 */
function runUv({ pkg, args = [], cwd, env = {} } = {}) {
  if (active && !active.killed) {
    const err = new Error("Another command is already running. Stop it first.");
    const emitter = new EventEmitter();
    process.nextTick(() => emitter.emit("error", err));
    return { emitter, kill: () => {} };
  }

  const root = cwd || scriptsRoot();
  const uv = resolveUv();
  const argv = ["run", "--package", pkg, ...args];
  const child = spawn(uv, argv, {
    cwd: root,
    env: {
      ...process.env,
      PYTHONUTF8: "1",
      PYTHONIOENCODING: "utf-8",
      ...env,
    },
    windowsHide: true,
  });
  active = child;

  const emitter = new EventEmitter();
  const prefix = `$ uv ${argv.join(" ")}\n`;
  emitter.emit("log", prefix);

  child.stdout.on("data", (buf) => emitter.emit("log", buf.toString()));
  child.stderr.on("data", (buf) => emitter.emit("log", buf.toString()));
  child.on("error", (err) => {
    if (active === child) active = null;
    emitter.emit("error", err);
  });
  child.on("close", (code) => {
    if (active === child) active = null;
    emitter.emit("exit", code ?? 1);
  });

  return {
    emitter,
    kill: () => {
      if (!child.killed) child.kill();
    },
  };
}

function stopActive() {
  if (active && !active.killed) {
    active.kill();
    return true;
  }
  return false;
}

function isBusy() {
  return Boolean(active && !active.killed);
}

module.exports = { runUv, stopActive, isBusy, resolveUv };
