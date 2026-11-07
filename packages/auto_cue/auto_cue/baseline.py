"""Run eval_kfold with durable responses and conservative spending controls."""

import argparse
import hashlib
import importlib.util
import json
import os
import pickle
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

import httpx

import auto_cue
from auto_cue.features import extract_features

REPO = Path(__file__).resolve().parents[3]
ROOT = Path.home() / "autocue-data" / "baseline"
POOL_DIR = Path("/workspace/gold-pool")
QA_DIR = Path("/workspace/qa-all")
LIMIT = 15.0
context = threading.local()
lock = threading.Lock()
run_fd = None


class BaselineStop(BaseException):
    pass


def durable_json(path, payload):
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w") as stream:
        json.dump(payload, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    if os.name != "nt":
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def ledger():
    records = [json.loads(p.read_text()) for p in (ROOT / "responses").glob("*.json")]
    return dict(
        actual_cost=sum(r.get("cost", 0.0) for r in records),
        uncertain_reserved=sum(
            r.get("reservation", 0.0) for r in records if r["status"] == "pending"
        ),
        successful_requests=sum(r["status"] == "success" for r in records),
        records=len(records),
        hard_limit=LIMIT,
    )


def stop(reason):
    durable_json(ROOT / "STOP.json", dict(reason=reason, time=time.time(), ledger=ledger()))
    raise BaselineStop(reason)


def repair_prediction_tail(path):
    if not path.exists():
        return
    data = path.read_bytes()
    lines = data.splitlines(keepends=True)
    offset = 0
    for index, line in enumerate(lines):
        if line.strip():
            try:
                json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                if index != len(lines) - 1:
                    raise
                data = data[:offset]
                break
        offset += len(line)
    if data and not data.endswith(b"\n"):
        data += b"\n"
    if data != path.read_bytes():
        temp = path.with_suffix(".repair.tmp")
        try:
            with temp.open("wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def install_controls(e):
    repair_prediction_tail(e.PRED_PATH)
    original_post = httpx.Client.post

    def guarded_post(client, url, **kwargs):
        body = kwargs.get("json")
        if str(url) != "https://api.openai.com/v1/chat/completions" or body is None:
            stop("Unexpected API endpoint/request shape")
        encoded = json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
        key = hashlib.sha256(encoded).hexdigest()
        path = ROOT / "responses" / f"{key}.json"
        with lock:
            if (ROOT / "STOP.json").exists():
                raise BaselineStop("Persisted stop marker exists; no API requests allowed")
            if path.exists():
                saved = json.loads(path.read_text())
                if saved["status"] != "success":
                    stop(
                        "Prior request has uncertain or failed outcome; "
                        "refusing automatic repayment"
                    )
                print(f"CACHE response {getattr(context, 'track', '')}", flush=True)
                return httpx.Response(
                    200, json=saved["response"], request=httpx.Request("POST", url)
                )
            if body["model"] != "gpt-6.1-terra" or body.get("max_completion_tokens") != 4096:
                stop("Unexpected model or completion cap")
            # UTF-8 bytes upper-bound ordinary BPE input token counts; leave
            # another 8192 tokens for framing/schema overhead.
            reservation = (len(encoded) + 8192 + 4096 * 5) / 1_000_000
            prior_attempts = len(list((ROOT / "responses").glob(f"{key}.attempt-*.json")))
            if prior_attempts >= 4:
                stop("Transient retry limit exhausted for this request")
            for attempt in range(prior_attempts + 1, 5):
                current = ledger()
                if current["actual_cost"] + current["uncertain_reserved"] + reservation > LIMIT:
                    stop("Insufficient remaining budget for conservative next-request reservation")
                receipt = dict(
                    status="pending",
                    reservation=reservation,
                    attempt=attempt,
                    track=getattr(context, "track", None),
                    request=body,
                    started_at=time.time(),
                )
                durable_json(path, receipt)
                transient = None
                try:
                    response = original_post(client, url, **kwargs)
                    if 500 <= response.status_code < 600:
                        transient = f"HTTP {response.status_code}"
                except httpx.TransportError as exc:
                    transient = type(exc).__name__
                if transient is None:
                    break
                receipt.update(transient_error=transient, completed_at=time.time())
                durable_json(path, receipt)
                path.rename(ROOT / "responses" / f"{key}.attempt-{attempt}-{time.time_ns()}.json")
                durable_json(ROOT / "ledger.json", ledger())
                if attempt == 4:
                    stop("Transient retry limit exhausted; uncertain reservations retained")
                delay = 2**attempt
                print(f"RETRY {transient}, attempt {attempt}/4; backoff {delay}s", flush=True)
                time.sleep(delay)
            if response.status_code != 200:
                receipt.update(
                    status="http-error",
                    status_code=response.status_code,
                    cost=0.0,
                    completed_at=time.time(),
                )
                durable_json(path, receipt)
                stop(f"API HTTP {response.status_code}; no further requests")
            try:
                payload = response.json()
                usage = payload["usage"]
                input_tokens = usage["prompt_tokens"]
                output_tokens = usage["completion_tokens"]
                cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
                cost = ((input_tokens - cached) + cached * 0.05 + output_tokens * 5) / 1_000_000
            except Exception:
                receipt.update(response_text=response.text)
                durable_json(path, receipt)
                stop("API success without usable usage; retained conservative reservation")
            receipt.update(
                status="success", response=payload, cost=cost, usage=usage, completed_at=time.time()
            )
            durable_json(path, receipt)
            totals = ledger()
            durable_json(ROOT / "ledger.json", totals)
            print(
                f"BILLING requests={totals['successful_requests']} "
                f"cost=${totals['actual_cost']:.6f}",
                flush=True,
            )
            if cost > reservation or totals["actual_cost"] > LIMIT:
                stop("Actual response cost exceeded conservative reservation/budget")
            return response

    httpx.Client.post = guarded_post
    original_predict = e.predict_track

    def predict(track, *args, **kwargs):
        context.track = track.path
        try:
            return original_predict(track, *args, **kwargs)
        except Exception as exc:
            stop(f"Prediction/parsing/scoring failure: {type(exc).__name__}; response cached")

    e.predict_track = predict

    def append(row):
        # The response is already durable before ranker scoring and this row.
        with e.PRED_PATH.open("a") as stream:
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    e.append_pred = append
    original_report = e.write_report
    e.write_report = lambda pool, qa, cost: original_report(pool, qa, ledger()["actual_cost"])


def audio_fingerprint(audio):
    with audio.open("rb") as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"Audio changed while hashing: {audio}")
    return dict(size=after.st_size, sha256=digest)


def fingerprint_audio_roots(pool_dir, qa_dir):
    result, resolved = {}, {}
    for label, root in [("pool", pool_dir), ("qa", qa_dir)]:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".mp3", ".flac"}:
                canonical = path.resolve()
                if canonical not in resolved:
                    resolved[canonical] = audio_fingerprint(path)
                result[f"{label}/{path.relative_to(root)}"] = resolved[canonical]
    return result


