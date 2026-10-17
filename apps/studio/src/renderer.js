"use strict";

const state = {
  drive: null,
  pickedImages: [],
  running: false,
};

const logEl = document.getElementById("log");
const driveDot = document.getElementById("driveDot");
const driveLabel = document.getElementById("driveLabel");

function appendLog(text) {
  logEl.textContent += text;
  logEl.scrollTop = logEl.scrollHeight;
}

function setRunning(running) {
  state.running = running;
  document.body.classList.toggle("running", running);
}

function basename(p) {
  if (!p) return "";
  return p.replace(/\\/g, "/").split("/").pop();
}

function fillSelect(select, items, { labelFn, valueFn, placeholder } = {}) {
  select.innerHTML = "";
  if (placeholder) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = placeholder;
    select.appendChild(opt);
  }
  for (const item of items) {
    const opt = document.createElement("option");
    opt.value = valueFn ? valueFn(item) : item;
    opt.textContent = labelFn ? labelFn(item) : basename(item);
    select.appendChild(opt);
  }
}

async function refreshDrive() {
  const status = await window.studio.driveStatus();
  state.drive = status;
  if (status.mounted) {
    driveDot.className = "dot ok";
    driveLabel.textContent = `${status.label} — ${status.root}`;
  } else {
    driveDot.className = "dot bad";
    driveLabel.textContent = "Drive not mounted";
  }

  const songs = await window.studio.listMySongs();
  fillSelect(document.getElementById("releaseSong"), songs, {
    placeholder: songs.length ? "Select a song" : "No songs found",
  });

  const huntingMp3s = await window.studio.listHuntingSznMp3s();
  const embedChoices = huntingMp3s.length ? huntingMp3s : songs.filter((s) => s.toLowerCase().endsWith(".mp3"));
  fillSelect(document.getElementById("embedMp3"), embedChoices, {
    placeholder: embedChoices.length
      ? "Select MP3 (DJ Music/HuntingSzn preferred)"
      : "No HuntingSzn MP3s — pick song above or right-click Embed",
  });

  const releases = await window.studio.listReleases();
  fillSelect(document.getElementById("releaseFolder"), releases, {
    placeholder: releases.length ? "Select release folder" : "No releases yet",
  });

  const djFolders = await window.studio.listDjFolders();
  fillSelect(document.getElementById("djDest"), djFolders, {
    placeholder: djFolders.length ? "Select DJ folder" : "No DJ Music folders",
  });

  if (status.paths) {
    document.getElementById("importSource").value = status.paths.platinumNotes || "";
  }

  await refreshSeratoStatus();
  return status;
}

async function refreshReleaseImages() {
  const folder = document.getElementById("releaseFolder").value;
  if (!folder) {
    fillSelect(document.getElementById("finalImage"), [], { placeholder: "Pick a release first" });
    return;
  }
  const images = await window.studio.listReleaseImages(folder);
  fillSelect(document.getElementById("finalImage"), images, {
    placeholder: images.length ? "Select final.png" : "No images in release",
    labelFn: (p) => p.slice(folder.length + 1),
  });
}

async function refreshSeratoStatus() {
  const running = await window.studio.seratoRunning();
  document.getElementById("seratoStatus").textContent = running
    ? "Serato is running — close it before BPM cleanup --write"
    : "Serato is closed — safe for tag/DB cleanup";
}

async function runCmd(pkg, args, env) {
  if (state.running) {
    appendLog("Already running. Stop the current command first.\n");
    return;
  }
  setRunning(true);
  appendLog(`\n--- ${pkg} ${args.join(" ")} ---\n`);
  const result = await window.studio.runCommand({ pkg, args, env });
  if (!result.ok) {
    appendLog(`${result.error}\n`);
    setRunning(false);
  }
}

function requireDrive() {
  if (!state.drive?.mounted || !state.drive.paths) {
    appendLog("Music drive is not mounted.\n");
    return null;
  }
  return state.drive;
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`panel-${btn.dataset.tab}`).classList.add("active");
  });
});

document.getElementById("btnClearLog").addEventListener("click", () => {
  logEl.textContent = "";
});

