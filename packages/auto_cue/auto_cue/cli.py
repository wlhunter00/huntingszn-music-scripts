"""auto-cue CLI — automatic Serato hot-cue tagger.

Dry-run by default. Backs up files before writing. Refuses while Serato is running.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from serato_bpm_cleanup.backup import timestamped_backup_root
from serato_bpm_cleanup.detect import serato_is_running, default_library_roots

from auto_cue import __version__
from auto_cue.tags import (
    read_track_tags,
    write_track_markers2,
    Markers2Data,
    CuePoint,
    SERATO_DEFAULT_COLORS,
    beats_to_ms,
)
from auto_cue.protection import (
    check_protection,
    decide_cue_write,
    load_protected_paths,
)
from auto_cue.validate import (
    CueSet,
    validate_cue_set,
    check_confidence_threshold,
)
from auto_cue.features import extract_features, check_grid_alignment
from auto_cue.llm import (
    predict_cues_llm,
    predict_cues_rules,
    prediction_to_cue_set,
    LLMAPIError,
    CueAbstainError,
)


AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".aac", ".wav", ".aiff", ".aif"}
WRITABLE_EXTENSIONS = {".mp3", ".flac"}

CLOSE_SERATO_WARNING = (
    "WARNING: Close Serato DJ Pro before writing. Serato can overwrite tags on exit."
)


@dataclass
class ProcessResult:
    """Result of processing a single track."""
    path: Path
    action: str  # write, would-write, skip-*, abstain-*, error-*
    cues_set: dict[int, int] | None = None
    error: str | None = None
    confidence: float = 0.0
    is_api_error: bool = False  # True for API/auth/HTTP errors that should fail fast


def iter_audio_files(root: Path) -> list[Path]:
    """Iterate over audio files in a directory."""
    if root.is_file():
        if root.suffix.lower() in AUDIO_EXTENSIONS:
            return [root]
        return []
    
    files = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
            if not path.name.startswith("._"):
                files.append(path)
    return sorted(files)


def process_track(
    path: Path,
    *,
    write: bool = False,
    replace_mik: bool = False,
    use_llm: bool = True,
    model: str = "gpt-6-luna",
    reasoning_effort: str = "medium",
    min_confidence: float = 0.6,
    backup_root: Path | None = None,
    protected_paths: set[str] | None = None,
    library_root: Path | None = None,
    explain: bool = False,
) -> ProcessResult:
    """Process a single track for cue prediction.
    
    Args:
        path: Audio file path
        write: Actually write tags (vs dry-run)
        replace_mik: Replace MIK Energy cues
        use_llm: Use LLM for prediction (vs rules-only)
        min_confidence: Minimum confidence threshold
        backup_root: Backup directory
        protected_paths: Paths from protected crates
        library_root: Library root for relative path calculation
        explain: Print detailed analysis
    
    Returns:
        ProcessResult with action taken
    """
    result = ProcessResult(path=path, action="unknown")
    
    tags = read_track_tags(path)
    
    if tags.error:
        result.action = f"skip-error"
        result.error = tags.error
        return result
    
    relative_path = None
    if library_root:
        try:
            relative_path = str(path.relative_to(library_root))
        except ValueError:
            pass
    
    decision = decide_cue_write(
        tags,
        replace_mik=replace_mik,
        protected_paths=protected_paths,
        track_relative_path=relative_path,
    )
    
    if not decision.should_write:
        result.action = f"skip-{decision.action}"
        result.error = "; ".join(decision.reasons)
        return result
    
    if not tags.beatgrid:
        result.action = "abstain-no-grid"
        return result
    
    if tags.beatgrid.is_dynamic:
        result.action = "abstain-dynamic-grid"
        return result
    
    bpm = tags.beatgrid.bpm
    first_beat_s = tags.beatgrid.first_beat_s
    
    if bpm is None or first_beat_s is None:
        result.action = "abstain-invalid-grid"
        return result
    
    if path.suffix.lower() not in WRITABLE_EXTENSIONS:
        result.action = f"skip-unsupported-format"
        result.error = f"Cannot write to {path.suffix}"
        return result
    
    try:
        features = extract_features(path, bpm, first_beat_s)
    except Exception as e:
        result.action = "abstain-feature-error"
        result.error = str(e)
        return result
    
    if explain:
        from auto_cue.features import format_phrase_table
        print(f"\n=== {path.name} ===")
        print(format_phrase_table(features))
    
    try:
        if use_llm:
            try:
                prediction = predict_cues_llm(features, model=model, reasoning_effort=reasoning_effort)
            except LLMAPIError as e:
                result.action = "error-api"
                result.error = str(e)
                result.is_api_error = True
                return result
            except CueAbstainError as e:
                if explain:
                    print(f"LLM abstained: {e}")
                result.action = "abstain-llm"
                result.error = str(e)
                return result
        else:
            prediction = predict_cues_rules(features)
    except LLMAPIError as e:
        result.action = "error-api"
        result.error = str(e)
        result.is_api_error = True
        return result
    except CueAbstainError as e:
        result.action = "abstain-rules"
        result.error = str(e)
        return result
    except Exception as e:
        result.action = "abstain-prediction-error"
        result.error = str(e)
        return result
    
    if explain:
        print(f"Prediction: cue4={prediction.cue4_beat}, cue6={prediction.cue6_beat}")
        print(f"Confidence: {prediction.confidence:.2f}")
        print(f"Rationale: {prediction.rationale}")
    
    cues = prediction_to_cue_set(prediction, features.total_beats)
    
    validation = validate_cue_set(cues)
    if not validation.valid:
        result.action = "abstain-validation-failed"
        result.error = "; ".join(validation.errors)
        return result
    
    if validation.warnings and explain:
        for w in validation.warnings:
            print(f"Warning: {w}")
    
    filtered_cues, abstain_reasons = check_confidence_threshold(
        cues,
        core_threshold=min_confidence,
    )
    
    if abstain_reasons:
        result.action = "abstain-low-confidence"
        result.error = "; ".join(abstain_reasons)
        return result
    
    cue_beats = filtered_cues.to_dict()
    result.cues_set = cue_beats
    result.confidence = prediction.confidence
    
    if explain:
        print(f"Final cues (beats): {cue_beats}")
    
    if not write:
        result.action = "would-write"
        return result
    
    try:
        markers = tags.markers2 or Markers2Data()
        
        markers.cues = []
        for index, beat in cue_beats.items():
            position_ms = beats_to_ms(beat, tags.beatgrid)
            color = SERATO_DEFAULT_COLORS.get(index, (0xCC, 0x00, 0x00))
            markers.cues.append(CuePoint(
                index=index,
                position_ms=position_ms,
                color=color,
                name="",
            ))
        
        write_track_markers2(path, markers, backup_root=backup_root, delete_v1=True)
        result.action = "write"
    except Exception as e:
        result.action = "error-write"
        result.error = str(e)
    
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="auto-cue",
        description=(
            "Automatic Serato hot-cue tagger. Predicts 8 cues from audio features "
            "using Will's cue system. Dry-run by default."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--library",
        type=Path,
        help="Audio folder to scan. Auto-detects DJ Music on Windows.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Process a single file.",
    )
    parser.add_argument(
        "--crate",
        type=str,
        help="Process only tracks in this crate (e.g., 'Sets/NYE 26').",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Actually write tags (default is dry-run). Refuses if Serato is running.",
    )
    parser.add_argument(
        "--replace-mik",
        action="store_true",
        help="Replace tracks with only MIK 'Energy N' cues.",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Use rule-based prediction only (no LLM API calls).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-6-luna",
        help="LLM model to use (default: gpt-6-luna).",
    )
    parser.add_argument(
        "--reasoning-effort",
        type=str,
        default="medium",
        choices=["low", "medium", "high"],
        help="Reasoning effort for reasoning models (default: medium).",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.6,
        help="Minimum confidence threshold for core cues (default 0.6).",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Print phrase table and prediction rationale.",
    )
    parser.add_argument(
        "--max-tracks",
        type=int,
        help="Maximum tracks to process.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        help="Write results to CSV.",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="Backup directory (default: auto-cue-backups/<utc>/).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="Path to Serato database V2 for crate parsing.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    
    print(CLOSE_SERATO_WARNING, file=sys.stderr)
    
    if args.write and serato_is_running():
        print(
            "ERROR: Serato appears to be running. Close Serato DJ Pro before --write.",
            file=sys.stderr,
        )
        return 1
    
    if args.file:
        files = [args.file]
        library_root = args.file.parent
    elif args.library:
        files = iter_audio_files(args.library)
        library_root = args.library
    else:
        roots = default_library_roots(None)
        if not roots:
            print("No library found. Use --library or --file.", file=sys.stderr)
            return 2
        library_root = roots[0]
        files = iter_audio_files(library_root)
    
    if not files:
        print("No audio files found.", file=sys.stderr)
        return 2
    
    protected_paths: set[str] = set()
    if args.db:
        serato_dir = args.db.parent
        protected_paths = load_protected_paths(serato_dir)
    elif library_root:
        for candidate in [
            library_root / "_Serato_",
            library_root.parent / "_Serato_",
        ]:
            if candidate.is_dir():
                protected_paths = load_protected_paths(candidate)
                break
    
    if args.max_tracks:
        files = files[:args.max_tracks]
    
    backup_root = None
    if args.write:
        backup_base = args.backup_dir or Path("auto-cue-backups")
        backup_root = timestamped_backup_root(backup_base)
    
    results: list[ProcessResult] = []
    
    for path in files:
        result = process_track(
            path,
            write=args.write,
            replace_mik=args.replace_mik,
            use_llm=not args.no_llm,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            min_confidence=args.min_confidence,
            backup_root=backup_root,
            protected_paths=protected_paths,
            library_root=library_root,
            explain=args.explain,
        )
        results.append(result)
        
        prefix = "[dry-run] " if not args.write else ""
        if result.action.startswith("would-write") or result.action == "write":
            cue_str = ", ".join(f"{k+1}={v}" for k, v in sorted((result.cues_set or {}).items()))
            print(f"{prefix}{result.action}: {result.path.name} [{cue_str}]")
        elif result.action.startswith("skip") or result.action.startswith("abstain"):
            print(f"{prefix}{result.action}: {result.path.name} ({result.error or ''})")
    
    action_counts: dict[str, int] = {}
    for r in results:
        action_counts[r.action] = action_counts.get(r.action, 0) + 1
    
    print(f"\nSummary: {len(results)} files processed")
    for action, count in sorted(action_counts.items()):
        print(f"  {action}: {count}")
    
    if backup_root:
        print(f"Backups: {backup_root}")
    
    if args.csv:
        _write_csv(args.csv, results)
        print(f"CSV: {args.csv}")
    
    api_errors = [r for r in results if r.is_api_error]
    if api_errors:
        print(f"\nERROR: {len(api_errors)} API/auth error(s) - these are NOT abstentions!", file=sys.stderr)
        for r in api_errors[:3]:
            print(f"  {r.path.name}: {r.error}", file=sys.stderr)
        return 3  # Distinct exit code for API errors
    
    write_errors = [r for r in results if r.action == "error-write"]
    return 1 if write_errors else 0


def _write_csv(path: Path, results: list[ProcessResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["path", "action", "cues", "confidence", "error"])
        for r in results:
            cue_str = ""
            if r.cues_set:
                cue_str = ";".join(f"{k}:{v}" for k, v in sorted(r.cues_set.items()))
            writer.writerow([str(r.path), r.action, cue_str, f"{r.confidence:.2f}", r.error or ""])


if __name__ == "__main__":
    raise SystemExit(main())
