#!/usr/bin/env python3
"""Generate detailed miss analysis report from diagnostics JSON."""

import json
from pathlib import Path
from collections import defaultdict

def load_diagnostics():
    with open("/workspace/drop_diagnostics.json") as f:
        return json.load(f)

def reclassify_cause(miss: dict, total_beats: int) -> tuple[str, str]:
    """Reclassify the cause with corrected rules (16-beat lattice is valid)."""
    if miss is None:
        return None, None
    
    gold_beat = int(round(miss["gold_beat"]))
    pred_beat = miss["pred_beat"]
    offset = miss["offset_beats"]
    abs_offset = abs(offset)
    original_cause = miss["cause"]
    
    # If it's skipped/abstained, keep that
    if original_cause == "skipped":
        return "skipped", miss["cause_detail"]
    
    # Check if gold is on valid lattice (16-beat is OK per corrected rules)
    gold_on_16 = (gold_beat % 16 == 0)
    
    # Check fractional beat (true grid misalignment)
    gold_fraction = abs(miss["gold_beat"] - round(miss["gold_beat"]))
    if gold_fraction > 0.1:
        return "grid_phase", f"Gold beat {miss['gold_beat']:.3f} not on integer grid (fraction={gold_fraction:.3f})"
    
    # Gold not even on 16-beat lattice - TRUE grid problem
    if not gold_on_16:
        return "grid_off_lattice", f"Gold beat {gold_beat} not on 16-beat lattice ({gold_beat} % 16 = {gold_beat % 16})"
    
    # Check candidate recall
    gold_in_cands = miss.get("gold_in_candidates", False)
    if not gold_in_cands:
        cands = miss.get("candidate_set", [])
        return "candidate_recall", f"Gold beat {gold_beat} not in candidates {cands[:5]}"
    
    # Now it's in candidates - check if model picked wrong one
    
    # ±16 beat error (fakeout/run-up)
    if 15 <= abs_offset <= 17:
        # Check if this is pre-drop vs post-drop
        if offset < 0:
            return "fakeout_runup", f"Model picked {pred_beat} which is 16 beats BEFORE gold {gold_beat} (run-up before drop)"
        else:
            return "fakeout_post", f"Model picked {pred_beat} which is 16 beats AFTER gold {gold_beat} (post-drop marker)"
    
    # ±32 beat error
    if 31 <= abs_offset <= 33:
        if offset < 0:
            return "offset_32_pre", f"Model picked {pred_beat} which is 32 beats BEFORE gold {gold_beat}"
        else:
            return "offset_32_post", f"Model picked {pred_beat} which is 32 beats AFTER gold {gold_beat}"
    
    # Check for wrong_drop
    if original_cause == "wrong_drop":
        return "wrong_drop", miss["cause_detail"]
    
    # Check for gold_questionable
    if original_cause == "gold_questionable":
        return "gold_questionable", miss["cause_detail"]
    
    # Default: judgment failure
    gold_score = miss.get("gold_drop_score", 0)
    pred_score = miss.get("pred_drop_score", 0)
    return "judgment", f"Gold ({gold_beat}, score={gold_score:.1f}) was in candidates but model picked ({pred_beat}, score={pred_score:.1f})"


def analyze_feature_comparison(misses: list[dict]) -> str:
    """Analyze features at gold vs predicted for representative misses."""
    lines = []
    
    # Group by cause type
    by_cause = defaultdict(list)
    for m in misses:
        if m and m.get("gold_features") and m.get("pred_features"):
            cause, _ = reclassify_cause(m, 0)
            by_cause[cause].append(m)
    
    for cause in ["fakeout_runup", "fakeout_post", "judgment", "candidate_recall"]:
        if cause not in by_cause:
            continue
        
        examples = by_cause[cause][:3]
        if not examples:
            continue
        
        lines.append(f"\n### {cause.replace('_', ' ').title()} Examples\n")
        
        for m in examples:
            gf = m.get("gold_features", {})
            pf = m.get("pred_features", {})
            
            lines.append(f"**{m['track']}** - Gold beat {int(m['gold_beat'])}, Predicted beat {m['pred_beat']}")
            lines.append("")
            lines.append("| Feature | Gold | Pred | Delta |")
            lines.append("|---------|------|------|-------|")
            
            key_features = [
                ("drop_score", "Drop Score"),
                ("delta_low", "Bass Jump"),
                ("contrast_score", "Contrast"),
                ("novelty_score", "Novelty"),
                ("kick_density", "Kick Density"),
                ("post_sustain", "Post Sustain"),
                ("rms_db", "RMS dB"),
            ]
            
            for key, label in key_features:
                g = gf.get(key, 0)
                p = pf.get(key, 0)
                d = p - g if isinstance(g, (int, float)) and isinstance(p, (int, float)) else "—"
                d_str = f"{d:+.1f}" if isinstance(d, (int, float)) else d
                lines.append(f"| {label} | {g:.1f} | {p:.1f} | {d_str} |")
            
            lines.append("")
    
    return "\n".join(lines)


