#!/usr/bin/env python3
"""Analyze DnB tracks for half/double-time beat counting issues.

Check:
- BPM 80-100 vs 160-200 (DnB can be labeled either way)
- Gold cue spacing patterns (16/32 in which tempo?)
- Compare gold spacing in DnB vs house to find systematic issues
"""

import os
from pathlib import Path
from collections import defaultdict

from auto_cue.gold import load_gold_csv, load_gold_pool

GOLD_CSV = Path("/workspace/qa-all/gold.csv")
POOL_DIR = Path("/workspace/gold-pool")


def analyze_cue_spacing(cues: dict, name: str, bpm: float):
    """Analyze spacing between cues in beats."""
    slots = sorted([s for s in cues.keys() if cues[s] is not None])
    if not slots:
        return None
    
    spacings = {}
    
    # Key spacings
    if 2 in cues and 3 in cues:  # cue3 -> cue4 gap
        spacings["cue3_to_cue4"] = int(cues[3] - cues[2]) if cues[2] is not None and cues[3] is not None else None
    if 4 in cues and 5 in cues:  # cue5 -> cue6 gap  
        spacings["cue5_to_cue6"] = int(cues[5] - cues[4]) if cues[4] is not None and cues[5] is not None else None
    if 3 in cues and 5 in cues:  # cue4 -> cue6 gap (drop to drop)
        spacings["cue4_to_cue6"] = int(cues[5] - cues[3]) if cues[3] is not None and cues[5] is not None else None
    
    # Total track coverage
    if slots:
        first_cue = min(cues[s] for s in slots if cues[s] is not None)
        last_cue = max(cues[s] for s in slots if cues[s] is not None)
        spacings["first_to_last"] = int(last_cue - first_cue)
    
    return spacings


def main():
    print("=" * 60)
    print("DnB HALF/DOUBLE-TIME ANALYSIS")
    print("=" * 60)
    
    # Load eval set
    gold_tracks = load_gold_csv(GOLD_CSV)
    
    # Load gold pool
    pool_csv = POOL_DIR / "gold_pool_clean.csv"
    audio_sel = POOL_DIR / "audio_sel.csv"
    pool = load_gold_pool(pool_csv, audio_sel)
    
    # Analyze by BPM band
    bands = {
        "bass (<80)": (0, 80),
        "dnb (80-100)": (80, 100),
        "midtempo (100-115)": (100, 115),
        "house (115+)": (115, 300),
    }
    
    # Collect spacing statistics
    spacing_stats = defaultdict(lambda: defaultdict(list))
    
    print("\n" + "=" * 60)
    print("EVAL SET ANALYSIS")
    print("=" * 60)
    
    for filename, track in gold_tracks.items():
        bpm = track.bpm
        band = None
        for b, (low, high) in bands.items():
            if low <= bpm < high:
                band = b
                break
        
        spacings = analyze_cue_spacing(track.cues, filename, bpm)
        
        if band == "dnb (80-100)":
            print(f"\n{filename} (BPM={bpm:.1f}):")
            print(f"  Cues: {dict(sorted(track.cues.items()))}")
            if spacings:
                print(f"  Spacings: {spacings}")
        
        if spacings and band:
            for key, val in spacings.items():
                if val is not None:
                    spacing_stats[band][key].append(val)
    
    # Print summary statistics
    print("\n" + "=" * 60)
    print("SPACING STATISTICS BY BPM BAND")
    print("=" * 60)
    
    for band in ["bass (<80)", "dnb (80-100)", "midtempo (100-115)", "house (115+)"]:
        print(f"\n{band}:")
        if band in spacing_stats:
            for key, vals in spacing_stats[band].items():
                if vals:
                    avg = sum(vals) / len(vals)
                    min_v = min(vals)
                    max_v = max(vals)
                    print(f"  {key}: avg={avg:.0f}, min={min_v}, max={max_v}")
    
    # Compare cue3->cue4 gap patterns
    print("\n" + "=" * 60)
    print("CUE3->CUE4 GAP COMPARISON")
    print("=" * 60)
    
    for band in ["dnb (80-100)", "house (115+)"]:
        if band in spacing_stats and "cue3_to_cue4" in spacing_stats[band]:
            vals = spacing_stats[band]["cue3_to_cue4"]
            gap_16 = sum(1 for v in vals if 14 <= v <= 18)
            gap_32 = sum(1 for v in vals if 30 <= v <= 34)
            print(f"\n{band}:")
            print(f"  16-beat gap: {gap_16}/{len(vals)}")
            print(f"  32-beat gap: {gap_32}/{len(vals)}")
            print(f"  Other: {len(vals) - gap_16 - gap_32}/{len(vals)}")
    
    # Check for double-time patterns
    print("\n" + "=" * 60)
    print("DOUBLE-TIME CHECK")
    print("=" * 60)
    print("\nIf DnB is labeled as 85 BPM but should be 170:")
    print("- 16 beats @ 85 BPM = 32 beats @ 170 BPM")
    print("- 32 beats @ 85 BPM = 64 beats @ 170 BPM")
    print("\nChecking if DnB spacings are 2x what they should be...")
    
    if "dnb (80-100)" in spacing_stats and "house (115+)" in spacing_stats:
        dnb_c4c6 = spacing_stats["dnb (80-100)"].get("cue4_to_cue6", [])
        house_c4c6 = spacing_stats["house (115+)"].get("cue4_to_cue6", [])
        
        if dnb_c4c6 and house_c4c6:
            dnb_avg = sum(dnb_c4c6) / len(dnb_c4c6)
            house_avg = sum(house_c4c6) / len(house_c4c6)
            print(f"\nCue4->Cue6 (drop to drop) average spacing:")
            print(f"  DnB: {dnb_avg:.0f} beats")
            print(f"  House: {house_avg:.0f} beats")
            print(f"  Ratio: {dnb_avg/house_avg:.2f}x")
            
            if dnb_avg < house_avg * 0.7:
                print("\n⚠️ DnB spacing is SHORTER than house - might be double-time labeled!")
            elif dnb_avg > house_avg * 1.3:
                print("\n⚠️ DnB spacing is LONGER than house - might be half-time labeled!")


if __name__ == "__main__":
    main()
