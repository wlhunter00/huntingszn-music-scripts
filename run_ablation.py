#!/usr/bin/env python3
"""Run full ablation study on 42-track eval set."""

import json
import os
import sys
from pathlib import Path

# Ensure OPENAI_API_KEY is set
if not os.environ.get("OPENAI_API_KEY"):
    print("ERROR: OPENAI_API_KEY not set")
    sys.exit(1)

from auto_cue.eval import run_eval, compute_summary, analyze_errors, results_by_bpm_band

AUDIO_DIR = Path("/workspace/qa-all")
GOLD_CSV = Path("/workspace/qa-all/gold.csv")
POOL_DIR = Path("/workspace/gold-pool")
MODEL = "gpt-6.1-terra"
REASONING = "medium"

def run_arm(name: str, use_fewshot: bool, use_demucs: bool, pool_dir: Path | None):
    """Run one ablation arm and return results."""
    print(f"\n{'='*60}")
    print(f"ABLATION ARM: {name}")
    print(f"  use_fewshot={use_fewshot}, use_demucs={use_demucs}")
    print(f"{'='*60}")
    
    results, summary = run_eval(
        AUDIO_DIR,
        gold_csv=GOLD_CSV,
        use_llm=True,
        model=MODEL,
        reasoning_effort=REASONING,
        use_fewshot=use_fewshot,
        use_demucs=use_demucs,
        pool_dir=pool_dir if use_fewshot else None,
    )
    
    error_analysis = analyze_errors(results)
    bpm_stats = results_by_bpm_band(results)
    
    return {
        "name": name,
        "results": results,
        "summary": summary,
        "error_analysis": error_analysis,
        "bpm_stats": bpm_stats,
    }

def format_arm_report(arm_data: dict) -> str:
    """Format report for one ablation arm."""
    name = arm_data["name"]
    summary = arm_data["summary"]
    error_analysis = arm_data["error_analysis"]
    bpm_stats = arm_data["bpm_stats"]
    
    lines = []
    lines.append(f"\n## {name}")
    lines.append("")
    
    # Main metrics - cue4 is slot 3, cue6 is slot 5
    cue4_correct = summary.per_cue_correct.get(3, 0)
    cue6_correct = summary.per_cue_correct.get(5, 0)
    cue4_all = cue4_correct / summary.total if summary.total > 0 else 0
    cue6_all = cue6_correct / summary.total if summary.total > 0 else 0
    all8 = summary.all_8_correct
    processed = summary.processed
    skip_rate = summary.abstain_rate
    cost_per_track = summary.total_cost_usd / summary.total if summary.total > 0 else 0
    
    lines.append("### Main Metrics")
    lines.append(f"- **Cue4 (all)**: {cue4_correct}/{summary.total} = {cue4_all:.1%}")
    lines.append(f"- **Cue6 (all)**: {cue6_correct}/{summary.total} = {cue6_all:.1%}")
    lines.append(f"- **All 8 correct**: {all8}/{processed}")
    lines.append(f"- **Skip rate**: {summary.abstained}/{summary.total} = {skip_rate:.1%}")
    lines.append(f"- **Cost/track**: ${cost_per_track:.4f}")
    
    # Error analysis
    lines.append("")
    lines.append("### Error Analysis (±16/±32)")
    lines.append(f"- Total errors (>1 beat): {error_analysis.get('total_errors', 0)}")
    lines.append(f"- ±16 beat errors: {error_analysis.get('errors_16', 0)}")
    lines.append(f"- ±32 beat errors: {error_analysis.get('errors_32', 0)}")
    lines.append(f"- Cue4 ±16: {error_analysis.get('cue4_errors_16', 0)}")
    lines.append(f"- Cue4 ±32: {error_analysis.get('cue4_errors_32', 0)}")
    lines.append(f"- Cue6 ±16: {error_analysis.get('cue6_errors_16', 0)}")
    lines.append(f"- Cue6 ±32: {error_analysis.get('cue6_errors_32', 0)}")
    
    # BPM band results
    lines.append("")
    lines.append("### Results by BPM Band")
    lines.append("| BPM Band | Tracks | Cue4 | Cue6 |")
    lines.append("|----------|--------|------|------|")
    for band, stats in sorted(bpm_stats.items()):
        c4_hits = stats.get('cue4_hits', 0)
        c6_hits = stats.get('cue6_hits', 0)
        total = stats.get('total', 0)
        c4_pct = f"{c4_hits}/{total} = {c4_hits/total:.0%}" if total > 0 else "N/A"
        c6_pct = f"{c6_hits}/{total} = {c6_hits/total:.0%}" if total > 0 else "N/A"
        lines.append(f"| {band} | {total} | {c4_pct} | {c6_pct} |")
    
    return "\n".join(lines)

def main():
    """Run all ablation arms and generate report."""
    
    arms = [
        ("Terra baseline (no fewshot, no demucs)", False, False, None),
        ("+ fewshot (v2 pool)", True, False, POOL_DIR),
        ("+ demucs (vocal activity)", False, True, None),
        ("+ fewshot + demucs (everything)", True, True, POOL_DIR),
    ]
    
    all_results = []
    
    for name, use_fewshot, use_demucs, pool_dir in arms:
        arm_data = run_arm(name, use_fewshot, use_demucs, pool_dir)
        all_results.append(arm_data)
    
    # Generate combined report
    print("\n" + "="*60)
    print("ABLATION STUDY REPORT")
    print("="*60)
    
    report_lines = []
    report_lines.append("# Ablation Study Results")
    report_lines.append("")
    report_lines.append("**Model**: gpt-6.1-terra (medium reasoning)")
    report_lines.append("**Eval set**: 42 tracks (excluding qa06, qa25, qa32)")
    report_lines.append("**Gold pool**: v2 cleaned (289 tracks)")
    report_lines.append("")
    
    # Summary table
    report_lines.append("## Summary")
    report_lines.append("")
    report_lines.append("| Arm | Cue4 | Cue6 | All 8 | Skip | Cost/track |")
    report_lines.append("|-----|------|------|-------|------|------------|")
    
    for arm_data in all_results:
        s = arm_data["summary"]
        cue4_correct = s.per_cue_correct.get(3, 0)
        cue6_correct = s.per_cue_correct.get(5, 0)
        c4 = cue4_correct / s.total if s.total > 0 else 0
        c6 = cue6_correct / s.total if s.total > 0 else 0
        cost = s.total_cost_usd / s.total if s.total > 0 else 0
        report_lines.append(
            f"| {arm_data['name'][:30]} | {c4:.1%} | {c6:.1%} | {s.all_8_correct}/{s.processed} | {s.abstain_rate:.1%} | ${cost:.4f} |"
        )
    
    # Detailed results for each arm
    for arm_data in all_results:
        report_lines.append(format_arm_report(arm_data))
    
    report = "\n".join(report_lines)
    print(report)
    
    # Save report
    report_path = Path("/workspace/packages/auto_cue/ABLATION_RESULTS.md")
    report_path.write_text(report)
    print(f"\nReport saved to: {report_path}")
    
    return all_results

if __name__ == "__main__":
    main()
