"""CLI flag defaults and wiring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from stem_split.__main__ import build_parser, main
from stem_split.models import VOCAL_BS_MODEL, VOCAL_MEL_MODEL
from stem_split.pipeline import StemSplitOptions


def test_flags_default_off() -> None:
    args = build_parser().parse_args([])
    assert args.dry_vocals is False
    assert args.karaoke is False
    assert args.crowd is False
    assert args.vocal_models is None
    assert args.list_vocal_models is False


def test_flags_parse() -> None:
    args = build_parser().parse_args(
        [
            "--dry-vocals",
            "--karaoke",
            "--crowd",
            "--vocal-models",
            "resurrection,kim-ft2-bleedless",
            "--input",
            "/tmp/in",
            "--output",
            "/tmp/out",
        ]
    )
    assert args.dry_vocals is True
    assert args.karaoke is True
    assert args.crowd is True
    assert args.vocal_models == "resurrection,kim-ft2-bleedless"


def test_main_passes_options() -> None:
    captured: dict = {}

    def fake_process(inp, out, options=None):
        captured["input"] = inp
        captured["output"] = out
        captured["options"] = options

    with patch("stem_split.__main__.process_audio_folder", fake_process):
        main(
            [
                "--dry-vocals",
                "--karaoke",
                "--input",
                "/tmp/in",
                "--output",
                "/tmp/out",
            ]
        )
    opts: StemSplitOptions = captured["options"]
    assert captured["input"] == str(Path("/tmp/in"))
    assert opts.dry_vocals is True
    assert opts.karaoke is True
    assert opts.crowd is False
    assert opts.vocal_models == (VOCAL_BS_MODEL, VOCAL_MEL_MODEL)


def test_list_vocal_models_does_not_run(capsys) -> None:
    with patch("stem_split.__main__.process_audio_folder") as proc:
        main(["--list-vocal-models"])
        proc.assert_not_called()
    out = capsys.readouterr().out
    assert "viperx" in out
    assert VOCAL_BS_MODEL in out
    assert "resurrection" in out
