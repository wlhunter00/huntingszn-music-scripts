import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from auto_cue import cli, llm
from auto_cue.features import (
    BeatFeatures,
    TrackFeatures,
    format_phrase_table,
    populate_phrase_features,
)
from auto_cue.first_drop import (
    CONTEXT_NAMES,
    FIRST_DROP_NAMES,
    FirstDropRanker,
    first_drop_vectors,
    fit_first_drop_ranker,
    format_first_drop_shortlist,
    load_first_drop_ranker,
    ranked_first_drops,
    save_first_drop_ranker,
)
from auto_cue.ranker import FEATURE_NAMES


def track():
    beats = [
        BeatFeatures(
            i,
            low_db=-10 if i % 64 >= 32 else -30,
            rms_db=-8 if i % 64 >= 32 else -20,
            kick_onset=1 if i % 64 >= 32 else 0,
            novelty_score=1 if i % 32 == 0 else 0,
        )
        for i in range(256)
    ]
    features = TrackFeatures(Path("audio"), 120, 0, 256, 128, beat_features=beats)
    populate_phrase_features(features)
    return features


def test_context_measures_immediate_entry_and_earlier_similar_energy():
    features = track()
    beats, vectors = first_drop_vectors(features, include_track_pct=True)
    row = vectors[beats.index(32)]
    start = len(FEATURE_NAMES)
    assert len(row) == len(FIRST_DROP_NAMES)
    assert row[start + CONTEXT_NAMES.index("bass_gain16")] == 20
    assert row[start + CONTEXT_NAMES.index("bass_gain32")] == 20
    assert row[start + CONTEXT_NAMES.index("bass_level16")] == 0
    later = vectors[beats.index(96)]
    assert later[start + CONTEXT_NAMES.index("earlier_similar_count")] > 0
    ablated = first_drop_vectors(features, include_track_pct=False)[1]
    assert np.all(ablated[:, FEATURE_NAMES.index("track_pct")] == 0)
    np.testing.assert_array_equal(vectors[:, start:], ablated[:, start:])


def test_empty_and_nonfinite_context():
    features = TrackFeatures(Path("empty"), 120, 0, 0, 0)
    beats, vectors = first_drop_vectors(features, include_track_pct=True)
    assert beats == [] and vectors.shape == (0, len(FIRST_DROP_NAMES))
    assert ranked_first_drops(None, features) == []
    features = track()
    features.beat_features[40].low_db = float("nan")
    with pytest.raises(ValueError, match="Nonfinite"):
        first_drop_vectors(features, include_track_pct=True)


class ComparisonModel:
    def predict_proba(self, vectors):
        scores = 1 / (1 + np.exp(-vectors[:, 0]))
        return np.column_stack([1 - scores, scores])


def test_pairwise_scores_are_order_equivariant_and_singleton_safe():
    model = FirstDropRanker(ComparisonModel(), True)
    x = np.array([[3.0], [1.0], [2.0]])
    p = model.predict_proba(x)
    assert p[0, 1] > p[2, 1] > p[1, 1]
    np.testing.assert_allclose(p.sum(axis=1), 1)
    np.testing.assert_allclose(model.predict_proba(x[::-1]), p[::-1])
    np.testing.assert_allclose(model.predict_proba(x[:1]), [[0.5, 0.5]])


def test_fixed_budget_shortlist_uses_scores_and_original_coordinates():
    features = track()
    beats = features.drop_candidates[:7]
    ranking = [(b, 0.1 * (i + 1)) for i, b in enumerate(beats)]
    rendered = format_first_drop_shortlist(features, ranking, limit=5)
    assert f"{beats[-1]} | 0.700" in rendered
    assert f"{beats[0]} | 0.100" not in rendered
    assert len([s for s in rendered.splitlines() if s[:1].isdigit()]) == 5
    table = format_phrase_table(features, first_drop_ranking=ranking)
    assert "ranker ordered" in table
    assert "Alternate phase candidates:" not in table
    assert "independently inspect the full phrase table" in table
    assert format_first_drop_shortlist(features, [])


def test_default_prompt_includes_every_scored_candidate_in_rank_order():
    features = track()
    ranking = [(b, (i + 1) / 100) for i, b in enumerate(features.drop_candidates)]
    rendered = format_phrase_table(features, first_drop_ranking=ranking)
    rows = rendered.split('beat | score | bass gain16')[1].splitlines()
    beats = [int(row.split(' | ')[0]) for row in rows if row[:1].isdigit()]
    assert beats == list(reversed(features.drop_candidates))
    assert 'all candidates, ranker ordered' in rendered


