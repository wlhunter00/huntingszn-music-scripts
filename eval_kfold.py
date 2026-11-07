#!/usr/bin/env python3
"""Leak-free 5-fold gold-pool eval plus the QA set.

Few-shot examples and the GBM are fit only on the train fold. The track
itself, the rest of its test fold, and same-title copies are excluded.
`track_pct` is reported both on and off. LLM confidence threshold is the
package default 0.5. Ranker probability threshold is the predeclared 0.3
gate. Neither threshold is fit on the test fold.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import pickle
import random
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier

if not os.environ.get("OPENAI_API_KEY"):
    print("ERROR: OPENAI_API_KEY not set")
    sys.exit(1)

from auto_cue.features import FEATURE_CACHE_VERSION, extract_features
from auto_cue.gold import GoldPool, PoolTrack, get_pool_fewshot_examples, load_gold_csv, load_gold_pool
from auto_cue.llm import predict_cues_llm
from auto_cue.ranker import candidate_vector

POOL_DIR = Path("/workspace/gold-pool")
QA_DIR = Path("/workspace/qa-all")
CACHE_DIR = Path("/workspace/.cache/kfold_features")
PRED_PATH = Path("/workspace/kfold_predictions.jsonl")
SUMMARY_PATH = Path("/workspace/kfold_summary.json")
FOLD_PATH = Path("/workspace/docs/auto-cue-kfold-folds.json")
REPORT_PATH = Path("/workspace/docs/auto-cue-kfold-results.md")

N_FOLDS = 5
SEED = 42
MODEL = "gpt-6.1-terra"
REASONING = "medium"
LLM_THRESHOLD = 0.5
RANKER_THRESHOLD = 0.3
LLM_WORKERS = 4
BANDS = ["bass (<80)", "dnb (80-100)", "midtempo (100-115)", "house (115+)"]
METHODS = ["llm", "ranker_pct", "ranker_nopct", "combined_pct", "combined_nopct"]


@dataclass
class CueStats:
    correct: int = 0
    total: int = 0
    err16: int = 0
    err32: int = 0
    emitted: int = 0
    emitted_hit: int = 0

    def add(self, gold: float | None, pred: int | None, conf: float, threshold: float) -> None:
        if gold is None:
            return
        self.total += 1
        err = abs(pred - gold) if pred is not None else float("inf")
        if err <= 1.0:
            self.correct += 1
        elif 14 <= err <= 18:
            self.err16 += 1
        elif 30 <= err <= 34:
            self.err32 += 1
        if pred is not None and conf >= threshold:
            self.emitted += 1
            if err <= 1.0:
                self.emitted_hit += 1

    @property
    def accuracy(self) -> float:
        return 100.0 * self.correct / self.total if self.total else 0.0

    @property
    def precision(self) -> float:
        return 100.0 * self.emitted_hit / self.emitted if self.emitted else 0.0

    @property
    def coverage(self) -> float:
        return 100.0 * self.emitted / self.total if self.total else 0.0


@dataclass
class Report:
    by_method: dict[str, dict[str, dict[str, CueStats]]] = field(default_factory=dict)

    def add(self, method: str, band: str, cue: str, gold, pred, conf: float, threshold: float) -> None:
        self.by_method.setdefault(method, {})
        for key in (band, "all"):
            self.by_method[method].setdefault(key, {})
            self.by_method[method][key].setdefault(cue, CueStats())
            self.by_method[method][key][cue].add(gold, pred, conf, threshold)


def load_done() -> set[tuple[str, str]]:
    done: set[tuple[str, str]] = set()
    if not PRED_PATH.exists():
        return done
    with PRED_PATH.open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            done.add((row["split"], row["id"]))
    return done


def audio_pool_tracks(pool: GoldPool) -> list[PoolTrack]:
    tracks = []
    for track in pool.tracks.values():
        if not track.small_file:
            continue
        audio = POOL_DIR / track.small_file
        if audio.exists():
            tracks.append(track)
    return tracks


def assign_folds(tracks: list[PoolTrack]) -> list[list[PoolTrack]]:
    ordered = list(tracks)
    random.Random(SEED).shuffle(ordered)
    folds: list[list[PoolTrack]] = [[] for _ in range(N_FOLDS)]
    for i, track in enumerate(ordered):
        folds[i % N_FOLDS].append(track)
    return folds


def _extract_and_cache(spec: tuple[str, str, float, float]) -> str:
    key, audio, bpm, first_beat_s = spec
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{FEATURE_CACHE_VERSION}-{key}.pkl"
    if cache_path.exists():
        return key
    features = extract_features(Path(audio), bpm, first_beat_s, use_demucs=False)
    with cache_path.open("wb") as handle:
        pickle.dump(features, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return key


def cached_features(key: str, audio: Path, bpm: float, first_beat_s: float):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{FEATURE_CACHE_VERSION}-{key}.pkl"
    if not cache_path.exists():
        _extract_and_cache((key, str(audio), bpm, first_beat_s))
    with cache_path.open("rb") as handle:
        return pickle.load(handle)


def rows_for_tracks(tracks: list[PoolTrack], feature_map: dict, include_pct: bool, cue: str):
    xs: list[np.ndarray] = []
    ys: list[int] = []
    slot = 3 if cue == "cue4" else 5
    for track in tracks:
        features = feature_map.get(track.path)
        if features is None:
            continue
        gold = track.cues.get(slot)
        beats = list(features.drop_candidates)
        if cue == "cue6":
            half = features.total_beats // 2
            later = [b for b in beats if b >= half]
            if later:
                beats = later
        for beat in beats:
            vector = candidate_vector(features, beat, include_track_pct=include_pct)
            if vector is None:
                continue
            label = int(gold is not None and abs(beat - gold) <= 1.0)
            xs.append(vector)
            ys.append(label)
    if not xs:
        return None, None
    return np.vstack(xs), np.array(ys)


def fit_gbm(tracks: list[PoolTrack], feature_map: dict, include_pct: bool, cue: str):
    xs, ys = rows_for_tracks(tracks, feature_map, include_pct, cue)
    if xs is None or len(set(ys.tolist())) < 2:
        return None
    model = GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=SEED)
    model.fit(xs, ys)
    return model


def rank_one(model, features, cue: str, include_pct: bool) -> tuple[int | None, float]:
    if model is None:
        return None, 0.0
    beats = list(features.drop_candidates)
    if cue == "cue6":
        half = features.total_beats // 2
        later = [b for b in beats if b >= half]
        if later:
            beats = later
    vectors = []
    kept = []
    for beat in beats:
        vector = candidate_vector(features, beat, include_track_pct=include_pct)
        if vector is None:
            continue
        vectors.append(vector)
        kept.append(beat)
    if not vectors:
        return None, 0.0
    probs = model.predict_proba(np.vstack(vectors))[:, 1]
    index = int(np.argmax(probs))
    return kept[index], float(probs[index])


def assert_no_leak(examples, banned_paths: set[str], small_to_path: dict[str, str], self_small: str) -> None:
    self_name = self_small.replace(".mp3", "")
    for example in examples:
        if example.name == self_name:
            raise RuntimeError(f"few-shot returned self: {self_small}")
        path = small_to_path.get(example.name + ".mp3")
        if path in banned_paths:
            raise RuntimeError(f"few-shot returned banned path {path}")


def predict_track(track: PoolTrack, features, pool: GoldPool, feature_cache: dict, banned: set[str], models: dict):
    examples = get_pool_fewshot_examples(
        pool,
        track.bpm,
        features.total_beats,
        POOL_DIR,
        max_examples=5,
        features_cache=feature_cache,
        exclude_paths=banned,
    )
    small_to_path = {
        t.small_file: t.path for t in pool.tracks.values() if t.small_file
    }
    assert_no_leak(examples, banned, small_to_path, track.small_file or "")
    llm = predict_cues_llm(
        features,
        model=MODEL,
        reasoning_effort=REASONING,
        genre_bucket=track.bpm_band,
        examples=examples,
    )
    out = {
        "llm4": llm.cue4_beat,
        "llm4_conf": llm.cue4.confidence,
        "llm6": llm.cue6_beat,
        "llm6_conf": llm.cue6.confidence,
        "cost": llm.cost_usd,
        "examples": [ex.name for ex in examples],
    }
    for pct_name, include_pct in (("pct", True), ("nopct", False)):
        for cue in ("cue4", "cue6"):
            pred, prob = rank_one(models[f"{cue}_{pct_name}"], features, cue, include_pct)
            key = "4" if cue == "cue4" else "6"
            out[f"rank_{pct_name}{key}"] = pred
            out[f"rank_{pct_name}{key}_p"] = prob
    return out


def choose(rank_pred, rank_p, llm_pred):
    if rank_pred is not None and rank_p >= RANKER_THRESHOLD:
        return rank_pred, rank_p, RANKER_THRESHOLD
    conf = 0.0
    return llm_pred, conf, LLM_THRESHOLD


def record_methods(report: Report, band: str, gold4, gold6, pred: dict) -> None:
    specs = {
        "llm": (pred["llm4"], pred["llm4_conf"], LLM_THRESHOLD, pred["llm6"], pred["llm6_conf"], LLM_THRESHOLD),
        "ranker_pct": (pred["rank_pct4"], pred["rank_pct4_p"], RANKER_THRESHOLD, pred["rank_pct6"], pred["rank_pct6_p"], RANKER_THRESHOLD),
        "ranker_nopct": (pred["rank_nopct4"], pred["rank_nopct4_p"], RANKER_THRESHOLD, pred["rank_nopct6"], pred["rank_nopct6_p"], RANKER_THRESHOLD),
    }
    c4, c4p, c4t = choose(pred["rank_pct4"], pred["rank_pct4_p"], pred["llm4"])
    # Combined uses the confidence of whichever source it kept.
    if pred["rank_pct4"] is not None and pred["rank_pct4_p"] >= RANKER_THRESHOLD:
        c4_conf, c4_thr = pred["rank_pct4_p"], RANKER_THRESHOLD
    else:
        c4, c4_conf, c4_thr = pred["llm4"], pred["llm4_conf"], LLM_THRESHOLD
    if pred["rank_pct6"] is not None and pred["rank_pct6_p"] >= RANKER_THRESHOLD:
        c6, c6_conf, c6_thr = pred["rank_pct6"], pred["rank_pct6_p"], RANKER_THRESHOLD
    else:
        c6, c6_conf, c6_thr = pred["llm6"], pred["llm6_conf"], LLM_THRESHOLD
    n4, n4_conf, n4_thr = (
        (pred["rank_nopct4"], pred["rank_nopct4_p"], RANKER_THRESHOLD)
        if pred["rank_nopct4"] is not None and pred["rank_nopct4_p"] >= RANKER_THRESHOLD
        else (pred["llm4"], pred["llm4_conf"], LLM_THRESHOLD)
    )
    n6, n6_conf, n6_thr = (
        (pred["rank_nopct6"], pred["rank_nopct6_p"], RANKER_THRESHOLD)
        if pred["rank_nopct6"] is not None and pred["rank_nopct6_p"] >= RANKER_THRESHOLD
        else (pred["llm6"], pred["llm6_conf"], LLM_THRESHOLD)
    )
    specs["combined_pct"] = (c4, c4_conf, c4_thr, c6, c6_conf, c6_thr)
    specs["combined_nopct"] = (n4, n4_conf, n4_thr, n6, n6_conf, n6_thr)
    # silence unused
    _ = (c4p, c4t)
    for method, (p4, conf4, thr4, p6, conf6, thr6) in specs.items():
        report.add(method, band, "cue4", gold4, p4, conf4, thr4)
        report.add(method, band, "cue6", gold6, p6, conf6, thr6)


def train_fold_models(train_tracks, feature_map):
    models = {}
    for cue in ("cue4", "cue6"):
        for pct_name, include_pct in (("pct", True), ("nopct", False)):
            models[f"{cue}_{pct_name}"] = fit_gbm(train_tracks, feature_map, include_pct, cue)
    return models


def append_pred(row: dict) -> None:
    with PRED_PATH.open("a") as handle:
        handle.write(json.dumps(row) + "\n")


def run_split(split_name: str, test_tracks: list[PoolTrack], train_tracks: list[PoolTrack], pool, feature_map, feature_cache, report: Report, done: set) -> float:
    test_paths = {t.path for t in test_tracks}
    banned_train = set()
    for track in test_tracks:
        banned_train |= pool.paths_to_exclude(
            self_path=track.path,
            artist=track.artist,
            title=track.title,
            bpm=track.bpm,
            duration_s=track.duration_s,
        )
    allowed_train = [t for t in train_tracks if t.path not in banned_train and t.path not in test_paths]
    print(f"\n{split_name}: test={len(test_tracks)} train_allowed={len(allowed_train)} banned_from_train={len(banned_train & {t.path for t in train_tracks})}")
    models = train_fold_models(allowed_train, feature_map)

    pending = []
    for track in test_tracks:
        if (split_name, track.path) in done:
            continue
        features = feature_map.get(track.path)
        if features is None:
            print(f"  skip {track.small_file}: no features")
            continue
        banned = pool.paths_to_exclude(
            self_path=track.path,
            artist=track.artist,
            title=track.title,
            bpm=track.bpm,
            duration_s=track.duration_s,
            extra_paths=test_paths,
        )
        pending.append((track, features, banned))

    cost = 0.0

    def job(item):
        track, features, banned = item
        pred = predict_track(track, features, pool, feature_cache, banned, models)
        return track, pred

    with ThreadPoolExecutor(max_workers=LLM_WORKERS) as executor:
        futures = [executor.submit(job, item) for item in pending]
        for future in as_completed(futures):
            try:
                track, pred = future.result()
            except Exception as exc:
                print(f"  ERROR {exc}")
                traceback.print_exc()
                continue
            row = {
                "split": split_name,
                "id": track.path,
                "band": track.bpm_band,
                "bpm": track.bpm,
                "gold4": track.cues.get(3),
                "gold6": track.cues.get(5),
                **pred,
            }
            append_pred(row)
            done.add((split_name, track.path))
            record_methods(report, track.bpm_band, row["gold4"], row["gold6"], pred)
            cost += pred["cost"]
            print(
                f"  {track.small_file} {track.bpm_band} "
                f"llm {pred['llm4']}/{pred['llm6']} "
                f"rank {pred['rank_pct4']}/{pred['rank_pct6']} "
                f"cost={cost:.2f}"
            )
    return cost


def replay(report: Report, split_prefix: str) -> None:
    if not PRED_PATH.exists():
        return
    with PRED_PATH.open() as handle:
        for line in handle:
            row = json.loads(line)
            if not row["split"].startswith(split_prefix) and split_prefix not in row["split"]:
                if split_prefix == "fold" and row["split"].startswith("fold"):
                    pass
                elif split_prefix == "qa" and row["split"] == "qa":
                    pass
                else:
                    continue
            if split_prefix == "fold" and not row["split"].startswith("fold"):
                continue
            if split_prefix == "qa" and row["split"] != "qa":
                continue
            record_methods(report, row["band"], row["gold4"], row["gold6"], row)


def stats_dict(stats: CueStats) -> dict:
    return {
        "accuracy": round(stats.accuracy, 1),
        "correct": stats.correct,
        "total": stats.total,
        "err16": stats.err16,
        "err32": stats.err32,
        "precision": round(stats.precision, 1),
        "coverage": round(stats.coverage, 1),
        "emitted": stats.emitted,
        "emitted_hit": stats.emitted_hit,
    }


def write_report(pool_report: Report, qa_report: Report, cost: float) -> None:
    def section(title: str, report: Report) -> list[str]:
        lines = [f"## {title}", ""]
        lines.append("Raw accuracy is exact within 1 beat. Precision is among predictions whose score clears the predeclared threshold (LLM 0.5, ranker 0.3). Coverage is the share of gold cues that cleared that threshold. Thresholds were not fit on these folds.")
        lines.append("")
        lines.append("| Method | Band | Cue4 acc | Cue4 prec (cov) | Cue6 acc | Cue6 prec (cov) | ±16 c4/c6 |")
        lines.append("|--------|------|----------|-----------------|----------|-----------------|-----------|")
        for method in METHODS:
            bands = report.by_method.get(method, {})
            for band in ["all", *BANDS]:
                if band not in bands:
                    continue
                c4 = bands[band].get("cue4", CueStats())
                c6 = bands[band].get("cue6", CueStats())
                lines.append(
                    f"| {method} | {band} | {c4.accuracy:.1f}% ({c4.correct}/{c4.total}) | "
                    f"{c4.precision:.1f}% ({c4.coverage:.0f}%) | {c6.accuracy:.1f}% ({c6.correct}/{c6.total}) | "
                    f"{c6.precision:.1f}% ({c6.coverage:.0f}%) | {c4.err16}/{c6.err16} |"
                )
        lines.append("")
        return lines

    body = [
        "# Leak-free k-fold results",
        "",
        f"5-fold gold pool, seed {SEED}. Few-shot and the GBM see only the train fold, with the scored track, its test-fold mates, and same-title copies removed. `ranker_nopct` / `combined_nopct` zero out `track_pct`.",
        "",
        f"API cost recorded this run: ${cost:.2f}. Resumed rows are not re-billed in that figure.",
        "",
        *section("Gold pool, pooled across folds", pool_report),
        *section("QA eval (37 tracks), few-shot from the pool with same-title copies removed", qa_report),
    ]
    REPORT_PATH.write_text("\n".join(body) + "\n")

    payload = {"cost_this_run": cost, "pool": {}, "qa": {}}
    for name, report in (("pool", pool_report), ("qa", qa_report)):
        for method, bands in report.by_method.items():
            payload[name].setdefault(method, {})
            for band, cues in bands.items():
                payload[name][method][band] = {cue: stats_dict(stats) for cue, stats in cues.items()}
    SUMMARY_PATH.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {REPORT_PATH}")
    print(f"Wrote {SUMMARY_PATH}")


def main() -> None:
    pool = load_gold_pool(POOL_DIR / "gold_pool_clean.csv", POOL_DIR / "audio_sel.csv")
    tracks = audio_pool_tracks(pool)
    folds = assign_folds(tracks)
    FOLD_PATH.write_text(json.dumps({
        "seed": SEED,
        "n_folds": N_FOLDS,
        "folds": [[t.path for t in fold] for fold in folds],
    }, indent=2))
    print(f"Pool tracks with audio: {len(tracks)}")
    for i, fold in enumerate(folds):
        print(f"  fold {i}: {len(fold)}")

    feature_map: dict = {}
    feature_cache: dict = {}
    print("Extracting pool features...")
    specs = [
        (track.small_file, str(POOL_DIR / track.small_file), track.bpm, track.first_beat_s)
        for track in tracks
    ]
    with ProcessPoolExecutor(max_workers=4, mp_context=mp.get_context("fork")) as executor:
        finished = 0
        for _key in executor.map(_extract_and_cache, specs):
            finished += 1
            if finished % 25 == 0 or finished == len(specs):
                print(f"  extracted {finished}/{len(specs)}")
    for track in tracks:
        features = cached_features(track.small_file, POOL_DIR / track.small_file, track.bpm, track.first_beat_s)
        feature_map[track.path] = features
        feature_cache[track.small_file] = features

    done = load_done()
    pool_report = Report()
    replay(pool_report, "fold")
    cost = 0.0
    for i, fold in enumerate(folds):
        train = [t for j, other in enumerate(folds) if j != i for t in other]
        cost += run_split(f"fold{i}", fold, train, pool, feature_map, feature_cache, pool_report, done)
        write_report(pool_report, Report(), cost)

    qa = load_gold_csv(QA_DIR / "gold.csv")
    print(f"\nQA tracks: {len(qa)}")
    qa_as_pool: list[PoolTrack] = []
    qa_feature_map = {}
    for filename, gold in qa.items():
        audio = QA_DIR / filename
        if not audio.exists():
            continue
        features = cached_features(filename, audio, gold.bpm, gold.first_beat_s)
        title = Path(gold.source_path).stem if gold.source_path else filename
        pseudo = PoolTrack(
            path=f"qa:{filename}",
            small_file=filename,
            bpm=gold.bpm,
            first_beat_s=gold.first_beat_s,
            total_beats=features.total_beats,
            duration_s=gold.duration_s,
            cues=gold.cues,
            artist="",
            title=title,
        )
        qa_as_pool.append(pseudo)
        qa_feature_map[pseudo.path] = features
        feature_cache[filename] = features

    qa_report = Report()
    replay(qa_report, "qa")
    # Ranker trains on the full pool except songs that match a QA track.
    banned_qa = set()
    for track in qa_as_pool:
        banned_qa |= pool.paths_to_exclude(
            artist=track.artist,
            title=track.title,
            source_path=track.title and "" or "",
            bpm=track.bpm,
            duration_s=track.duration_s,
        )
        banned_qa |= pool.paths_to_exclude(
            title=track.title,
            source_path=next((g.source_path for g in qa.values() if f"qa:{g.filename}" == track.path), ""),
            bpm=track.bpm,
            duration_s=track.duration_s,
        )
    print(f"Pool paths excluded from QA ranker training: {len(banned_qa)}")
    qa_train = [t for t in tracks if t.path not in banned_qa]
    # Test tracks are not in the pool, so train is qa_train and the exclusion
    # set for few-shot is computed per track inside run_split via extra test paths.
    # Passing the QA pseudos as the test fold would ban every QA title from
    # every other QA track's few-shot only if those titles exist in the pool.
    # run_split bans test_paths (qa: filenames) which are not pool paths, plus
    # per-track identity. Train exclusion unions identity of every QA track,
    # which is what we want for the ranker. Few-shot inside predict_track uses
    # per-track banned | test_paths. test_paths are qa: ids, not pool paths,
    # so few-shot still sees the whole pool except that track's copies.
    # Override: call predict with extra_paths only for identity, not every QA song.
    # run_split ORs the whole test fold into few-shot exclusion. Those paths are
    # not in the pool, so retrieval is unchanged. Good.
    cost += run_split("qa", qa_as_pool, qa_train, pool, {**feature_map, **qa_feature_map}, feature_cache, qa_report, done)

    write_report(pool_report, qa_report, cost)


if __name__ == "__main__":
    main()
