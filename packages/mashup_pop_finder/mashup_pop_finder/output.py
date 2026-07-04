"""Rich-table + CSV output."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from rich.console import Console
from rich.table import Table

from mashup_pop_finder.models import MatchResult, SongMeta

_COLUMNS = ("rank", "title", "artist", "key", "bpm", "ratio", "match_type")


def print_table(
    base: SongMeta, matches: Iterable[MatchResult], console: Console | None = None
) -> None:
    console = console or Console()
    table = Table(
        title=f"Matches for {base.title} — {base.artist} "
        f"(key={base.key or '?'}, bpm={base.bpm or '?'})",
        show_lines=False,
    )
    for col in _COLUMNS:
        table.add_column(col, overflow="fold")
    for rank, m in enumerate(matches, start=1):
        table.add_row(
            str(rank),
            m.candidate.title,
            m.candidate.artist,
            m.key or "",
            f"{m.bpm:g}",
            f"{m.ratio:.3f}",
            m.match_type,
        )
    console.print(table)


def write_csv(path: Path, base: SongMeta, matches: Iterable[MatchResult]) -> int:
    """Write rows to CSV. Returns number of data rows written."""
    matches_list = list(matches)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(_COLUMNS)
        for rank, m in enumerate(matches_list, start=1):
            writer.writerow(
                [
                    rank,
                    m.candidate.title,
                    m.candidate.artist,
                    m.key or "",
                    f"{m.bpm:g}",
                    f"{m.ratio:.6f}",
                    m.match_type,
                ]
            )
    return len(matches_list)
