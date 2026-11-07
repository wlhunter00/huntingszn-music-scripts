from pathlib import Path

import numpy as np
import pytest
from auto_cue.features import BeatFeatures, PhraseFeatures, TrackFeatures
from auto_cue.last_drop import (
    LAST_DROP_NAMES,
    apply_last_drop_ranker,
    filter_last_drop,
    last_drop_context,
    last_drop_vectors,
)
from auto_cue.ranker import FEATURE_NAMES


def track():
    beats = []
    for i in range(192):
        low, rms, kick = -30, -30, 0
        if 64 <= i < 96:
            low, rms, kick = -6, -8, 1
        elif 128 <= i < 144:
            low, rms, kick = -8, -9, .8
        beats.append(BeatFeatures(i, low_db=low, rms_db=rms, kick_onset=kick))
    features = TrackFeatures(Path('x'), 120, 0, 192, 96, beat_features=beats,
                             drop_candidates=[64, 80, 96, 128, 144, 160])
    features.phrases_16 = [PhraseFeatures(b, b + 16, 16) for b in features.drop_candidates]
    return features


def test_last_drop_context_counts_later_windows_and_decline():
    context = last_drop_context(track())
    vector = context[64]['vector']
    assert len(vector) == len(LAST_DROP_NAMES)
    assert vector[0] == 2
    assert vector[1] == 4
    assert vector[2] < 0 and vector[3] < 0 and vector[4] < 0
    assert context[64]['strong']
    assert not context[64]['last_full']
    assert context[128]['last_full']
    assert context[128]['outro']
    assert context[96]['outro']


def test_feature_vectors_preserve_candidates_and_pct_ablation():
    features = track()
    beats, matrix = last_drop_vectors(features, include_track_pct=True)
    other_beats, ablated = last_drop_vectors(features, include_track_pct=False)
    assert beats == other_beats == [96, 128, 144, 160]
    assert matrix.shape == (4, len(FEATURE_NAMES) + len(LAST_DROP_NAMES))
    assert np.all(ablated[:, FEATURE_NAMES.index('track_pct')] == 0)
    assert matrix[0, FEATURE_NAMES.index('track_pct')] == .5
    np.testing.assert_array_equal(matrix[:, len(FEATURE_NAMES):], ablated[:, len(FEATURE_NAMES):])


def test_empty_silent_and_nonfinite_audio():
    features = track()
    features.beat_features = []
    assert last_drop_context(features) == {}
    features.phrases_16 = []
    beats, vectors = last_drop_vectors(features, include_track_pct=True)
    assert not beats and vectors.size == 0
    features = track()
    for beat in features.beat_features:
        beat.kick_onset = 0
    assert not any(c['strong'] for c in last_drop_context(features).values())
    features.beat_features[20].low_db = np.nan
    with pytest.raises(ValueError, match='Nonfinite'):
        last_drop_context(features)


def test_fixed_filters_preserve_cue4_and_missing_predictions():
    features = track()
    ranking = [(160, .8), (128, .7), (64, .6)]
    assert filter_last_drop(features, (32, 160), ranking, rule='last_full') == (32, 128)
    assert filter_last_drop(features, (32, 160), ranking, rule='outro_filter') == (32, 64)
    assert filter_last_drop(features, (32, None), ranking, rule='last_full') == (32, None)
    with pytest.raises(ValueError, match='Unknown'):
        filter_last_drop(features, (32, 160), ranking, rule='unknown')


def test_feature_ranker_gate_order_abstention_and_build_prior():
    features = track()
    assert apply_last_drop_ranker(features, (64, 160), [(128, .7)], llm_beat=160) == (64, 128)
    assert apply_last_drop_ranker(features, (64, 160), [(128, .2)], llm_beat=160) == (64, 160)
    assert apply_last_drop_ranker(features, (64, 160), [(128, .2)],
                                  llm_beat=160, ranker_only=True) == (64, 128)
    assert apply_last_drop_ranker(features, (128, 160), [(96, .9)], llm_beat=160) == (128, 160)
    assert apply_last_drop_ranker(features, (128, 160), [(128, .2)], llm_beat=64) == (128, 160)
    assert apply_last_drop_ranker(features, (64, None), [(128, .9)], llm_beat=128) == (64, None)
    assert apply_last_drop_ranker(features, (64, 160), [], llm_beat=128) == (64, 160)
    assert apply_last_drop_ranker(features, (64, 160), [(96, .9), (128, .8)],
                                  llm_beat=160, build32=True) == (64, 128)


@pytest.mark.parametrize('ranking', [[(999, .5)], [(128, float('nan'))], [(128, 2)]])
def test_invalid_feature_ranking_fails_closed(ranking):
    with pytest.raises(ValueError, match='Invalid'):
        apply_last_drop_ranker(track(), (64, 160), ranking, llm_beat=128)