document.getElementById("btnStop").addEventListener("click", async () => {
  await window.studio.stopCommand();
  appendLog("\n[stop requested]\n");
});

document.getElementById("btnRefreshDrive").addEventListener("click", refreshDrive);
document.getElementById("btnRefreshReleases").addEventListener("click", async () => {
  await refreshDrive();
  await refreshReleaseImages();
});

document.getElementById("releaseFolder").addEventListener("change", refreshReleaseImages);

document.getElementById("btnPickImages").addEventListener("click", async () => {
  const files = await window.studio.pickFiles({
    multi: true,
    filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp"] }],
  });
  state.pickedImages = files.slice(0, 2);
  document.getElementById("pickedImages").textContent = state.pickedImages.length
    ? state.pickedImages.map(basename).join(", ")
    : "none";
});

document.getElementById("btnMashup").addEventListener("click", async () => {
  const drive = requireDrive();
  if (!drive) return;
  const mashup = document.getElementById("mashupName").value.trim();
  const a = document.getElementById("trackA").value.trim();
  const b = document.getElementById("trackB").value.trim();
  if (!mashup || !a || !b) {
    appendLog("Need mashup name and both Artist:Title tracks.\n");
    return;
  }
  const args = [
    "huntingszn-cover",
    "mashup",
    "--mashup",
    mashup,
    "--tracks",
    a,
    "--tracks",
    b,
    "--volume",
    drive.paths.releases,
  ];
  for (const img of state.pickedImages) {
    args.push("--image", img);
  }
  await runCmd("huntingszn-cover", args);
});

async function transformWith(prompt) {
  const image = document.getElementById("finalImage").value;
  if (!image) {
    appendLog("Pick a final/source image first (or pick files after mashup).\n");
    return;
  }
  const drive = requireDrive();
  if (!drive) return;
  const outDir = document.getElementById("releaseFolder").value || drive.paths.releases;
  await runCmd("huntingszn-cover", [
    "huntingszn-cover",
    "transform",
    "--image",
    image,
    "--prompts",
    prompt,
    "--output",
    outDir,
  ]);
}

document.getElementById("btnTransformClean").addEventListener("click", () => transformWith("clean"));
document.getElementById("btnTransformCrystal").addEventListener("click", () => transformWith("crystal"));

document.getElementById("btnEmbed").addEventListener("click", async () => {
  const image = document.getElementById("finalImage").value;
  const mp3 = document.getElementById("embedMp3").value || document.getElementById("releaseSong").value;
  if (!image || !mp3) {
    appendLog("Pick a final image and an MP3.\n");
    return;
  }
  await runCmd("library-tools", [
    "embed-cover",
    "--image",
    image,
    "--mp3",
    mp3,
  ]);
});

document.getElementById("btnVisualizer").addEventListener("click", async () => {
  appendLog("\nStarting Beat Visualizer…\n");
  const result = await window.studio.startVisualizer();
  if (!result.ok) {
    appendLog(`Visualizer failed: ${result.error}\n`);
  } else {
    appendLog(`Opened ${result.frontend}\n`);
  }
});

document.getElementById("btnOpenViWizard").addEventListener("click", async () => {
  const r = await window.studio.openApp("viwizard");
  appendLog(r.ok ? `Opened ViWizard: ${r.path}\n` : `${r.error}\n`);
});
document.getElementById("btnOpenPN").addEventListener("click", async () => {
  const r = await window.studio.openApp("platinumNotes");
  appendLog(r.ok ? `Opened Platinum Notes: ${r.path}\n` : `${r.error}\n`);
});
document.getElementById("btnOpenMIK").addEventListener("click", async () => {
  const r = await window.studio.openApp("mik");
  appendLog(r.ok ? `Opened Mixed In Key: ${r.path}\n` : `${r.error}\n`);
});
document.getElementById("btnOpenSerato").addEventListener("click", async () => {
  const r = await window.studio.openApp("serato");
  appendLog(r.ok ? `Opened Serato: ${r.path}\n` : `${r.error}\n`);
  await refreshSeratoStatus();
});

document.getElementById("btnPnPipeline").addEventListener("click", async () => {
  const drive = requireDrive();
  if (!drive) return;
  await runCmd("library-tools", ["pn-pipeline", "--root", drive.paths.platinumNotes]);
});

