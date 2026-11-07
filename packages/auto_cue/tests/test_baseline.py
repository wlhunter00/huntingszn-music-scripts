import hashlib
import json
from contextlib import nullcontext
from types import SimpleNamespace

import httpx
import pytest
from auto_cue import baseline
from auto_cue import baseline_analysis as analysis
from auto_cue.baseline_analysis import analyze, bucket, predictions

URL = "https://api.openai.com/v1/chat/completions"
BODY = {"model": "gpt-6.1-terra", "max_completion_tokens": 4096}
PAYLOAD = {"usage": {"prompt_tokens": 100, "completion_tokens": 10}, "choices": []}


@pytest.fixture
def guarded(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "ROOT", tmp_path)
    monkeypatch.setattr(baseline, "LIMIT", 15.0)
    (tmp_path / "responses").mkdir()
    calls = []
    replies = [httpx.Response(200, json=PAYLOAD)]

    def post(client, url, **kwargs):
        calls.append(kwargs["json"])
        response = replies.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(httpx.Client, "post", post)
    monkeypatch.setattr(baseline.time, "sleep", lambda _: None)
    evaluator = SimpleNamespace(
        predict_track=lambda *a, **k: None,
        append_pred=lambda row: None,
        write_report=lambda *a: None,
        PRED_PATH=tmp_path / "predictions.jsonl",
    )
    baseline.install_controls(evaluator)
    return calls, replies, evaluator


def test_budget_aborts_before_request(guarded, monkeypatch):
    calls, _, _ = guarded
    monkeypatch.setattr(baseline, "LIMIT", 0.001)
    with httpx.Client() as client, pytest.raises(baseline.BaselineStop, match="budget"):
        client.post(URL, json=BODY)
    assert not calls
    assert (baseline.ROOT / "STOP.json").exists()


@pytest.mark.parametrize("tail", [b'{"split":', b'{"id":"\xf0\x9f', b"{bad}\n"])
def test_repairs_only_malformed_final_prediction(tmp_path, tail):
    path = tmp_path / "predictions.jsonl"
    saved = b'{"split":"fold0","id":"completed"}\n'
    path.write_bytes(saved + tail)
    baseline.repair_prediction_tail(path)
    assert path.read_bytes() == saved
    with path.open("a") as stream:
        stream.write('{"split":"fold0","id":"next"}\n')
    assert [json.loads(line)["id"] for line in path.read_text().splitlines()] == [
        "completed",
        "next",
    ]


def test_malformed_earlier_prediction_fails_without_rewrite(tmp_path):
    path = tmp_path / "predictions.jsonl"
    data = b'{bad}\n{"split":"fold0","id":"completed"}\n'
    path.write_bytes(data)
    with pytest.raises(json.JSONDecodeError):
        baseline.repair_prediction_tail(path)
    assert path.read_bytes() == data


@pytest.mark.parametrize("data", [b"", b'{"id":"completed"}\n', b'{"id":"completed"}'])
def test_preserves_valid_prediction_tail(tmp_path, data):
    path = tmp_path / "predictions.jsonl"
    baseline.repair_prediction_tail(path)
    path.write_bytes(data)
    baseline.repair_prediction_tail(path)
    assert path.read_bytes() == data + (b"\n" if data and not data.endswith(b"\n") else b"")


def test_resume_reuses_durable_response_before_prediction_append(guarded):
    calls, _, evaluator = guarded
    with httpx.Client() as client:
        first = client.post(URL, json=BODY)
    assert not evaluator.PRED_PATH.exists()
    with httpx.Client() as restarted_client:
        resumed = restarted_client.post(URL, json=BODY)
    assert first.json() == resumed.json() == PAYLOAD
    assert len(calls) == 1
    assert baseline.ledger()["successful_requests"] == 1
    assert baseline.ledger()["actual_cost"] == pytest.approx(0.00015)


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("timeout"), httpx.Response(503)])
def test_transient_retry_retains_reservation(guarded, failure):
    calls, replies, _ = guarded
    replies.insert(0, failure)
    with httpx.Client() as client:
        assert client.post(URL, json=BODY).status_code == 200
    assert len(calls) == 2
    assert baseline.ledger()["uncertain_reserved"] > 0


@pytest.mark.parametrize("status", [401, 403])
def test_auth_stops_without_retry(guarded, status):
    calls, replies, _ = guarded
    replies[:] = [httpx.Response(status)]
    with httpx.Client() as client, pytest.raises(baseline.BaselineStop, match=f"HTTP {status}"):
        client.post(URL, json=BODY)
    assert len(calls) == 1


