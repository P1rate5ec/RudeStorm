"""WiFi Channel State Information -> coarse presence / gross motion.

Honest capability envelope (see references/CSI_ENVELOPE.md): this adapter reports
that *something moved* near the node. It does NOT infer identity, body pose,
person count, or vitals. Those claims are explicitly out of scope because they
are not physically supportable on commodity single-node ESP32-S3 CSI.

The signal-processing chain (noise floor gate, Hamming window, amplitude-variance
motion score, inter-antenna decorrelation, exponential temporal smoothing) is
distilled from the reusable parts of the wifi-densepose CSI processor, with the
pose/vitals modeling removed.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import scipy.signal

from rudestorm.adapters.base import SensorAdapter
from rudestorm.config import CSIConfig
from rudestorm.events import Detection, Modality


class CSISample:
    """Minimal CSI sample: amplitude & phase over (antennas x subcarriers)."""

    def __init__(self, amplitude: np.ndarray, phase: np.ndarray,
                 timestamp: Optional[datetime] = None) -> None:
        if amplitude.shape != phase.shape or amplitude.ndim != 2:
            raise ValueError("amplitude and phase must be equal-shaped 2D arrays")
        self.amplitude = amplitude
        self.phase = phase
        self.timestamp = timestamp or datetime.now(timezone.utc)


class CSIPresenceAdapter(SensorAdapter):
    modality = Modality.WIFI_CSI

    def __init__(self, source_id: str, config: Optional[CSIConfig] = None) -> None:
        super().__init__(source_id)
        self.config = config or CSIConfig()
        self._smoothed = 0.0
        self._baseline_var = deque(maxlen=self.config.max_history)
        self._prev_amp: Optional[np.ndarray] = None

    def process(self, sample: CSISample) -> Optional[Detection]:
        motion = self._motion_score(sample)
        raw_conf = self._presence_confidence(sample, motion)

        c = self.config.smoothing_factor
        self._smoothed = c * self._smoothed + (1 - c) * raw_conf
        confidence = max(self._smoothed, raw_conf)

        if confidence < self.config.presence_threshold:
            return self._count(None)

        detection = Detection(
            modality=self.modality,
            source_id=self.source_id,
            timestamp=sample.timestamp,
            confidence=float(np.clip(confidence, 0.0, 1.0)),
            kind="presence",
            attributes={
                "motion_score": round(float(motion), 4),
                "note": "coarse presence/motion only; no identity or pose",
            },
        )
        return self._count(detection)

    # --- signal processing -------------------------------------------------
    def _clean(self, amplitude: np.ndarray) -> np.ndarray:
        amp_db = 20 * np.log10(np.abs(amplitude) + 1e-12)
        floored = amplitude.copy()
        floored[amp_db <= self.config.noise_threshold_db] = 0.0
        window = scipy.signal.windows.hamming(floored.shape[1])
        return floored * window[np.newaxis, :]

    def _motion_score(self, sample: CSISample) -> float:
        amp = self._clean(sample.amplitude)
        subcarrier_var = float(np.mean(np.var(amp, axis=0)))
        self._baseline_var.append(subcarrier_var)
        baseline = float(np.median(self._baseline_var)) if self._baseline_var else 0.0
        # Motion = variance excursion above the rolling baseline.
        excursion = max(0.0, subcarrier_var - baseline)
        temporal = 0.0
        if self._prev_amp is not None and self._prev_amp.shape == amp.shape:
            temporal = float(np.mean(np.abs(amp - self._prev_amp)))
        self._prev_amp = amp.copy()
        # Frame-to-frame amplitude change is the primary motion cue; baseline
        # excursion catches onsets after a quiet period.
        score = 0.1 * np.tanh(excursion * 5.0) + 0.9 * np.tanh(temporal * 5.5)
        return float(np.clip(score, 0.0, 1.0))

    def _presence_confidence(self, sample: CSISample, motion: float) -> float:
        if motion < self.config.motion_threshold:
            return 0.0
        # Map motion above threshold onto a confidence ramp.
        span = max(1e-6, 1.0 - self.config.motion_threshold)
        return float(np.clip((motion - self.config.motion_threshold) / span, 0.0, 1.0))