def check_resume_manifest(path, sha, data, audio):
    if not path.exists():
        return
    saved = json.loads(path.read_text())
    if saved["sha"] != sha:
        raise SystemExit("Cannot resume predictions with different source revision")
    if saved.get("data_sha256") != data:
        raise SystemExit("Cannot resume predictions with different data")
    if saved.get("audio") != audio:
        raise SystemExit("Cannot resume predictions with different audio")


def feature_cache_path(cache_dir, audio, bpm, first_beat_s):
    digest = audio_fingerprint(audio)["sha256"]
    grid = hashlib.sha256(json.dumps([bpm, first_beat_s]).encode()).hexdigest()
    return cache_dir / f"{digest}-{grid}.pkl"


def extract_and_cache(cache_dir, spec):
    key, audio, bpm, first_beat_s = spec
    audio = Path(audio)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = feature_cache_path(cache_dir, audio, bpm, first_beat_s)
    if not path.exists():
        features = extract_features(audio, bpm, first_beat_s, use_demucs=False)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=cache_dir, prefix=".features-", delete=False
            ) as stream:
                temp = Path(stream.name)
                pickle.dump(features, stream, protocol=pickle.HIGHEST_PROTOCOL)
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(path)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
    return key


def cached_features(cache_dir, key, audio, bpm, first_beat_s):
    extract_and_cache(cache_dir, (key, str(audio), bpm, first_beat_s))
    with feature_cache_path(cache_dir, audio, bpm, first_beat_s).open("rb") as stream:
        return pickle.load(stream)


def validate_package_checkout(repo):
    if not Path(auto_cue.__file__).resolve().is_relative_to(repo.resolve()):
        raise SystemExit(
            "Imported auto_cue package is outside --repo; use that checkout environment"
        )


def load_eval():
    validate_package_checkout(REPO)
    spec = importlib.util.spec_from_file_location("baseline_eval_kfold", REPO / "eval_kfold.py")
    e = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = e
    spec.loader.exec_module(e)
    e.CACHE_DIR = ROOT / "cache/features"
    e.PRED_PATH = ROOT / "predictions.jsonl"
    e.SUMMARY_PATH = ROOT / "summary.json"
    e.FOLD_PATH = ROOT / "docs/folds.json"
    e.REPORT_PATH = ROOT / "docs/results.md"
    e.POOL_DIR = POOL_DIR
    e.QA_DIR = QA_DIR
    e.LLM_WORKERS = 1
    e._extract_and_cache = partial(extract_and_cache, e.CACHE_DIR)
    e.cached_features = partial(cached_features, e.CACHE_DIR)
    install_controls(e)
    return e


