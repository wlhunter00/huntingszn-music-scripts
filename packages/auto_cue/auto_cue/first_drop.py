"""Audio-only first-drop context and track-balanced candidate ranking."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from auto_cue.ranker import FEATURE_NAMES, candidate_vector

if TYPE_CHECKING:
    from auto_cue.features import TrackFeatures

CONTEXT_NAMES = [
    "bass_gain16",
    "bass_gain32",
    "rms_gain16",
    "rms_gain32",
    "kick_gain16",
    "kick_gain32",
    "bass_level16",
    "bass_level32",
    "hold_next16",
    "preceding_break",
    "preceding_build",
    "pre_gap4",
    "distance_first_kick",
    "earlier_similar_count",
    "earlier_similar_fraction",
    "earlier_peak_relative",
    "centroid_gain16",
    "boundary_novelty",
    "bass_gain4",
]
FIRST_DROP_NAMES = FEATURE_NAMES + CONTEXT_NAMES


def first_drop_vectors(
    features: TrackFeatures,
    *,
    include_track_pct: bool,
) -> tuple[list[int], np.ndarray]:
    """Return candidate rows in original grid coordinates; never inspect cue labels."""
    beats = []
    bases = []
    for beat in dict.fromkeys(features.drop_candidates):
        vector = candidate_vector(features, beat, include_track_pct=include_track_pct)
        if vector is not None:
            beats.append(beat)
            bases.append(vector)
    audio = np.array(
        [
            [b.low_db, b.rms_db, b.kick_onset, b.spectral_centroid, b.novelty_score]
            for b in features.beat_features
        ],
        dtype=float,
    ).reshape(-1, 5)
    if not np.isfinite(audio).all():
        raise ValueError("Nonfinite audio in first-drop context")
    if not beats:
        return [], np.empty((0, len(FIRST_DROP_NAMES)))
    if not len(audio):
        return beats, np.column_stack([bases, np.zeros((len(beats), len(CONTEXT_NAMES)))])

    def mean(start, end):
        start, end = max(0, start), min(len(audio), end)
        return audio[start:end].mean(axis=0) if start < end else np.zeros(5)

    loud = float(np.percentile(audio[:, 0], 75))
    kick = float(np.median(audio[:, 2]))
    first_kick = next(
        (
            b
            for b in range(0, len(audio), 4)
            if mean(b, b + 4)[0] >= loud - 3 and mean(b, b + 4)[2] > kick
        ),
        0,
    )
    levels = {b: mean(b, b + 16)[0] for b in beats}
    rows = []
    for beat, base in zip(beats, bases):
        pre16, pre32 = mean(beat - 16, beat), mean(beat - 32, beat)
        post16, post32 = mean(beat, beat + 16), mean(beat, beat + 32)
        earlier = [b for b in beats if b <= beat - 16]
        similar = sum(levels[b] >= post16[0] - 3 for b in earlier)
        pre = audio[max(0, beat - 32) : beat]
        pre4 = audio[max(0, beat - 4) : beat]
        row = [
            post16[0] - pre16[0],
            post32[0] - pre32[0],
            post16[1] - pre16[1],
            post32[1] - pre32[1],
            post16[2] - pre16[2],
            post32[2] - pre32[2],
            post16[0] - loud,
            post32[0] - loud,
            mean(beat + 16, beat + 32)[0] - post16[0],
            pre32[0] - float(pre[:, 0].min()) if len(pre) else 0,
            (mean(beat - 8, beat)[3] - mean(beat - 16, beat - 8)[3]) / 1000,
            post16[1] - float(pre4[:, 1].min()) if len(pre4) else 0,
            (beat - first_kick) / 16,
            np.log1p(similar),
            similar / max(1, len(earlier)),
            max((levels[b] for b in earlier), default=post16[0]) - post16[0],
            (post16[3] - pre16[3]) / 1000,
            float(audio[min(beat, len(audio) - 1), 4]),
            mean(beat, beat + 4)[0] - mean(beat - 4, beat)[0],
        ]
        rows.append(np.concatenate([base, row]))
    return beats, np.asarray(rows)


def pair_vectors(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Comparison differences and absolute context, symmetric under track identity."""
    return np.concatenate([left - right, (left + right) / 2], axis=-1)