@pytest.mark.parametrize("ranking", [[(9999, 0.5)], [(32, float("nan"))], [(32, 1.5)]])
def test_shortlist_rejects_invalid_rankings(ranking):
    with pytest.raises(ValueError, match="Invalid"):
        format_first_drop_shortlist(track(), ranking)


def test_shortlist_rejects_invalid_budget():
    with pytest.raises(ValueError, match="positive"):
        format_first_drop_shortlist(track(), [], limit=0)


def test_degenerate_training_groups_abstain_without_estimator():
    assert fit_first_drop_ranker([]) is None
    assert fit_first_drop_ranker([(np.ones((2, 3)), np.zeros(2))]) is None
    assert fit_first_drop_ranker([(np.ones((2, 3)), np.ones(2))], pairwise=True) is None


def fake_estimator():
    tree = SimpleNamespace(
        children_left=np.array([1, -1, -1]),
        children_right=np.array([2, -1, -1]),
        feature=np.array([0, -2, -2]),
        threshold=np.array([0, -2, -2]),
        value=np.array([0, -2, 2]).reshape(3, 1, 1),
    )
    return SimpleNamespace(
        init_=SimpleNamespace(class_prior_=np.array([0.5, 0.5])),
        estimators_=np.array([[SimpleNamespace(tree_=tree)]]),
        n_features_in_=len(FIRST_DROP_NAMES),
        learning_rate=1,
    )


def test_json_model_round_trip_and_input_validation(tmp_path):
    path = tmp_path / "model.json"
    save_first_drop_ranker(FirstDropRanker(fake_estimator(), False), path)
    model = load_first_drop_ranker(path)
    x = np.zeros((2, len(FIRST_DROP_NAMES)))
    x[:, 0] = [-1, 1]
    np.testing.assert_allclose(model.predict_proba(x)[:, 1], 1 / (1 + np.exp([2, -2])))
    with pytest.raises(ValueError, match="width"):
        model.predict_proba(np.zeros((1, 2)))
    x[0, 0] = np.nan
    with pytest.raises(ValueError, match="Nonfinite"):
        model.predict_proba(x)


@pytest.mark.parametrize("invalid", ["schema", "cycle", "missing", "nan"])
def test_invalid_json_model_is_rejected(tmp_path, invalid):
    path = tmp_path / "model.json"
    save_first_drop_ranker(FirstDropRanker(fake_estimator(), False), path)
    data = json.loads(path.read_text())
    if invalid == "schema":
        data["feature_names"] = []
    if invalid == "cycle":
        data["trees"][0]["left"][0] = 0
    if invalid == "missing":
        del data["trees"][0]["value"]
    if invalid == "nan":
        data["learning_rate"] = float("nan")
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Invalid"):
        load_first_drop_ranker(path)


def test_cli_rejects_invalid_model_without_prediction(tmp_path, capsys):
    assert (
        cli.main(
            [
                "--file",
                str(tmp_path / "audio.mp3"),
                "--first-drop-model",
                str(tmp_path / "missing.json"),
            ]
        )
        == 2
    )
    assert "cannot load first-drop model" in capsys.readouterr().err


def test_cli_passes_loaded_ranker_to_processing(sample_mp3, monkeypatch):
    model = object()
    monkeypatch.setattr(cli, "load_first_drop_ranker", lambda path: model)
    seen = []

    def process(path, **kwargs):
        seen.append(kwargs["first_drop_model"])
        return cli.ProcessResult(path=path, action="would-write")

    monkeypatch.setattr(cli, "process_track", process)
    assert cli.main(["--file", str(sample_mp3), "--first-drop-model", "model.json"]) == 0
    assert seen == [model]


def test_llm_receives_ranked_shortlist_with_mock_api(monkeypatch):
    features = track()
    ranking = [(b, 0.9 - i * 0.05) for i, b in enumerate(features.drop_candidates[:7])]
    payloads = []

    def post(*args, **kwargs):
        payloads.append(kwargs["json"])
        content = {f"cue{i}_beat": None for i in range(1, 9)}
        content.update({f"cue{i}_confidence": 0.1 for i in range(1, 9)})
        content["rationale"] = "uncertain"
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://example.invalid"),
            json={"choices": [{"message": {"content": json.dumps(content)}}]},
        )

    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")
    monkeypatch.setattr(llm.httpx.Client, "post", post)
    result = llm.predict_cues_llm(features, first_drop_ranking=ranking)
    assert result.cue4_beat is None
    prompt = payloads[0]["messages"][-1]["content"]
    assert "Cue 4 shortlist (all candidates" in prompt
    assert "Alternate phase candidates:" not in prompt