def smoke(e):
    pool = e.load_gold_pool(e.POOL_DIR / "gold_pool_clean.csv", e.POOL_DIR / "audio_sel.csv")
    tracks = e.audio_pool_tracks(pool)
    assert len(tracks) == 289
    folds = e.assign_folds(tracks)
    # Prepare the same train-fold inputs needed by the full ranker, without API calls.
    specs = [(t.small_file, str(e.POOL_DIR / t.small_file), t.bpm, t.first_beat_s) for t in tracks]
    with ProcessPoolExecutor(max_workers=4, mp_context=e.mp.get_context("fork")) as executor:
        for count, _ in enumerate(executor.map(e._extract_and_cache, specs), 1):
            if count % 25 == 0 or count == len(specs):
                print(f"FEATURES {count}/{len(specs)}", flush=True)
    feature_map = {
        t.path: e.cached_features(t.small_file, e.POOL_DIR / t.small_file, t.bpm, t.first_beat_s)
        for t in tracks
    }
    feature_cache = {t.small_file: feature_map[t.path] for t in tracks}
    targets = folds[0][:2]
    done = e.load_done() | {("fold0", t.path) for t in folds[0][2:]}
    report = e.Report()
    e.run_split(
        "fold0",
        folds[0],
        [t for f in folds[1:] for t in f],
        pool,
        feature_map,
        feature_cache,
        report,
        done,
    )
    rows = [json.loads(line) for line in e.PRED_PATH.read_text().splitlines()]
    selected = [r for r in rows if r["split"] == "fold0" and r["id"] in {t.path for t in targets}]
    assert len(selected) == 2
    for row in selected:
        assert row["cost"] > 0 and len(row["examples"]) == 5
        assert {"llm4", "llm6"}.issubset(row)
        assert 0 <= row["llm4_conf"] <= 1 and 0 <= row["llm6_conf"] <= 1
    parsed = e.Report()
    for row in selected:
        e.record_methods(parsed, row["band"], row["gold4"], row["gold6"], row)
    assert all(parsed.by_method[m]["all"]["cue4"].total == 2 for m in e.METHODS)
    durable_json(
        ROOT / "smoke.json",
        dict(
            status="passed",
            targets=[t.path for t in targets],
            rows=selected,
            ledger=ledger(),
            full_test_fold_size=len(folds[0]),
        ),
    )
    print(
        "SMOKE PASSED: two durable predictions; five scoring methods; full 58-track fold excluded",
        flush=True,
    )


def _main():
    global ROOT, REPO, LIMIT, POOL_DIR, QA_DIR, run_fd
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["smoke", "full", "analyze"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--pool-dir", type=Path, default=POOL_DIR)
    parser.add_argument("--qa-dir", type=Path, default=QA_DIR)
    parser.add_argument("--budget", type=float, default=15.0)
    args = parser.parse_args()
    ROOT, REPO = args.output.resolve(), args.repo.resolve()
    validate_package_checkout(REPO)
    POOL_DIR, QA_DIR, LIMIT = args.pool_dir.resolve(), args.qa_dir.resolve(), args.budget
    if not 0 < LIMIT < float("inf"):
        parser.error("--budget must be finite and positive")
    for directory in (ROOT, ROOT / "responses", ROOT / "docs", ROOT / "cache/features"):
        directory.mkdir(parents=True, exist_ok=True)
    if args.phase == "analyze":
        from auto_cue.baseline_analysis import analyze

        analyze(ROOT, POOL_DIR, QA_DIR)
        return
    try:
        run_fd = os.open(ROOT / ".running", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise SystemExit(
            "Output directory is locked; verify no runner is active before removing .running"
        ) from None
    os.write(run_fd, str(os.getpid()).encode())
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is unset; no requests made")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    if subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, text=True
    ).strip():
        raise SystemExit("Commit tracked source changes before running")
    fingerprints = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [POOL_DIR / "gold_pool_clean.csv", POOL_DIR / "audio_sel.csv", QA_DIR / "gold.csv"]
    }
    manifest = ROOT / "manifest.json"
    audio = fingerprint_audio_roots(POOL_DIR, QA_DIR)
    check_resume_manifest(manifest, sha, fingerprints, audio)
    if not manifest.exists():
        durable_json(
            manifest,
            dict(
                sha=sha,
                started_at=time.time(),
                budget=LIMIT,
                model="gpt-6.1-terra",
                workers=1,
                repository=str(REPO),
                data_sha256=fingerprints,
                audio=audio,
            ),
        )
    e = load_eval()
    try:
        if args.phase == "smoke":
            smoke(e)
        else:
            if not (ROOT / "smoke.json").is_file():
                raise BaselineStop("Smoke test has not passed")
            e.main()
            rows = [json.loads(line) for line in e.PRED_PATH.read_text().splitlines()]
            assert len(rows) == 326 and len({(r["split"], r["id"]) for r in rows}) == 326
            durable_json(
                ROOT / "complete.json",
                dict(rows=len(rows), ledger=ledger(), completed_at=time.time()),
            )
            print("BASELINE COMPLETE", json.dumps(ledger()), flush=True)
    except BaselineStop as exc:
        print(f"BASELINE STOPPED: {exc}", flush=True)
        raise SystemExit(3)


def main():
    global run_fd
    try:
        _main()
    finally:
        if run_fd is not None:
            os.close(run_fd)
            run_fd = None
            (ROOT / ".running").unlink()


if __name__ == "__main__":
    main()