@dataclass
class FirstDropRanker:
    estimator: object
    pairwise: bool

    def predict_proba(self, vectors: np.ndarray) -> np.ndarray:
        if not self.pairwise:
            return self.estimator.predict_proba(vectors)
        n = len(vectors)
        if n < 2:
            return np.ones((n, 2)) * 0.5
        left, right = np.triu_indices(n, 1)
        forward = self.estimator.predict_proba(pair_vectors(vectors[left], vectors[right]))[:, 1]
        reverse = self.estimator.predict_proba(pair_vectors(vectors[right], vectors[left]))[:, 1]
        wins = (forward + 1 - reverse) / 2
        scores = np.zeros(n)
        np.add.at(scores, left, wins)
        np.add.at(scores, right, 1 - wins)
        scores /= n - 1
        return np.column_stack([1 - scores, scores])


@dataclass
class FrozenBoosting:
    """JSON tree inference without pickle or a runtime sklearn dependency."""

    trees: list[dict]
    log_odds: float
    learning_rate: float
    n_features: int

    def predict_proba(self, vectors):
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[1] != self.n_features:
            raise ValueError("First-drop model feature width mismatch")
        if not np.isfinite(vectors).all():
            raise ValueError("Nonfinite first-drop model input")
        score = np.full(len(vectors), self.log_odds)
        for tree in self.trees:
            left, right = np.array(tree["left"]), np.array(tree["right"])
            feature, threshold = np.array(tree["feature"]), np.array(tree["threshold"])
            nodes = np.zeros(len(vectors), dtype=int)
            while len(active := np.flatnonzero(left[nodes] >= 0)):
                current = nodes[active]
                nodes[active] = np.where(
                    vectors[active, feature[current]] <= threshold[current],
                    left[current],
                    right[current],
                )
            score += self.learning_rate * np.array(tree["value"])[nodes]
        probability = 1 / (1 + np.exp(-np.clip(score, -700, 700)))
        return np.column_stack([1 - probability, probability])


def save_first_drop_ranker(model: FirstDropRanker, path: Path) -> None:
    estimator = model.estimator
    prior = estimator.init_.class_prior_
    trees = []
    for fitted in estimator.estimators_[:, 0]:
        tree = fitted.tree_
        trees.append(
            dict(
                left=tree.children_left.tolist(),
                right=tree.children_right.tolist(),
                feature=tree.feature.tolist(),
                threshold=tree.threshold.tolist(),
                value=tree.value[:, 0, 0].tolist(),
            )
        )
    payload = dict(
        format="auto-cue-first-drop-v1",
        feature_names=FIRST_DROP_NAMES,
        pairwise=model.pairwise,
        n_features=int(estimator.n_features_in_),
        log_odds=float(np.log(prior[1] / prior[0])),
        learning_rate=float(estimator.learning_rate),
        trees=trees,
    )
    path.write_text(json.dumps(payload, allow_nan=False))


def load_first_drop_ranker(path: Path) -> FirstDropRanker:
    payload = json.loads(path.read_text())

    def require(condition):
        if not condition:
            raise ValueError("Invalid first-drop model JSON")

    try:
        require(payload["format"] == "auto-cue-first-drop-v1")
        require(payload["feature_names"] == FIRST_DROP_NAMES)
        require(type(payload["pairwise"]) is bool)
        width = len(FIRST_DROP_NAMES) * (2 if payload["pairwise"] else 1)
        require(payload["n_features"] == width)
        require(np.isfinite(payload["log_odds"]))
        require(np.isfinite(payload["learning_rate"]) and payload["learning_rate"] > 0)
        require(payload["trees"])
        for tree in payload["trees"]:
            n = len(tree["left"])
            require(
                n and all(len(tree[k]) == n for k in ("right", "feature", "threshold", "value"))
            )
            require(np.isfinite(tree["threshold"]).all() and np.isfinite(tree["value"]).all())
            for i, (left, right, feature) in enumerate(
                zip(tree["left"], tree["right"], tree["feature"])
            ):
                require(type(left) is int and type(right) is int and type(feature) is int)
                require(
                    (left == right == -1)
                    or (i < left < n and i < right < n and 0 <= feature < width)
                )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid first-drop model JSON") from exc
    return FirstDropRanker(
        FrozenBoosting(payload["trees"], payload["log_odds"], payload["learning_rate"], width),
        payload["pairwise"],
    )