def test_pending_request_is_not_reissued(guarded):
    calls, _, _ = guarded
    key = hashlib.sha256(json.dumps(BODY, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    baseline.durable_json(
        baseline.ROOT / "responses" / f"{key}.json", dict(status="pending", reservation=0.05)
    )
    with httpx.Client() as client, pytest.raises(baseline.BaselineStop, match="uncertain"):
        client.post(URL, json=BODY)
    assert calls == []


def test_retry_limit_is_three_after_original(guarded):
    calls, replies, _ = guarded
    replies[:] = [httpx.Response(503) for _ in range(4)]
    with httpx.Client() as client, pytest.raises(baseline.BaselineStop, match="retry limit"):
        client.post(URL, json=BODY)
    assert len(calls) == 4
    assert baseline.ledger()["records"] == 4
    assert baseline.ledger()["uncertain_reserved"] > 0


def test_budget_includes_prior_spend_and_uncertain_attempts(guarded):
    calls, _, _ = guarded
    baseline.durable_json(
        baseline.ROOT / "responses" / "old.json", dict(status="success", cost=14.96)
    )
    baseline.durable_json(
        baseline.ROOT / "responses" / "uncertain.json", dict(status="pending", reservation=0.03)
    )
    with httpx.Client() as client, pytest.raises(baseline.BaselineStop, match="budget"):
        client.post(URL, json=BODY)
    assert calls == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (None, "no_prediction"),
        (0, "hit_±1"),
        (-1, "hit_±1"),
        (1, "hit_±1"),
        (1.01, "other_miss"),
        (14, "+16±2"),
        (18, "+16±2"),
        (-32, "-32±2"),
        (19, "other_miss"),
        (176, "+176±2"),
    ],
)
def test_analysis_buckets(error, expected):
    assert bucket(error) == expected


def test_analysis_requires_complete_unique_run(tmp_path):
    (tmp_path / "predictions.jsonl").write_text("")
    with pytest.raises(ValueError, match="326 unique"):
        analyze(tmp_path, tmp_path, tmp_path)


def test_combined_uses_predeclared_gate():
    row = dict(llm4=32, llm6=160)
    for mode in ("pct", "nopct"):
        row.update(
            {
                f"rank_{mode}4": 64,
                f"rank_{mode}4_p": 0.3,
                f"rank_{mode}6": 192,
                f"rank_{mode}6_p": 0.29,
            }
        )
    assert predictions(row)["combined_pct"] == (64, 160)


def test_rejects_different_checkout_before_loading_evaluator(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "REPO", tmp_path)
    with pytest.raises(SystemExit, match="outside --repo"):
        baseline.load_eval()


def test_accepts_package_inside_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(
        baseline.auto_cue, "__file__", str(tmp_path / "packages/auto_cue/__init__.py")
    )
    baseline.validate_package_checkout(tmp_path)


def test_checkout_validation_resolves_symlinks(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(checkout, target_is_directory=True)
    monkeypatch.setattr(baseline.auto_cue, "__file__", str(checkout / "__init__.py"))
    baseline.validate_package_checkout(alias)


def test_audio_manifest_rejects_same_size_content_changes(tmp_path):
    pool, qa = tmp_path / "pool", tmp_path / "qa"
    pool.mkdir()
    qa.mkdir()
    audio = pool / "track.mp3"
    audio.write_bytes(b"first")
    (qa / "qa.flac").write_bytes(b"qa")
    original = baseline.fingerprint_audio_roots(pool, qa)
    assert original["pool/track.mp3"]["size"] == 5
    assert original["pool/track.mp3"]["sha256"] == hashlib.sha256(b"first").hexdigest()
    assert len(original) == 2
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(dict(sha="revision", data_sha256={}, audio=original)))
    baseline.check_resume_manifest(manifest, "revision", {}, original)
    audio.write_bytes(b"other")
    changed = baseline.fingerprint_audio_roots(pool, qa)
    with pytest.raises(SystemExit, match="different audio"):
        baseline.check_resume_manifest(manifest, "revision", {}, changed)
    audio.unlink()
    with pytest.raises(SystemExit, match="different audio"):
        baseline.check_resume_manifest(
            manifest, "revision", {}, baseline.fingerprint_audio_roots(pool, qa)
        )


def test_content_addressed_features_do_not_reuse_stale_audio(tmp_path, monkeypatch):
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"first")
    cache = tmp_path / "cache"
    calls = []

    def extract(path, *args, **kwargs):
        calls.append(path.read_bytes())
        return {"audio": calls[-1]}

    monkeypatch.setattr(baseline, "extract_features", extract)
    assert baseline.cached_features(cache, "track.mp3", audio, 128, 0) == {"audio": b"first"}
    assert baseline.cached_features(cache, "track.mp3", audio, 128, 0) == {"audio": b"first"}
    renamed = tmp_path / "renamed.mp3"
    renamed.write_bytes(b"first")
    baseline.cached_features(cache, "renamed.mp3", renamed, 128, 0)
    assert len(calls) == 1
    audio.write_bytes(b"other")
    assert baseline.cached_features(cache, "track.mp3", audio, 128, 0) == {"audio": b"other"}
    assert len(calls) == 2
    assert len(list(cache.glob("*.pkl"))) == 2
    baseline.cached_features(cache, "track.mp3", audio, 130, 0)
    assert len(calls) == 3


