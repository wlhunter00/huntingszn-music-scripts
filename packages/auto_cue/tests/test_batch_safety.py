import csv
import shutil
from types import SimpleNamespace

import httpx
import pytest
from auto_cue import cli, llm
from auto_cue.tags import CuePoint, Markers2Data, beats_to_ms, cues_to_beats, write_track_beatgrid
from serato_bpm_cleanup.beatgrid import BeatGrid, TerminalMarker

from tests.test_write_safety import chunk


def test_zero_offset_grid_converts_beats():
    grid = BeatGrid(markers=(TerminalMarker(position_s=0.0, bpm=120.0),))
    assert beats_to_ms(0, grid) == 0
    assert beats_to_ms(32, grid) == 16000
    markers = Markers2Data(cues=[CuePoint(index=3, position_ms=16000)])
    assert cues_to_beats(markers, grid) == {3: 32}
    assert cues_to_beats(Markers2Data(), grid) == {}


def test_negative_grid_offset_converts_valid_cue_positions():
    grid = BeatGrid(markers=(TerminalMarker(position_s=-0.25, bpm=120.0),))
    assert beats_to_ms(1, grid) == 250
    assert cues_to_beats(Markers2Data(cues=[CuePoint(index=3, position_ms=250)]), grid) == {3: 1}
    for beat in [0, float("nan"), float("inf")]:
        with pytest.raises(ValueError, match="cue position"):
            beats_to_ms(beat, grid)


@pytest.mark.parametrize("grid", [BeatGrid(markers=()),
    BeatGrid(markers=(TerminalMarker(position_s=float("nan"), bpm=120.0),)),
    BeatGrid(markers=(TerminalMarker(position_s=0.0, bpm=0.0),)),
    BeatGrid(markers=(TerminalMarker(position_s=0.0, bpm=float("inf")),)),
])
def test_invalid_grid_rejected(grid):
    with pytest.raises(ValueError, match="missing or invalid"):
        beats_to_ms(32, grid)
    assert cues_to_beats(Markers2Data(cues=[CuePoint(index=3, position_ms=1000)]), grid) == {}


@pytest.mark.parametrize("mode", ["valid", "empty", "missing", "malformed"])
def test_crate_filters_before_processing(tmp_path, monkeypatch, capsys, mode):
    library = tmp_path / "DJ Music"
    library.mkdir()
    for name in ["Cafe\u0301.mp3", "other.mp3"]:
        (library / name).touch()
    serato = tmp_path / "_Serato_"
    subcrates = serato / "Subcrates"
    subcrates.mkdir(parents=True)
    crate = subcrates / "Favorites%%House.crate"
    if mode == "valid":
        member = "DJ Music/Café.mp3".encode("utf-16-be")
        crate.write_bytes(chunk(b"otrk", chunk(b"ptrk", member)))
    elif mode == "empty":
        crate.write_bytes(b"")
    elif mode == "malformed":
        crate.write_bytes(b"otrk")
    processed = []

    def process(path, **kwargs):
        processed.append(path)
        return cli.ProcessResult(path=path, action="would-write")

    monkeypatch.setattr(cli, "process_track", process)
    result = cli.main(["--library", str(library), "--crate", "Favorites/House", "--no-llm"])
    if mode in ("missing", "malformed"):
        assert result == 1
        assert "Cannot safely filter requested crate" in capsys.readouterr().err
    else:
        assert result == 0
    assert [p.name for p in processed] == (["Cafe\u0301.mp3"] if mode == "valid" else [])


def test_missing_key_does_not_abort_skipped_tracks(sample_mp3, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "extract_features", lambda *a: pytest.fail("must not extract"))
    assert cli.main(["--file", str(sample_mp3)]) == 0
    output = capsys.readouterr()
    assert "Summary: 1 files processed" in output.out
    assert "batch aborted" not in output.err


@pytest.mark.parametrize("scan", ["library", "subfolder", "file"])
@pytest.mark.parametrize("absolute", [False, True])
def test_crate_matching_uses_volume_root(tmp_path, monkeypatch, scan, absolute):
    volume = tmp_path / "volume"
    folder = volume / "DJ Music" / "House"
    folder.mkdir(parents=True)
    track = folder / "track.mp3"
    track.touch()
    subcrates = volume / "_Serato_" / "Subcrates"
    subcrates.mkdir(parents=True)
    member = track.as_posix() if absolute else "DJ Music/House/track.mp3"
    (subcrates / "House.crate").write_bytes(
        chunk(b"otrk", chunk(b"ptrk", member.encode("utf-16-be")))
    )
    processed = []

    def process(path, **kwargs):
        processed.append(path)
        return cli.ProcessResult(path=path, action="would-write")

    monkeypatch.setattr(cli, "process_track", process)
    option, root = {
        "library": ("--library", volume / "DJ Music"),
        "subfolder": ("--library", folder),
        "file": ("--file", track),
    }[scan]
    assert cli.main([option, str(root), "--crate", "House", "--no-llm"]) == 0
    assert processed == [track]


