import shutil
from types import SimpleNamespace

import httpx
import pytest
from auto_cue import cli, llm
from auto_cue.tags import beats_to_ms, write_track_beatgrid
from serato_bpm_cleanup.beatgrid import BeatGrid, TerminalMarker

from tests.test_write_safety import chunk


def test_zero_offset_grid_converts_beats():
    grid = BeatGrid(markers=(TerminalMarker(position_s=0.0, bpm=120.0),))
    assert beats_to_ms(0, grid) == 0
    assert beats_to_ms(32, grid) == 16000


@pytest.mark.parametrize("grid", [BeatGrid(markers=()),
    BeatGrid(markers=(TerminalMarker(position_s=float("nan"), bpm=120.0),)),
    BeatGrid(markers=(TerminalMarker(position_s=0.0, bpm=0.0),)),
    BeatGrid(markers=(TerminalMarker(position_s=0.0, bpm=float("inf")),)),
])
def test_invalid_grid_rejected(grid):
    with pytest.raises(ValueError, match="missing or invalid"):
        beats_to_ms(32, grid)


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


def test_missing_key_aborts_before_processing(tmp_path, monkeypatch, capsys):
    (tmp_path / "track.mp3").touch()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "process_track", lambda *a, **kw: pytest.fail("must not process"))
    assert cli.main(["--library", str(tmp_path)]) == 3
    assert "OPENAI_API_KEY environment variable not set; batch aborted" in capsys.readouterr().err


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
    assert cli.main(["--library", str(sample_mp3.parent)]) == 3
    assert len(extracted) == (1 if fatal else 2)
    assert ("batch aborted" in capsys.readouterr().err) == fatal


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