@pytest.mark.parametrize(("cue4", "cue6"), [(None, None), (None, 64), (32, None), (32, 64)])
def test_smoke_accepts_saved_parsed_abstentions(tmp_path, monkeypatch, cue4, cue6):
    monkeypatch.setattr(baseline, "ROOT", tmp_path)
    tracks = [
        SimpleNamespace(path=str(i), small_file=str(i), bpm=128, first_beat_s=0) for i in range(289)
    ]
    folds = [tracks[i::5] for i in range(5)]
    executor = SimpleNamespace(map=lambda fn, specs: [None] * len(specs))
    monkeypatch.setattr(baseline, "ProcessPoolExecutor", lambda **kw: nullcontext(executor))
    rows = [
        dict(
            split="fold0",
            id=t.path,
            cost=0.01,
            examples=["example"] * 5,
            llm4=cue4,
            llm6=cue6,
            llm4_conf=0,
            llm6_conf=0,
            band="house (115+)",
            gold4=32,
            gold6=64,
        )
        for t in folds[0][:2]
    ]
    path = tmp_path / "predictions.jsonl"

    def run_split(*args):
        path.write_text("\n".join(json.dumps(r) for r in rows))

    def record(report, *args):
        report.by_method["llm"]["all"]["cue4"].total += 1

    evaluator = SimpleNamespace(
        POOL_DIR=tmp_path,
        PRED_PATH=path,
        load_gold_pool=lambda *a: None,
        audio_pool_tracks=lambda _: tracks,
        assign_folds=lambda _: folds,
        mp=SimpleNamespace(get_context=lambda _: None),
        _extract_and_cache=lambda *a: None,
        cached_features=lambda *a: None,
        load_done=lambda: set(),
        run_split=run_split,
        Report=lambda: SimpleNamespace(
            by_method={"llm": {"all": {"cue4": SimpleNamespace(total=0)}}}
        ),
        METHODS=["llm"],
        record_methods=record,
    )
    baseline.smoke(evaluator)
    saved = json.loads((tmp_path / "smoke.json").read_text())
    assert saved["status"] == "passed"
    assert saved["rows"] == rows


def test_offline_analysis_full_run(tmp_path, monkeypatch):
    tracks = {}
    rows = []
    for i in range(326):
        name = str(i)
        tracks[name] = SimpleNamespace(
            path=name, name=name, artist="", title=name, bpm=128, duration_s=200, source_path=name
        )
        row = dict(
            split="fold0" if i < 289 else "qa",
            id=name if i < 289 else "qa:" + name,
            band="house (115+)",
            gold4=32,
            gold6=160,
            llm4=32,
            llm6=176,
            examples=[str(j) for j in range(5)],
        )
        for mode in ("pct", "nopct"):
            row.update(
                {
                    f"rank_{mode}4": 32,
                    f"rank_{mode}4_p": 0.5,
                    f"rank_{mode}6": 176,
                    f"rank_{mode}6_p": 0.5,
                }
            )
        rows.append(row)
    pool = SimpleNamespace(tracks=tracks, paths_to_exclude=lambda **kw: {"forbidden"})
    monkeypatch.setattr(analysis, "load_gold_pool", lambda *a: pool)
    monkeypatch.setattr(analysis, "load_gold_csv", lambda *a: tracks)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/folds.json").write_text(json.dumps({"folds": [[]]}))
    (tmp_path / "predictions.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    methods = predictions(rows[0])
    summary = {
        split: {
            method: {
                band: {
                    "cue4": {"correct": count, "accuracy": 100, "total": count},
                    "cue6": {"correct": 0, "accuracy": 0, "total": count},
                }
                for band in ("all", "bass (<80)", "dnb (80-100)", "house (115+)")
            }
            for method in methods
        }
        for split, count in [("pool", 289), ("qa", 37)]
    }
    (tmp_path / "summary.json").write_text(json.dumps(summary))
    (tmp_path / "ledger.json").write_text("{}")
    analyze(tmp_path, tmp_path, tmp_path)
    result = json.loads((tmp_path / "analysis.json").read_text())
    assert result["error_distributions"]["pool"]["llm"]["cue6"] == {"+16±2": 289}
    assert result["leakage_audit"]["examples_checked"] == 1630
    pool.paths_to_exclude = lambda **kw: {"0"}
    with pytest.raises(AssertionError):
        analyze(tmp_path, tmp_path, tmp_path)