@pytest.mark.parametrize("member_type", ["relative", "absolute", "windows"])
def test_crate_does_not_match_another_volume(tmp_path, monkeypatch, member_type):
    volume = tmp_path / "volume-a"
    other = tmp_path / "volume-b" / "DJ Music"
    other.mkdir(parents=True)
    track = other / "track.mp3"
    track.touch()
    serato = volume / "_Serato_"
    (serato / "Subcrates").mkdir(parents=True)
    member = {
        "relative": "DJ Music/track.mp3",
        "absolute": (volume / "DJ Music" / "track.mp3").as_posix(),
        "windows": "E:/DJ Music/track.mp3",
    }[member_type]
    (serato / "Subcrates" / "House.crate").write_bytes(
        chunk(b"otrk", chunk(b"ptrk", member.encode("utf-16-be")))
    )
    monkeypatch.setattr(cli, "process_track", lambda *a, **kw: pytest.fail("wrong volume"))
    assert cli.main([
        "--file", str(track), "--db", str(serato / "database V2"),
        "--crate", "House", "--no-llm",
    ]) == 0


@pytest.mark.parametrize("ambiguous", [False, True])
def test_crate_requires_unambiguous_volume_root(tmp_path, monkeypatch, capsys, ambiguous):
    folder = tmp_path / "DJ Music" / "House"
    folder.mkdir(parents=True)
    track = folder / "track.mp3"
    track.touch()
    if ambiguous:
        (tmp_path / "_Serato_").mkdir()
        (folder.parent / "_Serato_").mkdir()
    monkeypatch.setattr(cli, "process_track", lambda *a, **kw: pytest.fail("ambiguous root"))
    assert cli.main(["--file", str(track), "--crate", "House", "--no-llm"]) == 1
    assert "unambiguous volume root" in capsys.readouterr().err


def test_fatal_auth_exports_accumulated_results(tmp_path, monkeypatch, capsys):
    paths = [tmp_path / f"{i}.mp3" for i in range(3)]
    monkeypatch.setattr(cli, "iter_audio_files", lambda root: paths)
    processed = []

    def process(path, **kwargs):
        processed.append(path)
        fatal = len(processed) == 2
        return cli.ProcessResult(
            path=path, action="error-api" if fatal else "would-write",
            error="authentication failed" if fatal else None,
            is_api_error=fatal, fatal_api_error=fatal,
        )

    monkeypatch.setattr(cli, "process_track", process)
    destination = tmp_path / "results.csv"
    assert cli.main(["--library", str(tmp_path), "--csv", str(destination)]) == 3
    assert processed == paths[:2]
    assert "Summary: 2 files processed" in capsys.readouterr().out
    with destination.open() as source:
        rows = list(csv.DictReader(source))
    assert [row["action"] for row in rows] == ["would-write", "error-api"]


def test_missing_key_aborts_only_when_prediction_needed(sample_mp3, monkeypatch, tmp_path, capsys):
    write_track_beatgrid(sample_mp3, BeatGrid(markers=(TerminalMarker(0.0, 128.0),)))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "extract_features", lambda *a: SimpleNamespace(
        total_beats=256, bpm=128.0, first_beat_s=0.0,
    ))
    monkeypatch.setattr(llm, "format_phrase_table", lambda *a: "features")
    destination = tmp_path / "results.csv"
    assert cli.main(["--file", str(sample_mp3), "--csv", str(destination)]) == 3
    output = capsys.readouterr()
    assert "OPENAI_API_KEY environment variable not set; batch aborted" in output.err
    assert "Summary: 1 files processed" in output.out
    with destination.open() as source:
        assert len(list(csv.DictReader(source))) == 1


@pytest.mark.parametrize("fatal", [True, False])
def test_auth_failure_aborts_but_transient_error_continues(
    sample_mp3, tmp_path, monkeypatch, capsys, fatal,
):
    second = sample_mp3.with_name("second.mp3")
    shutil.copy2(sample_mp3, second)
    for path in [sample_mp3, second]:
        write_track_beatgrid(path, BeatGrid(markers=(TerminalMarker(0.0, 128.0),)))
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    extracted = []

    def extract(path, *args):
        extracted.append(path)
        return SimpleNamespace(total_beats=256)

    def predict(*args, **kwargs):
        error = llm.LLMAuthError if fatal else llm.LLMAPIError
        raise error("authentication failed" if fatal else "rate limited")

    monkeypatch.setattr(cli, "extract_features", extract)
    monkeypatch.setattr(cli, "predict_cues_llm", predict)
    destination = tmp_path / "results.csv"
    assert cli.main(["--library", str(sample_mp3.parent), "--csv", str(destination)]) == 3
    assert len(extracted) == (1 if fatal else 2)
    output = capsys.readouterr()
    assert ("batch aborted" in output.err) == fatal
    assert f"Summary: {len(extracted)} files processed" in output.out
    with destination.open() as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == len(extracted)
    assert all(row["error"] for row in rows)


@pytest.mark.parametrize("status", [401, 403, 429])
def test_http_auth_errors_are_fatal(monkeypatch, status):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setattr(llm, "format_phrase_table", lambda *a: "features")

    def post(*args, **kwargs):
        return httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com"))

    monkeypatch.setattr(llm.httpx.Client, "post", post)
    features = SimpleNamespace(bpm=128.0, first_beat_s=0.0, total_beats=256)
    with pytest.raises(llm.LLMAPIError) as error:
        llm.predict_cues_llm(features)
    assert isinstance(error.value, llm.LLMAuthError) == (status in (401, 403))
