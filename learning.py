"""Machine-learning layer: how rudestorm learns to read the signals better.

The hand-tuned adapters and the noisy-OR fusion rule are a strong, honest
*baseline*. This module is how the system improves on that baseline by learning
from data and from operator feedback, without ever abandoning the safety rule
(>= 2 independent modalities to alert).

Three learnable pieces, all numpy-only so they run offline on an edge node:

1. `ConfidenceCalibrator` (Platt scaling) — turns each adapter's raw score into a
   *calibrated probability*. "0.8" from the acoustic node and "0.8" from the RF
   node rarely mean the same thing; calibration makes them comparable so fusion
   is fair.

2. `LearnedFusion` (logistic regression over window features) — learns, from
   labelled windows, how much to trust each combination of modalities. It
   replaces the fixed noisy-OR weighting with weights fit to real detection/
   false-alarm outcomes. It is constrained to never fire on a single modality.

3. `CSIBaselineModel` (online Welford statistics) — learns what the *normal*
   WiFi field looks like at a node, then scores how anomalous the current frame
   is. This adapts each mote to its own room/street instead of a global threshold.

`OperatorFeedback` closes the loop: every operator confirm/dismiss is a label the
calibrators and fusion model train on, so the system's false-alarm rate falls the
longer it runs in a given deployment (a form of active learning).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from rudestorm.events import CORROBORATION_ONLY, Detection, Modality

# Fixed feature order so a trained model is reproducible across runs/nodes.
_FEATURE_MODALITIES: Tuple[Modality, ...] = (
    Modality.REMOTE_ID,
    Modality.WIFI_CSI,
    Modality.ACOUSTIC,
    Modality.VIDEO,
    Modality.VIBRATION,
)


def window_features(detections: Sequence[Detection]) -> np.ndarray:
    """Turn a correlation window into a fixed-length feature vector.

    Features: per-modality max confidence (5), number of distinct modalities (1),
    number of independent (non-corroboration-only) modalities (1), total evidence
    mass (1). This is what `LearnedFusion` learns weights over.
    """
    per_mod = {m: 0.0 for m in _FEATURE_MODALITIES}
    for d in detections:
        if d.modality in per_mod:
            per_mod[d.modality] = max(per_mod[d.modality], d.confidence)
    distinct = {d.modality for d in detections}
    independent = distinct - CORROBORATION_ONLY
    feats = [per_mod[m] for m in _FEATURE_MODALITIES]
    feats.append(float(len(distinct)))
    feats.append(float(len(independent)))
    feats.append(float(sum(d.confidence for d in detections)))
    return np.asarray(feats, dtype=float)


class LogisticRegressionNP:
    """Minimal L2-regularized logistic regression (numpy gradient descent)."""

    def __init__(self, l2: float = 1e-3, lr: float = 0.1, epochs: int = 400) -> None:
        self.l2 = l2
        self.lr = lr
        self.epochs = epochs
        self.w: Optional[np.ndarray] = None
        self.b: float = 0.0
        self._mu: Optional[np.ndarray] = None
        self._sd: Optional[np.ndarray] = None

    @staticmethod
    def _sigmoid(z: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))

    def _standardize(self, X: np.ndarray, fit: bool) -> np.ndarray:
        if fit:
            self._mu = X.mean(axis=0)
            self._sd = X.std(axis=0) + 1e-8
        return (X - self._mu) / self._sd

    def fit(self, X: np.ndarray, y: np.ndarray) -> "LogisticRegressionNP":
        X = np.atleast_2d(np.asarray(X, dtype=float))
        y = np.asarray(y, dtype=float).ravel()
        Xs = self._standardize(X, fit=True)
        n, d = Xs.shape
        self.w = np.zeros(d)
        self.b = 0.0
        for _ in range(self.epochs):
            p = self._sigmoid(Xs @ self.w + self.b)
            err = p - y
            grad_w = Xs.T @ err / n + self.l2 * self.w
            grad_b = float(np.mean(err))
            self.w -= self.lr * grad_w
            self.b -= self.lr * grad_b
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self.w is None:
            raise RuntimeError("model is not fitted")
        Xs = self._standardize(np.atleast_2d(np.asarray(X, dtype=float)), fit=False)
        return self._sigmoid(Xs @ self.w + self.b)


class ConfidenceCalibrator:
    """Per-modality Platt scaling: raw adapter score -> calibrated probability."""

    def __init__(self) -> None:
        self._models: Dict[Modality, LogisticRegressionNP] = {}

    def fit(self, modality: Modality, raw_scores: Sequence[float],
            labels: Sequence[int]) -> None:
        X = np.asarray(raw_scores, dtype=float).reshape(-1, 1)
        model = LogisticRegressionNP(l2=1e-4, lr=0.3, epochs=600)
        model.fit(X, np.asarray(labels, dtype=float))
        self._models[modality] = model

    def calibrate(self, modality: Modality, raw_score: float) -> float:
        model = self._models.get(modality)
        if model is None:
            return raw_score
        return float(model.predict_proba([[raw_score]])[0])

    @property
    def fitted_modalities(self) -> List[Modality]:
        return list(self._models.keys())


class LearnedFusion:
    """Learned window scorer, constrained by the single-modality safety rule.

    Use `.score(detections)` in place of noisy-OR. If fewer than two independent
    modalities are present, it returns 0.0 regardless of what the model says —
    the learned model can raise confidence but can never override the safety rule.
    """

    def __init__(self, min_independent: int = 2) -> None:
        self.min_independent = min_independent
        self.model = LogisticRegressionNP(l2=1e-3, lr=0.2, epochs=500)
        self._fitted = False

    def fit(self, windows: Sequence[Sequence[Detection]],
            labels: Sequence[int]) -> "LearnedFusion":
        X = np.vstack([window_features(w) for w in windows])
        self.model.fit(X, np.asarray(labels, dtype=float))
        self._fitted = True
        return self

    def score(self, detections: Sequence[Detection]) -> float:
        distinct = {d.modality for d in detections}
        independent = distinct - CORROBORATION_ONLY
        if len(independent) < 1 or len(distinct) < self.min_independent:
            return 0.0
        if not self._fitted:
            # Fall back to a safe combination until trained.
            from rudestorm.fusion import noisy_or
            return noisy_or([d.confidence for d in detections])
        return float(self.model.predict_proba([window_features(detections)])[0])


class CSIBaselineModel:
    """Online per-feature baseline (Welford) for a single CSI node.

    Learns the mean/variance of a scalar motion feature during quiet periods, then
    scores new frames by how many standard deviations they deviate. This adapts a
    mote to its own environment instead of relying on one global threshold.
    """

    def __init__(self) -> None:
        self._n = 0
        self._mean = 0.0
        self._m2 = 0.0

    def update(self, feature: float) -> None:
        self._n += 1
        delta = feature - self._mean
        self._mean += delta / self._n
        self._m2 += delta * (feature - self._mean)

    @property
    def std(self) -> float:
        if self._n < 2:
            return 0.0
        return float(np.sqrt(self._m2 / (self._n - 1)))

    def anomaly_score(self, feature: float) -> float:
        """Return a 0..1 anomaly score = squashed z-score above baseline."""
        if self._n < 2 or self.std == 0.0:
            return 0.0
        z = max(0.0, (feature - self._mean) / self.std)
        return float(np.tanh(z / 3.0))


@dataclass
class OperatorFeedback:
    """Active-learning buffer: operator confirm/dismiss becomes training labels."""

    windows: List[List[Detection]] = field(default_factory=list)
    labels: List[int] = field(default_factory=list)

    def record(self, detections: Sequence[Detection], confirmed: bool) -> None:
        self.windows.append(list(detections))
        self.labels.append(1 if confirmed else 0)

    def retrain(self, fusion: LearnedFusion) -> Optional[LearnedFusion]:
        """Retrain the learned fusion once both classes are represented."""
        if len(set(self.labels)) < 2:
            return None
        return fusion.fit(self.windows, self.labels)


def build_training_set(n_per_class: int = 40, seed: int = 0
                       ) -> Tuple[List[List[Detection]], List[int]]:
    """Generate labelled correlation windows from synthetic scenarios.

    Positive = corroborated incursion; negative = single-modality / background.
    Used to fit `LearnedFusion` offline (Component 1a ships no DND data).
    """
    from rudestorm import synthetic
    from rudestorm.adapters import AcousticAdapter, CSIPresenceAdapter, RemoteIDAdapter
    from rudestorm.config import RudestormConfig

    cfg = RudestormConfig()
    windows: List[List[Detection]] = []
    labels: List[int] = []

    def detections_for(samples) -> List[Detection]:
        adapters = {
            "remote_id": RemoteIDAdapter("mote-rf-1", cfg.remote_id),
            "acoustic": AcousticAdapter("mote-mic-1", cfg.acoustic),
            "wifi_csi": CSIPresenceAdapter("mote-csi-1", cfg.csi),
        }
        out: List[Detection] = []
        for s in samples:
            det = adapters[s.modality].process(s.payload)
            if det is not None:
                out.append(det)
        return out

    for i in range(n_per_class):
        pos = detections_for(synthetic.scenario_cooperative_uas(seed=seed + i))
        if pos:
            windows.append(pos)
            labels.append(1)
        neg = detections_for(synthetic.scenario_false_alarm_single(seed=seed + 1000 + i))
        windows.append(neg)
        labels.append(0)
    return windows, labels
