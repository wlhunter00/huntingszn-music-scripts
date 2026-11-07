import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from auto_cue.baseline_analysis import predictions
from auto_cue.features import BeatFeatures, PhraseFeatures, TrackFeatures
from auto_cue.ranker import apply_build_prior, has_32beat_build


def track():
    beats = [BeatFeatures(i, low_db=-30 if 32 <= i < 64 else -10,
                          rms_db=-30 if 32 <= i < 64 else -10) for i in range(128)]
    return TrackFeatures(Path('x'), 120, 0, 128, 64,
                         beat_features=beats, drop_candidates=[32, 64, 96])


def test_build_requires_bass_and_rms_and_complete_context():
    features = track()
    assert has_32beat_build(features, 32) is False
    assert has_32beat_build(features, 64) is True
    assert has_32beat_build(features, 96) is False
    assert has_32beat_build(features, None) is None
    assert has_32beat_build(features, 16) is None
    assert has_32beat_build(features, 120) is None
    features.beat_features[64].rms_db = -1000
    assert has_32beat_build(features, 64) is False


def test_filter_preserves_supported_picks_and_order():
    features = track()
    rankings = ([32, 64], [96, 64])
    assert apply_build_prior(features, (32, 96), rankings) == (64, 64)
    assert apply_build_prior(features, (64, 96), rankings) == (64, 64)
    assert apply_build_prior(features, (32, 32), rankings) == (32, 64)
    assert apply_build_prior(features, (16, 96), ([], [])) == (16, 96)
    assert apply_build_prior(features, (None, None), rankings) == (None, None)


def test_empty_and_nonfinite_build_audio():
    features = track()
    features.beat_features = []
    assert apply_build_prior(features, (32, 96), ([64], [64])) == (32, 96)
    features = track()
    features.beat_features[40].low_db = np.nan
    with pytest.raises(ValueError, match='Nonfinite'):
        has_32beat_build(features, 64)


@pytest.fixture
def evaluator(monkeypatch):
    pytest.importorskip('sklearn')
    monkeypatch.setenv('OPENAI_API_KEY', 'offline-unit-test')
    path = Path(__file__).resolve().parents[3] / 'eval_kfold.py'
    spec = importlib.util.spec_from_file_location('structure_test_eval', path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def packet():
    result = dict(llm4=32, llm6=96, llm4_conf=.9, llm6_conf=.9)
    for mode in ('pct', 'nopct'):
        for cue, beat in ((4, 32), (6, 96)):
            result[f'rank_{mode}{cue}'] = beat
            result[f'rank_{mode}{cue}_p'] = .8
    return result


def test_eval_variants_replay_without_overwriting_raw_predictions(evaluator):
    row = packet()
    row['build32_predictions'] = {'combined_pct_build32': (64, 64)}
    report = evaluator.Report()
    evaluator.record_methods(report, 'house (115+)', 64, 64, row)
    assert report.by_method['combined_pct']['all']['cue4'].correct == 0
    after = report.by_method['combined_pct_build32']['all']
    assert after['cue4'].correct == after['cue6'].correct == 1
    assert after['cue4'].emitted == after['cue6'].emitted == 0
    assert predictions(row)['combined_pct_build32'] == (64, 64)
    assert predictions(row)['llm'] == (32, 96)


def test_predict_track_adds_all_fixed_gate_variants_without_api(evaluator, monkeypatch):
    row = packet()
    prediction = SimpleNamespace(
        cue4_beat=32, cue6_beat=96, cue4=SimpleNamespace(confidence=.9),
        cue6=SimpleNamespace(confidence=.9), cost_usd=0,
    )
    monkeypatch.setattr(evaluator, 'get_pool_fewshot_examples', lambda *a, **k: [])
    monkeypatch.setattr(evaluator, 'predict_cues_llm', lambda *a, **k: prediction)
    monkeypatch.setattr(evaluator, 'rank_candidates', lambda model, f, cue, include:
                        [(32, .8), (64, .2)] if cue == 'cue4' else [(96, .8), (64, .2)])
    models = {f'cue{cue}_{mode}': None for cue in (4, 6) for mode in ('pct', 'nopct')}
    result = evaluator.predict_track(SimpleNamespace(bpm=120, bpm_band='house (115+)',
                                                     small_file='x'), track(),
                                     SimpleNamespace(tracks={}), {}, set(), models)
    assert result['llm4'] == row['llm4']
    assert len(result['build32_predictions']) == 5
    assert all(pair == (64, 64) for pair in result['build32_predictions'].values())
    assert len(result['lastdrop_predictions']) == 10
    assert all(pair[0] == predictions(result)[m.removesuffix('_lastdrop')][0]
               for m, pair in result['lastdrop_predictions'].items())


def test_lastdrop_variants_replay_without_changing_cue4(evaluator):
    row = packet()
    row['build32_predictions'] = {'combined_pct_build32': (64, 96)}
    row['lastdrop_predictions'] = {'combined_pct_build32_lastdrop': (64, 64)}
    report = evaluator.Report()
    evaluator.record_methods(report, 'house (115+)', 64, 64, row)
    after = report.by_method['combined_pct_build32_lastdrop']['all']
    assert after['cue4'].correct == after['cue6'].correct == 1
    assert after['cue6'].emitted == 0
    assert predictions(row)['combined_pct_build32_lastdrop'] == (64, 64)


def test_lastdrop_training_and_empty_ranking(evaluator):
    features = track()
    features.phrases_16 = [PhraseFeatures(b, b + 16, 16) for b in features.drop_candidates]
    tracks = [SimpleNamespace(path='x', cues={3: 32, 5: 64})]
    models = evaluator.train_fold_models(tracks, {'x': features})
    assert models['cue6_lastdrop_pct'] is not None
    assert evaluator.rank_last_drop(None, features, True) == []
    assert evaluator.rank_last_drop(models['cue6_lastdrop_pct'], features, True)