def fit_first_drop_ranker(groups, *, pairwise: bool = False) -> FirstDropRanker | None:
    """Fit only supplied training groups: (candidate matrix, binary gold labels)."""
    xs, ys, weights = [], [], []
    for vectors, labels in groups:
        if not len(vectors):
            continue
        if pairwise:
            good, bad = np.flatnonzero(labels), np.flatnonzero(1 - labels)
            if not len(good) or not len(bad):
                continue
            positive, negative = np.meshgrid(good, bad, indexing="ij")
            positive, negative = positive.ravel(), negative.ravel()
            comparisons = pair_vectors(vectors[positive], vectors[negative])
            opposite = pair_vectors(vectors[negative], vectors[positive])
            xs.extend([comparisons, opposite])
            ys.extend([np.ones(len(comparisons)), np.zeros(len(comparisons))])
            weights.extend([np.full(len(comparisons), 1 / len(comparisons))] * 2)
        else:
            xs.append(vectors)
            ys.append(labels)
            weights.append(np.full(len(labels), 1 / len(labels)))
    if not xs or len(np.unique(np.concatenate(ys))) < 2:
        return None
    from sklearn.ensemble import GradientBoostingClassifier

    model = GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=42)
    model.fit(np.vstack(xs), np.concatenate(ys), sample_weight=np.concatenate(weights))
    return FirstDropRanker(model, pairwise)


def ranked_first_drops(model, features: TrackFeatures, *, include_track_pct: bool = True):
    beats, vectors = first_drop_vectors(features, include_track_pct=include_track_pct)
    if model is None or not beats:
        return []
    scores = model.predict_proba(vectors)[:, 1]
    return sorted(zip(beats, scores.tolist()), key=lambda item: (-item[1], item[0]))


def format_first_drop_shortlist(
    features: TrackFeatures, ranking, *, limit: int | None = None,
) -> str:
    """Render scored first-drop candidates without changing cue-six context."""
    if limit is not None and limit <= 0:
        raise ValueError("Shortlist limit must be positive")
    beats, vectors = first_drop_vectors(features, include_track_pct=True)
    context = dict(zip(beats, vectors))
    seen = set()
    candidates = []
    for beat, score in sorted(ranking, key=lambda item: (-item[1], item[0])):
        if beat not in context or not np.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("Invalid first-drop ranking")
        if beat not in seen:
            candidates.append((beat, score))
            seen.add(beat)
    lines = [
        f"Cue 4 shortlist ({'all candidates' if limit is None else f'top {limit}'}, "
        "ranker ordered; scores are not LLM confidence):",
        "beat | score | bass gain16 | bass gain32 | bass vs loud | earlier similar",
    ]
    for beat, score in candidates[:limit]:
        row = context[beat]
        offset = len(FEATURE_NAMES)
        earlier = int(round(np.expm1(row[offset + CONTEXT_NAMES.index("earlier_similar_count")])))
        lines.append(
            f"{beat} | {score:.3f} | {row[offset]:+.1f} | {row[offset + 1]:+.1f} | "
            f"{row[offset + 6]:+.1f} | {earlier}"
        )
    lines.append(
        "For cue 6, independently inspect the full phrase table; this shortlist is cue 4 only."
    )
    return "\n".join(lines)
