"""Summarize saved baseline predictions without making any API calls."""

import collections
import csv
import json
from pathlib import Path

from auto_cue.gold import load_gold_csv, load_gold_pool


def predictions(row):
    result = {"llm": (row["llm4"], row["llm6"])}
    for mode in ("pct", "nopct"):
        result["ranker_" + mode] = tuple(row[f"rank_{mode}{i}"] for i in (4, 6))
        result["combined_" + mode] = tuple(
            row[f"rank_{mode}{i}"]
            if row[f"rank_{mode}{i}"] is not None and row[f"rank_{mode}{i}_p"] >= 0.3
            else row[f"llm{i}"]
            for i in (4, 6)
        )
    result.update({
        method: tuple(picks) for method, picks in row.get("build32_predictions", {}).items()
    })
    return result


def bucket(error):
    if error is None:
        return "no_prediction"
    if abs(error) <= 1:
        return "hit_±1"
    multiple = round(error / 16) * 16
    if multiple and abs(error - multiple) <= 2:
        return f"{multiple:+d}±2"
    return "other_miss"


def analyze(ROOT, pool_dir, qa_dir):
    rows = [json.loads(line) for line in (ROOT / "predictions.jsonl").read_text().splitlines()]
    if len(rows) != 326 or len({(r["split"], r["id"]) for r in rows}) != 326:
        raise ValueError("Expected 326 unique completed predictions")
    summary = json.loads((ROOT / "summary.json").read_text())
    pool = load_gold_pool(pool_dir / "gold_pool_clean.csv", pool_dir / "audio_sel.csv")
    qa = load_gold_csv(qa_dir / "gold.csv")
    folds = json.loads((ROOT / "docs/folds.json").read_text())["folds"]
    by_small = {t.name: t for t in pool.tracks.values()}
    for row in rows:
        if row["split"].startswith("fold"):
            track = pool.tracks[row["id"]]
            held_out = set(folds[int(row["split"].removeprefix("fold"))])
            banned = pool.paths_to_exclude(
                self_path=track.path,
                artist=track.artist,
                title=track.title,
                bpm=track.bpm,
                duration_s=track.duration_s,
                extra_paths=held_out,
            )
        else:
            track = qa[row["id"].removeprefix("qa:")]
            banned = pool.paths_to_exclude(
                title=Path(track.source_path).stem,
                source_path=track.source_path,
                bpm=track.bpm,
                duration_s=track.duration_s,
            )
        assert len(row["examples"]) == 5
        assert not any(by_small[name].path in banned for name in row["examples"])

    distributions = {}
    per_track = []
    for row in rows:
        split = "pool" if row["split"].startswith("fold") else "qa"
        for method, predicted in predictions(row).items():
            for cue, pred in zip((4, 6), predicted):
                gold = row[f"gold{cue}"]
                error = None if pred is None else pred - gold
                distributions.setdefault(split, {}).setdefault(method, {}).setdefault(
                    f"cue{cue}", collections.Counter()
                )[bucket(error)] += 1
                per_track.append(
                    dict(
                        split=split,
                        fold=row["split"],
                        path=row["id"],
                        band=row["band"],
                        method=method,
                        cue=cue,
                        gold=gold,
                        predicted=pred,
                        signed_error_beats=error,
                        hit=pred is not None and abs(error) <= 1,
                        error_bucket=bucket(error),
                    )
                )

    for split in ("pool", "qa"):
        count = sum(
            (r["split"].startswith("fold") if split == "pool" else r["split"] == "qa") for r in rows
        )
        for method in summary[split]:
            for cue in ("cue4", "cue6"):
                assert sum(distributions[split][method][cue].values()) == count
                assert (
                    distributions[split][method][cue]["hit_±1"]
                    == summary[split][method]["all"][cue]["correct"]
                )

    historical = {
        "pool": {
            "all": (67.8, 59.5),
            "bass (<80)": (52, 44),
            "dnb (80-100)": (60, 47),
            "house (115+)": (70, 62),
        },
        "qa": {"all": (67.6, 48.6)},
    }
    comparison = {}
    for split, bands in historical.items():
        comparison[split] = {}
        for band, old in bands.items():
            current = tuple(summary[split]["llm"][band][f"cue{c}"]["accuracy"] for c in (4, 6))
            comparison[split][band] = dict(
                historical=old,
                current=current,
                delta_percentage_points=[round(a - b, 1) for a, b in zip(current, old)],
            )

    output = dict(
        total_rows=len(rows),
        historical_comparison=comparison,
        error_distributions=distributions,
        cost=json.loads((ROOT / "ledger.json").read_text()),
        leakage_audit=dict(
            tracks_checked=len(rows),
            examples_checked=sum(len(r["examples"]) for r in rows),
            violations=0,
        ),
    )
    (ROOT / "analysis.json").write_text(json.dumps(output, indent=2))
    with (ROOT / "per-track-errors.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(per_track[0]))
        writer.writeheader()
        writer.writerows(per_track)
    print("TOTAL", len(rows))
    print("COST", json.dumps(output["cost"]))
    for split in ("pool", "qa"):
        print("\n" + split.upper())
        for method, bands in summary[split].items():
            print(
                method,
                "; ".join(
                    f"{band}: c4={cues['cue4']['accuracy']}% "
                    f"({cues['cue4']['correct']}/{cues['cue4']['total']}) "
                    f"c6={cues['cue6']['accuracy']}% "
                    f"({cues['cue6']['correct']}/{cues['cue6']['total']})"
                    for band, cues in bands.items()
                ),
            )
        print("LLM errors", json.dumps(distributions[split]["llm"], sort_keys=True))
    print("HISTORICAL", json.dumps(comparison))