document.getElementById("btnPnDry").addEventListener("click", async () => {
  const drive = requireDrive();
  if (!drive) return;
  await runCmd("library-tools", ["pn-pipeline", "--root", drive.paths.platinumNotes, "--dry-run"]);
});

document.getElementById("btnImportPreview").addEventListener("click", async () => {
  const sourceDir = document.getElementById("importSource").value;
  const destDir = document.getElementById("djDest").value;
  if (!sourceDir || !destDir) {
    appendLog("Need Platnium Notes source and DJ destination.\n");
    return;
  }
  const preview = await window.studio.previewImport({ sourceDir, destDir });
  document.getElementById("importPreview").textContent = JSON.stringify(
    {
      count: preview.count,
      wouldCopy: preview.wouldCopy,
      wouldSkip: preview.wouldSkip,
      sample: preview.files.slice(0, 20).map((f) => ({
        from: basename(f.source),
        to: basename(f.dest),
        exists: f.exists,
      })),
    },
    null,
    2
  );
});

document.getElementById("btnImportRun").addEventListener("click", async () => {
  const sourceDir = document.getElementById("importSource").value;
  const destDir = document.getElementById("djDest").value;
  if (!sourceDir || !destDir) {
    appendLog("Need Platnium Notes source and DJ destination.\n");
    return;
  }
  const result = await window.studio.runImport({ sourceDir, destDir, overwrite: false });
  appendLog(`Import done: copied ${result.copied}, skipped ${result.skipped}\n`);
  document.getElementById("importPreview").textContent = JSON.stringify(result, null, 2);
});

document.getElementById("btnDedupe").addEventListener("click", async () => {
  const dest = document.getElementById("djDest").value;
  const args = ["library-dedupe"];
  if (dest) args.push("--library", dest);
  await runCmd("library-tools", args);
});

document.getElementById("btnMikClear").addEventListener("click", async () => {
  const drive = requireDrive();
  if (!drive) return;
  await runCmd("library-tools", ["mik-clear-cues", "--dry-run", drive.paths.platinumNotes]);
});

async function seratoBpm(write) {
  const drive = requireDrive();
  if (!drive) return;
  const running = await window.studio.seratoRunning();
  if (write && running) {
    appendLog("Close Serato DJ Pro before --write.\n");
    return;
  }
  const args = [
    "serato-bpm-cleanup",
    "--library",
    drive.paths.djMusic,
    "--db",
    drive.paths.seratoDb,
  ];
  if (write) args.push("--write");
  await runCmd("serato-bpm-cleanup", args);
}

document.getElementById("btnSeratoBpm").addEventListener("click", () => seratoBpm(false));
document.getElementById("btnSeratoBpmWrite").addEventListener("click", () => seratoBpm(true));

document.getElementById("btnStemSplit").addEventListener("click", async () => {
  const drive = requireDrive();
  if (!drive) return;
  await runCmd("stem-split", [
    "stem-split",
    "--input",
    drive.paths.stemInput,
    "--output",
    drive.paths.stemOutput,
  ]);
});

document.getElementById("btnOpenScripts").addEventListener("click", async () => {
  const status = state.drive || (await window.studio.driveStatus());
  await window.studio.openPath(status.scripts || status.scriptsRoot);
});

document.getElementById("btnOpenDrive").addEventListener("click", async () => {
  const drive = requireDrive();
  if (!drive) return;
  await window.studio.openPath(drive.root);
});

window.studio.onLog((text) => appendLog(text));
window.studio.onExit((code) => {
  setRunning(false);
  appendLog(`\n[exit ${code}]\n`);
  refreshDrive();
});

document.getElementById("btnEmbed").addEventListener("contextmenu", async (e) => {
  e.preventDefault();
  const files = await window.studio.pickFiles({
    filters: [{ name: "MP3", extensions: ["mp3"] }],
  });
  if (files[0]) {
    fillSelect(document.getElementById("embedMp3"), [files[0]], {});
    document.getElementById("embedMp3").value = files[0];
  }
});

refreshDrive();
appendLog("HuntingSzn Studio ready.\n");
