"""Offline evaluation harness for auto-cue.

Tests cue predictions against gold labels from cues.csv.
Measures:
- Per-cue accuracy (exact within ±1 beat)
- Cue4 and cue6 accuracy (spec: >= 85%)
- Abstain rate (spec: <= 35%)
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import pytest


@dataclass
class GoldCues:
    """Gold cue positions for a track."""
    path: str
    bpm: float
    cues: dict[int, float]  # slot (0-7) -> beat position


@dataclass
class EvalResult:
    """Evaluation result for a single track."""
    path: str
    predicted: dict[int, int]
    gold: dict[int, float]
    errors: dict[int, float]  # slot -> error in beats
    abstained: bool = False


@dataclass
class EvalMetrics:
    """Aggregate evaluation metrics."""
    total: int = 0
    processed: int = 0
    abstained: int = 0
    
    cue4_correct: int = 0
    cue4_total: int = 0
    cue6_correct: int = 0
    cue6_total: int = 0
    
    per_cue_correct: dict[int, int] = field(default_factory=dict)
    per_cue_total: dict[int, int] = field(default_factory=dict)
    
    all_8_correct: int = 0
    
    @property
    def abstain_rate(self) -> float:
        return self.abstained / self.total if self.total > 0 else 0.0
    
    @property
    def cue4_accuracy(self) -> float:
        return self.cue4_correct / self.cue4_total if self.cue4_total > 0 else 0.0
    
    @property
    def cue6_accuracy(self) -> float:
        return self.cue6_correct / self.cue6_total if self.cue6_total > 0 else 0.0
    
    @property
    def mean_per_cue_accuracy(self) -> float:
        if not self.per_cue_total:
            return 0.0
        accuracies = []
        for slot in range(8):
            total = self.per_cue_total.get(slot, 0)
            if total > 0:
                accuracies.append(self.per_cue_correct.get(slot, 0) / total)
        return sum(accuracies) / len(accuracies) if accuracies else 0.0


def load_gold_cues(csv_path: Path) -> dict[str, GoldCues]:
    """Load gold cues from cues.csv."""
    gold = {}
    
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            path = row.get("path", "")
            if not path:
                continue
            
            if "Energy" in row.get("name", ""):
                continue
            
            if row.get("kind") != "CUE":
                continue
            
            if path not in gold:
                try:
                    bpm = float(row.get("bpm") or 0)
                except ValueError:
                    bpm = 0.0
                gold[path] = GoldCues(
                    path=path,
                    bpm=bpm,
                    cues={},
                )
            
            try:
                index = int(row["index"])
                beat = float(row["beat"])
                gold[path].cues[index] = beat
            except (ValueError, KeyError):
                pass
    
    return {p: g for p, g in gold.items() if len(g.cues) >= 4}


def evaluate_prediction(
    predicted: dict[int, int],
    gold: GoldCues,
    tolerance: float = 1.0,
) -> EvalResult:
    """Evaluate a single prediction against gold."""
    errors = {}
    
    for slot, pred_beat in predicted.items():
        if slot in gold.cues:
            error = abs(pred_beat - gold.cues[slot])
            errors[slot] = error
    
    return EvalResult(
        path=gold.path,
        predicted=predicted,
        gold=gold.cues,
        errors=errors,
    )


def compute_metrics(
    results: list[EvalResult],
    tolerance: float = 1.0,
) -> EvalMetrics:
    """Compute aggregate metrics from evaluation results."""
    metrics = EvalMetrics()
    metrics.total = len(results)
    
    for result in results:
        if result.abstained:
            metrics.abstained += 1
            continue
        
        metrics.processed += 1
        
        if 3 in result.errors:
            metrics.cue4_total += 1
            if result.errors[3] <= tolerance:
                metrics.cue4_correct += 1
        
        if 5 in result.errors:
            metrics.cue6_total += 1
            if result.errors[5] <= tolerance:
                metrics.cue6_correct += 1
        
        all_correct = True
        for slot in range(8):
            if slot in result.errors:
                metrics.per_cue_total[slot] = metrics.per_cue_total.get(slot, 0) + 1
                if result.errors[slot] <= tolerance:
                    metrics.per_cue_correct[slot] = metrics.per_cue_correct.get(slot, 0) + 1
                else:
                    all_correct = False
            elif slot in result.gold:
                all_correct = False
        
        if all_correct and len(result.predicted) == 8:
            metrics.all_8_correct += 1
    
    return metrics


class TestEvalHarness:
    """Test the evaluation harness itself."""

    def test_load_gold_cues(self, gold_cues_csv: Path | None):
        """Test loading gold cues from CSV."""
        if gold_cues_csv is None:
            pytest.skip("Gold cues CSV not available")
        
        gold = load_gold_cues(gold_cues_csv)
        
        assert len(gold) > 0, "No gold cues loaded"
        
        for path, g in list(gold.items())[:5]:
            assert g.bpm > 0
            assert 3 in g.cues, f"Missing cue4 in {path}"

    def test_evaluation_metrics(self):
        """Test metrics computation."""
        gold = GoldCues(
            path="test.mp3",
            bpm=128.0,
            cues={0: 0, 1: 32, 2: 64, 3: 96, 4: 160, 5: 192, 6: 224, 7: 256},
        )
        
        perfect_pred = {0: 0, 1: 32, 2: 64, 3: 96, 4: 160, 5: 192, 6: 224, 7: 256}
        result = evaluate_prediction(perfect_pred, gold)
        
        assert all(e == 0 for e in result.errors.values())
        
        metrics = compute_metrics([result])
        assert metrics.cue4_accuracy == 1.0
        assert metrics.cue6_accuracy == 1.0
        assert metrics.all_8_correct == 1


class TestQAEvaluation:
    """Evaluate on real QA songs."""

    def test_evaluate_qa_songs(
        self,
        qa_songs_dir: Path | None,
        gold_cues_csv: Path | None,
    ):
        """Evaluate predictions on QA songs and report errors."""
        if qa_songs_dir is None:
            pytest.skip("QA songs not available")
        if gold_cues_csv is None:
            pytest.skip("Gold cues CSV not available")
        
        gold_data = load_gold_cues(gold_cues_csv)
        
        results = []
        
        for mp3 in qa_songs_dir.glob("*.mp3"):
            gold_key = None
            for key in gold_data.keys():
                if mp3.stem in key or key.endswith(mp3.name):
                    gold_key = key
                    break
            
            if gold_key is None:
                print(f"No gold data for {mp3.name}")
                continue
            
            gold = gold_data[gold_key]
            
            print(f"\n=== {mp3.name} ===")
            print(f"Gold cues (beats): {gold.cues}")
            
            from auto_cue.tags import read_track_tags, cues_to_beats
            
            tags = read_track_tags(mp3)
            assert tags.markers2 is not None
            assert tags.beatgrid is not None
            
            actual_beats = cues_to_beats(tags.markers2, tags.beatgrid)
            print(f"Actual cues from file (beats): {actual_beats}")
            
            for slot, expected in gold.cues.items():
                if slot in actual_beats:
                    error = abs(actual_beats[slot] - expected)
                    print(f"  Cue {slot+1}: expected={expected:.1f}, actual={actual_beats[slot]:.1f}, error={error:.1f} beats")

    def test_blind_prediction_on_qa(
        self,
        qa_songs_dir: Path | None,
        gold_cues_csv: Path | None,
        temp_dir: Path,
    ):
        """Run blind prediction (strip cues, predict, compare) on QA songs."""
        if qa_songs_dir is None:
            pytest.skip("QA songs not available")
        if gold_cues_csv is None:
            pytest.skip("Gold cues CSV not available")
        
        import shutil
        from auto_cue.tags import (
            read_track_tags,
            write_track_markers2,
            Markers2Data,
            cues_to_beats,
        )
        from auto_cue.features import extract_features
        from auto_cue.llm import predict_cues_rules, prediction_to_cue_set
        
        gold_data = load_gold_cues(gold_cues_csv)
        
        print("\n" + "=" * 60)
        print("BLIND PREDICTION TEST (rule-based, no LLM)")
        print("=" * 60)
        
        results = []
        
        for mp3 in qa_songs_dir.glob("*.mp3"):
            gold_key = None
            for key in gold_data.keys():
                if mp3.stem in key or key.endswith(mp3.name):
                    gold_key = key
                    break
            
            if gold_key is None:
                continue
            
            gold = gold_data[gold_key]
            
            copy_path = temp_dir / mp3.name
            shutil.copy2(mp3, copy_path)
            
            original_tags = read_track_tags(copy_path)
            beatgrid = original_tags.beatgrid
            
            empty_markers = Markers2Data()
            write_track_markers2(copy_path, empty_markers)
            
            tags = read_track_tags(copy_path)
            assert len(tags.markers2.cues) == 0
            
            try:
                features = extract_features(
                    copy_path,
                    beatgrid.bpm,
                    beatgrid.first_beat_s,
                )
                
                prediction = predict_cues_rules(features)
                cues = prediction_to_cue_set(prediction, features.total_beats)
                predicted = cues.to_dict()
                
                result = evaluate_prediction(predicted, gold)
                results.append(result)
                
                print(f"\n{mp3.name}:")
                print(f"  BPM: {beatgrid.bpm:.1f}, Total beats: {features.total_beats}")
                print(f"  Gold:      {dict(sorted(gold.cues.items()))}")
                print(f"  Predicted: {dict(sorted(predicted.items()))}")
                print(f"  Errors (beats):")
                for slot in sorted(result.errors.keys()):
                    err = result.errors[slot]
                    status = "✓" if err <= 1 else "✗"
                    print(f"    Cue {slot+1}: {err:6.1f} {status}")
                
            except Exception as e:
                print(f"\n{mp3.name}: ERROR - {e}")
                results.append(EvalResult(
                    path=str(mp3),
                    predicted={},
                    gold=gold.cues,
                    errors={},
                    abstained=True,
                ))
        
        if results:
            metrics = compute_metrics(results)
            print("\n" + "=" * 60)
            print("SUMMARY")
            print("=" * 60)
            print(f"Total tracks: {metrics.total}")
            print(f"Processed:    {metrics.processed}")
            print(f"Abstained:    {metrics.abstained} ({metrics.abstain_rate:.1%})")
            print(f"Cue4 accuracy: {metrics.cue4_correct}/{metrics.cue4_total} = {metrics.cue4_accuracy:.1%}")
            print(f"Cue6 accuracy: {metrics.cue6_correct}/{metrics.cue6_total} = {metrics.cue6_accuracy:.1%}")
            print(f"Mean per-cue: {metrics.mean_per_cue_accuracy:.1%}")
            print(f"All 8 correct: {metrics.all_8_correct}/{metrics.processed}")
