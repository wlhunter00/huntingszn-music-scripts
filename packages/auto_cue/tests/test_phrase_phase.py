from pathlib import Path

import numpy as np
import pytest
from auto_cue import baseline
from auto_cue.calibrated_confidence import compute_cue_confidence_signals
from auto_cue.features import (
    BeatFeatures,
    PhraseFeatures,
    TrackFeatures,
    _aggregate_phrases,
    _identify_drop_candidates,
    estimate_phrase_phase,
    format_phrase_table,
    populate_phrase_features,
)
from auto_cue.llm import CueConfidence, LLMPrediction, prediction_to_cue_set
from auto_cue.ranker import FEATURE_NAMES, candidate_vector, phrase_at_beat
from auto_cue.tags import CuePoint, Markers2Data, beats_to_ms, cues_to_beats
from auto_cue.validate import validate_cue_set
from serato_bpm_cleanup.beatgrid import BeatGrid, TerminalMarker


def beats_with_phase(phase, n=256):
    return [BeatFeatures(
        beat=i, low_db=-8 if (i - phase) % 32 < 16 else -30,
        rms_db=-6 if (i - phase) % 32 < 16 else -20,
        kick_onset=2 if (i - phase) % 32 < 16 else 0,
    ) for i in range(n)]


@pytest.mark.parametrize('cue1,cue2,expected', [
    (0, 0, (12, 12)), (-20, -10, (12, 12)),
    (100, 100, (44, 44)), (100, 28, (28, 28)),
    (100, None, (44, None)), (None, None, (None, None)),
])
def test_shifted_intro_snapping_stays_on_lattice_and_validates(cue1, cue2, expected):
    prediction = LLMPrediction(
        cue1=CueConfidence(cue1, 1), cue2=CueConfidence(cue2, 1),
        cue4=CueConfidence(76, 1), cue6=CueConfidence(172, 1),
        cue7=CueConfidence(None, 0), cue8=CueConfidence(None, 0),
        cue7_midsong=False, rationale='',
    )
    cues = prediction_to_cue_set(prediction, 256)
    assert (cues.cue1, cues.cue2) == expected
    assert validate_cue_set(cues).valid


