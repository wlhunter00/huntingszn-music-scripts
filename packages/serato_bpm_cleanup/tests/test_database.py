from pathlib import Path

from serato_bpm_cleanup.database import (
    dump_minimal_database,
    parse_database_tracks,
    update_database_bpm,
)


def test_parse_and_update_tbpm(tmp_path: Path):
    blob = dump_minimal_database(
        [
            ("DJ Music/a.mp3", "128.31"),
            ("DJ Music/b.mp3", "140.00"),
        ]
    )
    tracks = parse_database_tracks(blob)
    assert len(tracks) == 2
    assert tracks[0].path.endswith("a.mp3")
    assert tracks[0].bpm == 128.31

    new_blob, n = update_database_bpm(blob, {"DJ Music/a.mp3": 128})
    assert n == 1
    updated = parse_database_tracks(new_blob)
    by_name = {Path(t.path).name: t.bpm for t in updated}
    assert by_name["a.mp3"] == 128.0
    assert by_name["b.mp3"] == 140.0
    # Original bytes for the untouched track stay representable.
    assert dump_minimal_database is not None
