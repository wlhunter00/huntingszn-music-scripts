"""Flag wiring, outputs, fallbacks, and cleanup — separator is faked."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import soundfile as sf
from _audio import FRAMES, SR, rms, write_separator_stem, write_wav
from stem_split.models import (
    CROWD_MODELS,
    DENOISE_MODELS,
    DEREVERB_MODELS,
    KARAOKE_MODELS,
    VOCAL_BS_MODEL,
    VOCAL_MEL_MODEL,
)
from stem_split.pipeline import (
    StemSplitOptions,
    _delete_separator_wavs,
    _mix_minus_vocals,
    _run_separator,
    clean_partial_state,
    process_audio_folder,
)

KEEP_BY_MODEL = {
    VOCAL_BS_MODEL: (("Vocals", 0.5), ("Instrumental", 0.2)),
    VOCAL_MEL_MODEL: (("Vocals", 0.3), ("Other", 0.1)),
    DEREVERB_MODELS[0]: (("noreverb", 0.4), ("reverb", 0.9)),
    DEREVERB_MODELS[1]: (("noreverb", 0.41), ("reverb", 0.91)),
    DEREVERB_MODELS[2]: (("Reverb", 0.95), ("No Reverb", 0.42)),
    DENOISE_MODELS[0]: (("other", 0.8), ("dry", 0.35)),
    DENOISE_MODELS[1]: (("Vocals", 0.88), ("Instrumental", 0.33)),
    DENOISE_MODELS[2]: (("Noise", 0.99), ("No Noise", 0.34)),
    KARAOKE_MODELS[0]: (("Instrumental", 0.7), ("Vocals", 0.55)),
    KARAOKE_MODELS[1]: (("Instrumental", 0.71), ("Vocals", 0.56)),
    CROWD_MODELS[0]: (("crowd", 0.85), ("other", 0.38)),
    "htdemucs_ft.yaml": (("Vocals", 0.01), ("Drums", 0.2), ("Bass", 0.15), ("Other", 0.12)),
    "bs_roformer_vocals_resurrection_unwa.ckpt": (("Vocals", 0.6), ("Instrumental", 0.25)),
    "mel_band_roformer_kim_ft2_bleedless_unwa.ckpt": (("Vocals", 0.58), ("Other", 0.22)),
    "BS-Roformer-SW.ckpt": (
        ("Vocals", 0.62),
        ("Drums", 0.1),
        ("Bass", 0.1),
        ("Guitar", 0.1),
        ("Piano", 0.1),
        ("Other", 0.05),
    ),
}


class FakeSeparator:
    def __init__(self, fail_models: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_models = set(fail_models or ())

    def __call__(self, cmd_tool, input_path, model, sep_dir, extra_args=()) -> None:
        self.calls.append((str(input_path), model))
        if model in self.fail_models:
            raise subprocess.CalledProcessError(1, list(cmd_tool) + ["-m", model])
        stems = KEEP_BY_MODEL.get(model)
        if stems is None:
            raise FileNotFoundError(f"test fake has no layout for {model}")
        base = Path(input_path).stem
        # Write residual-like tokens first so order cannot leak into keep-stem choice.
        for token, value in stems:
            write_separator_stem(Path(sep_dir), base, token, model, value=value)


@pytest.fixture
def fake_separator(monkeypatch: pytest.MonkeyPatch) -> FakeSeparator:
    fake = FakeSeparator()
    monkeypatch.setattr("stem_split.pipeline._run_separator", fake)
    monkeypatch.setattr("stem_split.pipeline._separator_cmd", lambda: ["audio-separator"])
    return fake


def _prepare_job(tmp_path: Path) -> tuple[Path, Path, Path]:
    inp = tmp_path / "songs-to-split"
    out = tmp_path / "stem-output"
    inp.mkdir()
    song = write_wav(inp / "Artist - Title.wav", value=0.4)
    return inp, out, song


def _song_dir(out: Path) -> Path:
    return out / "htdemucs_ft" / "Artist - Title"


class TestProcessAudioFolder:
    def test_default_writes_wet_stems_only(
        self, tmp_path: Path, fake_separator: FakeSeparator
    ) -> None:
        inp, out, song = _prepare_job(tmp_path)
        process_audio_folder(str(inp), str(out))
        dest = _song_dir(out)
        title = "Title"
        assert (dest / f"{title}_vocals.wav").exists()
        assert (dest / f"{title}_no_vocals.wav").exists()
        assert not (dest / f"{title}_vocals_dry.wav").exists()
        assert not (dest / f"{title}_vocals_lead.wav").exists()
        assert (dest / f"{title}_drums.wav").exists()
        assert (dest / f"{title}_drums_2.wav").exists()
        assert (dest / f"{title}_bass.wav").exists()
        assert (dest / f"{title}_other.wav").exists()
        assert (dest / "original_Artist - Title.wav").exists()
        assert not song.exists()
        models = [m for _, m in fake_separator.calls]
        assert models[:2] == [VOCAL_BS_MODEL, VOCAL_MEL_MODEL]
        assert "htdemucs_ft.yaml" in models
        assert DEREVERB_MODELS[0] not in models
        leftover = list(dest.glob("*_(*)_*.wav"))
        assert leftover == []

    def test_dry_karaoke_crowd_outputs(self, tmp_path: Path, fake_separator: FakeSeparator) -> None:
        inp, out, _ = _prepare_job(tmp_path)
        process_audio_folder(
            str(inp),
            str(out),
            options=StemSplitOptions(dry_vocals=True, karaoke=True, crowd=True),
        )
        dest = _song_dir(out)
        title = "Title"
        wet = dest / f"{title}_vocals.wav"
        dry = dest / f"{title}_vocals_dry.wav"
        lead = dest / f"{title}_vocals_lead.wav"
        assert wet.exists() and dry.exists() and lead.exists()
        # Wet vocals stay the ensemble, not overwritten by the dry chain.
        assert rms(wet) != pytest.approx(rms(dry), abs=0.01)
        assert not (dest / f"{title}_mix_nocrowd.wav").exists()
        assert not (dest / f"{title}_vocals_dereverb.wav").exists()
        models = [m for _, m in fake_separator.calls]
        assert CROWD_MODELS[0] in models
        assert DEREVERB_MODELS[0] in models
        assert DENOISE_MODELS[0] in models
        assert KARAOKE_MODELS[0] in models
        # Crowd runs before vocals; Demucs still runs on the original mix path.
        assert models[0] == CROWD_MODELS[0]
        assert models[-1] == "htdemucs_ft.yaml"
        demucs_inputs = [p for p, m in fake_separator.calls if m == "htdemucs_ft.yaml"]
        crowd_inputs = [p for p, m in fake_separator.calls if m == CROWD_MODELS[0]]
        vocal_inputs = [p for p, m in fake_separator.calls if m == VOCAL_BS_MODEL]
        assert Path(crowd_inputs[0]).name == Path(demucs_inputs[0]).name
        vocal_name = Path(vocal_inputs[0]).name
        demucs_name = Path(demucs_inputs[0]).name
        assert "nocrowd" in vocal_name or vocal_name != demucs_name

    def test_vocal_model_override(self, tmp_path: Path, fake_separator: FakeSeparator) -> None:
        inp, out, _ = _prepare_job(tmp_path)
        process_audio_folder(
            str(inp),
            str(out),
            options=StemSplitOptions(
                vocal_models=(
                    "bs_roformer_vocals_resurrection_unwa.ckpt",
                    "mel_band_roformer_kim_ft2_bleedless_unwa.ckpt",
                )
            ),
        )
        models = [m for _, m in fake_separator.calls]
        assert models[:2] == [
            "bs_roformer_vocals_resurrection_unwa.ckpt",
            "mel_band_roformer_kim_ft2_bleedless_unwa.ckpt",
        ]
        assert VOCAL_BS_MODEL not in models

    def test_dry_fallback_when_roformer_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeSeparator(fail_models={DEREVERB_MODELS[0], DENOISE_MODELS[0]})
        monkeypatch.setattr("stem_split.pipeline._run_separator", fake)
        monkeypatch.setattr("stem_split.pipeline._separator_cmd", lambda: ["audio-separator"])
        inp, out, _ = _prepare_job(tmp_path)
        process_audio_folder(str(inp), str(out), options=StemSplitOptions(dry_vocals=True))
        models = [m for _, m in fake.calls]
        assert DEREVERB_MODELS[0] in models
        assert DEREVERB_MODELS[1] in models
        assert DENOISE_MODELS[0] in models
        assert DENOISE_MODELS[1] in models
        dest = _song_dir(out)
        assert (dest / "Title_vocals_dry.wav").exists()
        assert (dest / "Title_vocals.wav").exists()

    def test_sw_mix_minus_vocals(self, tmp_path: Path, fake_separator: FakeSeparator) -> None:
        inp, out, _ = _prepare_job(tmp_path)
        process_audio_folder(
            str(inp),
            str(out),
            options=StemSplitOptions(vocal_models=("BS-Roformer-SW.ckpt",)),
        )
        dest = _song_dir(out)
        assert (dest / "Title_vocals.wav").exists()
        assert (dest / "Title_no_vocals.wav").exists()

    def test_sw_mix_minus_48k_source(self, tmp_path: Path, fake_separator: FakeSeparator) -> None:
        inp = tmp_path / "songs-to-split"
        out = tmp_path / "stem-output"
        inp.mkdir()
        write_wav(inp / "Artist - Title.wav", value=0.4, frames=480, sr=48000)
        process_audio_folder(
            str(inp),
            str(out),
            options=StemSplitOptions(vocal_models=("BS-Roformer-SW.ckpt",)),
        )
        dest = _song_dir(out)
        info = sf.info(dest / "Title_no_vocals.wav")
        assert info.samplerate == SR
        assert info.subtype == "PCM_24"

    def test_failure_leaves_original_and_cleans(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_a, **_k):
            raise RuntimeError("separator exploded")

        monkeypatch.setattr("stem_split.pipeline._run_separator", boom)
        monkeypatch.setattr("stem_split.pipeline._separator_cmd", lambda: ["audio-separator"])
        inp, out, song = _prepare_job(tmp_path)
        write_separator_stem(
            _song_dir(out), "Title", "Reverb", "UVR-DeEcho-DeReverb.pth", value=0.9
        )
        process_audio_folder(str(inp), str(out), options=StemSplitOptions(dry_vocals=True))
        assert song.exists()
        dest = _song_dir(out)
        assert list(dest.glob("*_(*)_*.wav")) == []
        assert not (dest / "Title_vocals.wav").exists()
        assert not (dest / "original_Artist - Title.wav").exists()


class TestCleanPartialState:
    def test_removes_new_outputs_and_residuals(self, tmp_path: Path) -> None:
        dest = tmp_path / "song"
        dest.mkdir()
        title = "Title"
        for sfx in (
            "_vocals.wav",
            "_vocals_dry.wav",
            "_vocals_lead.wav",
            "_mix_nocrowd.wav",
            "_vocals_dereverb.wav",
            "_drums.wav",
        ):
            write_wav(dest / f"{title}{sfx}")
        write_separator_stem(dest, "mix", "Reverb", "UVR-DeEcho-DeReverb.pth")
        write_separator_stem(dest, "mix", "Noise", "UVR-DeNoise.pth")
        write_separator_stem(dest, "mix", "crowd", CROWD_MODELS[0])
        write_wav(dest / "original_Artist - Title.wav")
        clean_partial_state(dest, title)
        assert (dest / "original_Artist - Title.wav").exists()
        assert not (dest / f"{title}_vocals_dry.wav").exists()
        assert not (dest / f"{title}_vocals_lead.wav").exists()
        assert not (dest / f"{title}_mix_nocrowd.wav").exists()
        assert not (dest / f"{title}_vocals_dereverb.wav").exists()
        assert list(dest.glob("*_(*)_*.wav")) == []

    def test_preserves_archived_original_with_reverb_in_name(self, tmp_path: Path) -> None:
        dest = tmp_path / "song"
        dest.mkdir()
        archived = dest / "original_Artist - Club _(Reverb)_ Mix.wav"
        write_wav(archived, value=0.5)
        write_separator_stem(dest, "mix", "Reverb", "UVR-DeEcho-DeReverb.pth", value=0.9)
        clean_partial_state(dest, "Club _(Reverb)_ Mix")
        assert archived.exists()
        leftover = [
            p for p in dest.glob("*_(*)_*.wav") if not p.name.startswith("original_")
        ]
        assert leftover == []


def test_delete_separator_wavs_skips_archived_original(tmp_path: Path) -> None:
    archived = tmp_path / "original_Artist - Club _(Reverb)_ Mix.wav"
    write_wav(archived, value=0.5)
    write_separator_stem(tmp_path, "mix", "Reverb", "UVR-DeEcho-DeReverb.pth", value=0.9)
    _delete_separator_wavs(tmp_path)
    assert archived.exists()
    leftover = [p for p in tmp_path.glob("*_(*)_*.wav") if not p.name.startswith("original_")]
    assert leftover == []


def test_mix_minus_vocals_resamples_48k_mix(tmp_path: Path) -> None:
    mix = write_wav(tmp_path / "mix.wav", value=0.4, frames=480, sr=48000)
    vocals = write_wav(tmp_path / "vocals.wav", value=0.1, frames=FRAMES, sr=SR)
    dest = tmp_path / "no_vocals.wav"
    _mix_minus_vocals(mix, vocals, dest)
    info = sf.info(dest)
    assert info.samplerate == SR
    assert info.subtype == "PCM_24"
    assert abs(info.frames - FRAMES) <= 2


def test_run_separator_invokes_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorded = {}

    def fake_run(argv, check):
        recorded["argv"] = argv
        recorded["check"] = check

    monkeypatch.setattr(subprocess, "run", fake_run)
    _run_separator(["audio-separator"], "in.wav", VOCAL_BS_MODEL, tmp_path)
    assert recorded["argv"][:4] == ["audio-separator", "in.wav", "-m", VOCAL_BS_MODEL]
    assert "--output_format" in recorded["argv"]
    assert recorded["check"] is True