@pytest.mark.parametrize('phase', [0, 4, 8, 12])
def test_estimates_phase_from_audio_energy_changes(phase):
    estimated, support = estimate_phrase_phase(beats_with_phase(phase))
    assert estimated == phase
    assert len(support) == 4 and support[phase // 4] == 1


@pytest.mark.parametrize('n', [0, 1, 16, 31, 64])
def test_phase_empty_short_silent_fallback(n):
    assert estimate_phrase_phase([BeatFeatures(i) for i in range(n)]) == (0, [0.0] * 4)


def test_phase_rejects_nonfinite_audio():
    beats = [BeatFeatures(i) for i in range(64)]
    beats[20].low_db = float('nan')
    with pytest.raises(ValueError, match='Nonfinite'):
        estimate_phrase_phase(beats)


@pytest.mark.parametrize('size', [8, 16, 32])
def test_aggregation_retains_grid_coordinates_and_complete_windows(size):
    beats = beats_with_phase(4, 101)
    phrases = _aggregate_phrases(beats, size, 101, 4)
    assert [p.beat_start for p in phrases] == list(range(4, 102 - size, size))
    assert all(p.beat_end == p.beat_start + size <= 101 for p in phrases)
    assert all(p.track_pct == p.beat_start / 101 for p in phrases)
    assert phrases[0].low_db == pytest.approx(np.mean([b.low_db for b in beats[4:4 + size]]))


@pytest.mark.parametrize('size,phase', [(0, 0), (16, -1), (16, 16)])
def test_invalid_aggregation_phase(size, phase):
    with pytest.raises(ValueError):
        _aggregate_phrases([], size, 0, phase)


def test_shifted_candidates_prompt_ranker_and_coordinate_round_trip():
    beats = beats_with_phase(4)
    track = TrackFeatures(Path('audio.mp3'), 120, 0.25, len(beats), 128, beat_features=beats)
    legacy = TrackFeatures(track.path, track.bpm, track.first_beat_s, len(beats), 128)
    for size in (8, 16, 32):
        setattr(legacy, f'phrases_{size}', _aggregate_phrases(beats, size, len(beats)))
    _identify_drop_candidates(legacy)
    populate_phrase_features(track)
    assert track.phrase_phase == 4
    assert track.drop_candidates[:5] == legacy.drop_candidates[:5]
    assert set(legacy.drop_candidates) <= set(track.drop_candidates)
    assert len(track.drop_candidates) == len(set(track.drop_candidates))
    shifted = [b for b in track.drop_candidates if b % 16 == 4]
    assert shifted
    table = format_phrase_table(track)
    assert 'Audio phrase phase: 4 mod 16' in table
    assert f'Alternate phase candidates: {track.drop_candidates[5:]}' in table
    assert all(f'{b:4d} |' in table for b in shifted)
    for beat in shifted:
        phrase = phrase_at_beat(track, beat)
        assert phrase is not None
        vector = candidate_vector(track, beat, include_track_pct=True)
        assert len(vector) == len(FEATURE_NAMES)
        assert vector[FEATURE_NAMES.index('track_pct')] == beat / track.total_beats
        assert vector[-1] == track.phase_support[1]
        ablated = candidate_vector(track, beat, include_track_pct=False)
        assert ablated[FEATURE_NAMES.index('track_pct')] == 0
        grid = BeatGrid(markers=[TerminalMarker(position_s=0.25, bpm=120)])
        ms = beats_to_ms(beat, grid)
        recovered = cues_to_beats(Markers2Data(cues=[CuePoint(index=3, position_ms=ms)]), grid)
        assert recovered[3] == pytest.approx(beat)
    starts_32 = {p.beat_start for p in track.phrases_32}
    for beat in shifted:
        if beat in starts_32:
            assert phrase_at_beat(track, beat).phrase_size == 32


def test_rebuild_is_idempotent_and_unscorable_candidate_is_missing():
    track = TrackFeatures(Path('x'), 120, 0, 256, 128, beat_features=beats_with_phase(8))
    populate_phrase_features(track)
    before = (track.phrase_phase, list(track.drop_candidates))
    populate_phrase_features(track)
    assert before == (track.phrase_phase, track.drop_candidates)
    assert candidate_vector(track, 9999, include_track_pct=True) is None


def test_incomplete_32beat_tail_does_not_change_legacy_shortlist():
    track = TrackFeatures(Path('x'), 120, 0, 80, 40, beat_features=beats_with_phase(0, 80))
    for size in (16, 32):
        setattr(track, f'phrases_{size}', _aggregate_phrases(track.beat_features, size, 80))
    _identify_drop_candidates(track)
    tail = next(p for p in track.phrases_16 if p.beat_start == 64)
    assert not tail.is_drop_candidate
    assert tail.drop_score == 0


def test_feature_cache_invalidates_legacy_phrase_features(tmp_path):
    audio = tmp_path / 'audio.mp3'
    audio.write_bytes(b'audio')
    current = baseline.feature_cache_path(tmp_path, audio, 120, 0)
    legacy = tmp_path / current.name.removeprefix('phrase-phase-v1-')
    assert current != legacy
    assert current.name.startswith('phrase-phase-v1-')


@pytest.mark.parametrize('slot', [4, 6])
@pytest.mark.parametrize('phase', [0, 4, 8, 12])
def test_confidence_uses_candidate_phase_not_overlapping_zero_window(slot, phase):
    beat = 96 + phase
    track = TrackFeatures(Path('x'), 120, 0, 192, 96, phrase_phase=0)
    for size in (8, 16, 32):
        wrong = PhraseFeatures(beat - 4, beat - 4 + size, size)
        right = PhraseFeatures(beat, beat + size, size, delta_kick=0.5,
                               delta_low=10, drop_score=4, is_drop_candidate=True)
        setattr(track, f'phrases_{size}', [wrong, right])
    track.drop_candidates = [beat]
    signals = compute_cue_confidence_signals(track, beat, slot)
    assert signals.kick_slam_strength == 1
    assert signals.zoom_agreement == 1
    assert signals.on_lattice
    assert 'off-lattice' not in signals.abstain_reasons
    assert 'weak kick slam (0.00)' not in signals.abstain_reasons
    assert signals.calibrated_confidence > 0.9


def test_confidence_missing_and_unrepresented_off_phase_predictions():
    track = TrackFeatures(Path('x'), 120, 0, 192, 96, phrase_phase=4)
    missing = compute_cue_confidence_signals(track, None, 4)
    assert missing.calibrated_confidence == 0
    signals = compute_cue_confidence_signals(track, 37, 4)
    assert signals.kick_slam_strength == 0
    assert signals.zoom_agreement == 0
    assert not signals.on_lattice
    assert 'off-lattice' in signals.abstain_reasons


@pytest.mark.parametrize('has_own_window', [False, True])
def test_zoom_does_not_credit_previous_32beat_section(has_own_window):
    track = TrackFeatures(Path('x'), 120, 0, 192, 96)
    track.phrases_16 = [PhraseFeatures(116, 132, 16)]
    track.phrases_32 = [PhraseFeatures(
        100, 132, 32, drop_score=4, is_drop_candidate=True,
    )]
    if has_own_window:
        track.phrases_32.append(PhraseFeatures(
            116, 148, 32, drop_score=4, is_drop_candidate=True,
        ))
    signals = compute_cue_confidence_signals(track, 116, 4)
    assert signals.zoom_agreement == (0.5 if has_own_window else 0)


@pytest.mark.parametrize('beat,on_outro_lattice', [(100, True), (116, False), (132, True)])
def test_cue6_checks_32beat_lattice_of_candidate_phase(beat, on_outro_lattice):
    track = TrackFeatures(Path('x'), 120, 0, 192, 96, phrase_phase=0)
    track.phrases_16 = [PhraseFeatures(b, b + 16, 16) for b in (100, 116, 132)]
    track.phrases_32 = [PhraseFeatures(b, b + 32, 32) for b in (100, 132)]
    track.drop_candidates = [beat]
    intro = compute_cue_confidence_signals(track, beat, 4)
    outro = compute_cue_confidence_signals(track, beat, 6)
    assert intro.on_lattice
    assert outro.on_lattice == on_outro_lattice
    assert ('off-lattice' in outro.abstain_reasons) == (not on_outro_lattice)


@pytest.mark.parametrize('phase', [0, 4])
@pytest.mark.parametrize('slot', [4, 6])
def test_kick_slam_uses_16beat_onset_when_32beat_average_is_weak(phase, slot):
    beat = 96 + phase
    track = TrackFeatures(Path('x'), 120, 0, 192, 96, phrase_phase=phase)
    track.phrases_16 = [PhraseFeatures(beat, beat + 16, 16, delta_kick=0.5, delta_low=10)]
    track.phrases_32 = [PhraseFeatures(beat, beat + 32, 32, delta_kick=0, delta_low=0)]
    track.drop_candidates = [beat]
    signals = compute_cue_confidence_signals(track, beat, slot)
    assert signals.kick_slam_strength == 1
    assert not any(reason.startswith('weak kick slam') for reason in signals.abstain_reasons)