def check_simple_rule_wins(misses: list[dict]) -> dict:
    """Check if a simple rule (strongest kick slam-in on lattice) would beat model."""
    simple_wins = 0
    simple_total = 0
    examples = []
    
    for m in misses:
        if not m or not m.get("gold_in_candidates"):
            continue
        
        gold_score = m.get("gold_drop_score", 0)
        pred_score = m.get("pred_drop_score", 0)
        
        # If gold has higher drop score, simple "pick highest score" would have won
        if gold_score > pred_score:
            simple_wins += 1
            examples.append({
                "track": m["track"],
                "gold_beat": int(m["gold_beat"]),
                "pred_beat": m["pred_beat"],
                "gold_score": gold_score,
                "pred_score": pred_score,
            })
        
        simple_total += 1
    
    return {
        "wins": simple_wins,
        "total": simple_total,
        "pct": simple_wins / simple_total * 100 if simple_total > 0 else 0,
        "examples": examples[:5],
    }


def generate_report(diagnostics: list[dict]) -> str:
    """Generate the markdown report."""
    lines = []
    
    # Header
    lines.append("# Drop Miss Analysis (Cue 4 and Cue 6)")
    lines.append("")
    lines.append("**Model**: gpt-6.1-terra (medium reasoning)")
    lines.append("**Configuration**: + fewshot (v2 pool) + demucs")
    lines.append("**Eval set**: 42 tracks (excluding qa06, qa25, qa32)")
    lines.append("")
    
    # Overall stats
    total = len(diagnostics)
    abstained = sum(1 for d in diagnostics if d["abstained"])
    processed = total - abstained
    
    cue4_correct = sum(1 for d in diagnostics if not d["abstained"] and d["errors"].get("3", 999) <= 1)
    cue6_correct = sum(1 for d in diagnostics if not d["abstained"] and d["errors"].get("5", 999) <= 1)
    
    lines.append("## Overall Performance")
    lines.append("")
    lines.append(f"- Total tracks: {total}")
    lines.append(f"- Processed: {processed} (abstained: {abstained})")
    lines.append(f"- **Cue4 correct**: {cue4_correct}/{total} = {cue4_correct/total:.1%}")
    lines.append(f"- **Cue6 correct**: {cue6_correct}/{total} = {cue6_correct/total:.1%}")
    lines.append("")
    
    # Collect all misses
    cue4_misses = [d.get("cue4_miss") for d in diagnostics if d.get("cue4_miss")]
    cue6_misses = [d.get("cue6_miss") for d in diagnostics if d.get("cue6_miss")]
    all_misses = cue4_misses + cue6_misses
    
    # Reclassify all misses
    cue4_causes = defaultdict(list)
    cue6_causes = defaultdict(list)
    
    for m in cue4_misses:
        cause, detail = reclassify_cause(m, 0)
        cue4_causes[cause].append((m, detail))
    
    for m in cue6_misses:
        cause, detail = reclassify_cause(m, 0)
        cue6_causes[cause].append((m, detail))
    
    # Cause breakdown
    lines.append("## Cause Classification")
    lines.append("")
    lines.append("### Cue 4 Misses")
    lines.append("")
    lines.append("| Cause | Count | % of Misses |")
    lines.append("|-------|-------|-------------|")
    cue4_total_misses = len(cue4_misses)
    for cause in sorted(cue4_causes.keys(), key=lambda c: -len(cue4_causes[c])):
        count = len(cue4_causes[cause])
        pct = count / cue4_total_misses * 100 if cue4_total_misses > 0 else 0
        lines.append(f"| {cause} | {count} | {pct:.0f}% |")
    lines.append("")
    
    lines.append("### Cue 6 Misses")
    lines.append("")
    lines.append("| Cause | Count | % of Misses |")
    lines.append("|-------|-------|-------------|")
    cue6_total_misses = len(cue6_misses)
    for cause in sorted(cue6_causes.keys(), key=lambda c: -len(cue6_causes[c])):
        count = len(cue6_causes[cause])
        pct = count / cue6_total_misses * 100 if cue6_total_misses > 0 else 0
        lines.append(f"| {cause} | {count} | {pct:.0f}% |")
    lines.append("")
    
    # Candidate recall
    cue4_gold_in_cands = sum(1 for m in cue4_misses if m and m.get("gold_in_candidates"))
    cue6_gold_in_cands = sum(1 for m in cue6_misses if m and m.get("gold_in_candidates"))
    
    lines.append("## Candidate Recall")
    lines.append("")
    lines.append(f"- **Cue4**: Gold in candidates for {cue4_gold_in_cands}/{len(cue4_misses)} misses = {cue4_gold_in_cands/len(cue4_misses)*100:.0f}% recall")
    lines.append(f"- **Cue6**: Gold in candidates for {cue6_gold_in_cands}/{len(cue6_misses)} misses = {cue6_gold_in_cands/len(cue6_misses)*100:.0f}% recall")
    lines.append("")
    lines.append("*When gold is in candidates, the issue is model judgment. When gold is NOT in candidates, feature/recall failed.*")
    lines.append("")
    
    # Per-track table
    lines.append("## Per-Track Miss Details")
    lines.append("")
    lines.append("### Cue 4 Misses")
    lines.append("")
    lines.append("| Track | BPM Band | Gold | Pred | Offset | Cause | In Candidates | Gold Score | Pred Score |")
    lines.append("|-------|----------|------|------|--------|-------|---------------|------------|------------|")
    
    for d in diagnostics:
        m = d.get("cue4_miss")
        if not m:
            continue
        cause, _ = reclassify_cause(m, d["total_beats"])
        gold_beat = int(round(m["gold_beat"]))
        in_cands = "✓" if m.get("gold_in_candidates") else "✗"
        gold_score = m.get("gold_drop_score", 0)
        pred_score = m.get("pred_drop_score", 0)
        
        lines.append(f"| {m['track']} | {m['bpm_band']} | {gold_beat} | {m['pred_beat']} | {m['offset_beats']:+.0f} | {cause} | {in_cands} | {gold_score:.1f} | {pred_score:.1f} |")
    
    lines.append("")
    lines.append("### Cue 6 Misses")
    lines.append("")
    lines.append("| Track | BPM Band | Gold | Pred | Offset | Cause | In Candidates | Gold Score | Pred Score |")
    lines.append("|-------|----------|------|------|--------|-------|---------------|------------|------------|")
    
    for d in diagnostics:
        m = d.get("cue6_miss")
        if not m:
            continue
        cause, _ = reclassify_cause(m, d["total_beats"])
        gold_beat = int(round(m["gold_beat"]))
        in_cands = "✓" if m.get("gold_in_candidates") else "✗"
        gold_score = m.get("gold_drop_score", 0)
        pred_score = m.get("pred_drop_score", 0)
        
        lines.append(f"| {m['track']} | {m['bpm_band']} | {gold_beat} | {m['pred_beat']} | {m['offset_beats']:+.0f} | {cause} | {in_cands} | {gold_score:.1f} | {pred_score:.1f} |")
    
    lines.append("")
    
    # Feature comparison
    lines.append("## Feature Comparison (Gold vs Predicted)")
    lines.append("")
    lines.append("Representative examples showing feature values at gold drop vs model's pick:")
    lines.append("")
    lines.append(analyze_feature_comparison(all_misses))
    
    # Simple rule analysis
    lines.append("## Would Simple Rules Beat the Model?")
    lines.append("")
    
    cue4_simple = check_simple_rule_wins(cue4_misses)
    cue6_simple = check_simple_rule_wins(cue6_misses)
    
    lines.append("### Rule: Pick highest drop_score on lattice")
    lines.append("")
    lines.append(f"- **Cue4**: Would fix {cue4_simple['wins']}/{cue4_simple['total']} judgment errors = {cue4_simple['pct']:.0f}%")
    lines.append(f"- **Cue6**: Would fix {cue6_simple['wins']}/{cue6_simple['total']} judgment errors = {cue6_simple['pct']:.0f}%")
    lines.append("")
    
    if cue4_simple["examples"] or cue6_simple["examples"]:
        lines.append("Examples where gold score > pred score:")
        lines.append("")
        for ex in (cue4_simple["examples"] + cue6_simple["examples"])[:5]:
            lines.append(f"- **{ex['track']}**: Gold beat {ex['gold_beat']} (score={ex['gold_score']:.1f}) vs Pred beat {ex['pred_beat']} (score={ex['pred_score']:.1f})")
        lines.append("")
    
    # BPM band breakdown
    lines.append("## Misses by BPM Band")
    lines.append("")
    
    by_band = defaultdict(lambda: {"cue4_miss": 0, "cue6_miss": 0, "total": 0})
    for d in diagnostics:
        band = d["bpm_band"] or "unknown"
        by_band[band]["total"] += 1
        if d.get("cue4_miss"):
            by_band[band]["cue4_miss"] += 1
        if d.get("cue6_miss"):
            by_band[band]["cue6_miss"] += 1
    
    lines.append("| BPM Band | Tracks | Cue4 Misses | Cue6 Misses |")
    lines.append("|----------|--------|-------------|-------------|")
    for band in ["bass (<80)", "dnb (80-100)", "midtempo (100-115)", "house (115+)", "unknown"]:
        if band in by_band:
            stats = by_band[band]
            lines.append(f"| {band} | {stats['total']} | {stats['cue4_miss']} | {stats['cue6_miss']} |")
    
    lines.append("")
    
    # Top 3 fixes
    lines.append("## Top 3 Concrete Fixes (Ranked by Expected Gain)")
    lines.append("")
    
    # Analyze which fixes would help most
    total_misses = len(cue4_misses) + len(cue6_misses)
    
    # Count causes across both
    all_causes = defaultdict(int)
    for cause in list(cue4_causes.keys()) + list(cue6_causes.keys()):
        all_causes[cause] = len(cue4_causes.get(cause, [])) + len(cue6_causes.get(cause, []))
    
    # Calculate potential gains
    fixes = []
    
    # Fix 1: Improve candidate recall
    recall_misses = all_causes.get("candidate_recall", 0)
    if recall_misses > 0:
        fixes.append({
            "name": "Improve candidate recall (feature scoring)",
            "misses_fixed": recall_misses,
            "pct_gain": recall_misses / total_misses * 100 if total_misses > 0 else 0,
            "desc": "Lower drop_score threshold OR add more candidate positions. Currently gold drops are not even surfaced as candidates in these cases.",
            "priority": recall_misses,
        })
    
    # Fix 2: Fix fakeout/runup selection
    fakeout_misses = all_causes.get("fakeout_runup", 0) + all_causes.get("fakeout_post", 0)
    if fakeout_misses > 0:
        fixes.append({
            "name": "Fix ±16 beat selection (run-up vs drop)",
            "misses_fixed": fakeout_misses,
            "pct_gain": fakeout_misses / total_misses * 100 if total_misses > 0 else 0,
            "desc": "Model picks 16 beats before/after the actual drop. Could penalize candidates too close to other candidates, or add explicit run-up detection.",
            "priority": fakeout_misses,
        })
    
    # Fix 3: Skipped tracks
    skipped_misses = all_causes.get("skipped", 0)
    if skipped_misses > 0:
        fixes.append({
            "name": "Fix validation/abstention logic",
            "misses_fixed": skipped_misses,
            "pct_gain": skipped_misses / total_misses * 100 if total_misses > 0 else 0,
            "desc": "Model abstains due to validation errors (cue4>cue5, cue7>cue5). Either relax these rules or improve candidate selection to avoid impossible configurations.",
            "priority": skipped_misses,
        })
    
    # Fix 4: Grid off-lattice
    grid_misses = all_causes.get("grid_off_lattice", 0)
    if grid_misses > 0:
        fixes.append({
            "name": "Support non-16-beat lattice drops",
            "misses_fixed": grid_misses,
            "pct_gain": grid_misses / total_misses * 100 if total_misses > 0 else 0,
            "desc": "Some tracks have drops on beats like 68, 72, 152 that are not on 16-beat boundaries. Consider adding 8-beat lattice or flexible lattice detection.",
            "priority": grid_misses,
        })
    
    # Fix 5: Wrong drop (for cue6)
    wrong_drop_misses = all_causes.get("wrong_drop", 0)
    if wrong_drop_misses > 0:
        fixes.append({
            "name": "Fix cue6 last-drop detection",
            "misses_fixed": wrong_drop_misses,
            "pct_gain": wrong_drop_misses / total_misses * 100 if total_misses > 0 else 0,
            "desc": "Model picks a drop that is not actually the LAST drop. Need better position-aware scoring or explicit 'is this the last high-energy section' check.",
            "priority": wrong_drop_misses,
        })
    
    # Sort by potential gain
    fixes.sort(key=lambda x: -x["priority"])
    
    for i, fix in enumerate(fixes[:3], 1):
        lines.append(f"### Fix #{i}: {fix['name']}")
        lines.append("")
        lines.append(f"**Misses potentially fixed**: {fix['misses_fixed']} ({fix['pct_gain']:.0f}% of all misses)")
        lines.append("")
        lines.append(f"**Implementation**: {fix['desc']}")
        lines.append("")
    
    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append("The main failure modes are:")
    lines.append("")
    
    for cause in sorted(all_causes.keys(), key=lambda c: -all_causes[c]):
        count = all_causes[cause]
        pct = count / total_misses * 100 if total_misses > 0 else 0
        lines.append(f"1. **{cause}**: {count} misses ({pct:.0f}%)")
    
    return "\n".join(lines)


def main():
    diagnostics = load_diagnostics()
    report = generate_report(diagnostics)
    
    output_path = Path("/workspace/packages/auto_cue/DROP_MISS_ANALYSIS.md")
    output_path.write_text(report)
    print(f"Report written to: {output_path}")
    
    print("\n" + "="*60)
    print(report[:3000])
    print("...")


if __name__ == "__main__":
    main()
