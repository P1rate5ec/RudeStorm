"""Acoustic corroboration adapter (edge spectrogram classifier).

Urban acoustic drone detection has an 8-15% false-positive rate, so this modality
is CORROBORATION ONLY — the fusion engine never lets it trigger an alert alone.
Only the inference result (a band-energy score) leaves the node; raw audio never
does, which is both a privacy and a bandwidth property.

The classifier here is an interpretable band-energy ratio over a spectrogram. It
is the seam where a trained CNN (e.g. on DroneAudioDataset) is dropped in; the
Detection contract above it does not change.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import numpy as np

from rudestorm.adapters.base import SensorAdapter
from rudestorm.config import AcousticConfig
from rudestorm.events import Detection, Modality


class AcousticSample:
    """A short audio frame plus its sample rate."""

    def __init__(self, waveform: np.ndarray, sample_rate: int = 16000,
                 timestamp: Optional[datetime] = None) -> None:
        self.waveform = np.asarray(waveform, dtype=float).ravel()
        self.sample_rate = sample_rate
        self.timestamp = timestamp or datetime.now(timezone.utc)


class AcousticAdapter(SensorAdapter):
    modality = Modality.ACOUSTIC

    def __init__(self, source_id: str, config: Optional[AcousticConfig] = None) -> None:
        super().__init__(source_id)
        self.config = config or AcousticConfig()

    def process(self, sample: AcousticSample) -> Optional[Detection]:
        score = self._band_energy_ratio(sample)
        if score < self.config.detection_threshold:
            return self._count(None)
        detection = Detection(
            modality=self.modality,
            source_id=self.source_id,
            timestamp=sample.timestamp,
            confidence=float(np.clip(score, 0.0, 1.0)),
            kind="acoustic_uav",
            attributes={
                "band_energy_ratio": round(float(score), 4),
                "role": "corroboration_only",
            },
        )
        return self._count(detection)

    def _band_energy_ratio(self, sample: AcousticSample) -> float:
        wf = sample.waveform
        if wf.size < 16:
            return 0.0
        spectrum = np.abs(np.fft.rfft(wf)) ** 2
        freqs = np.fft.rfftfreq(wf.size, d=1.0 / sample.sample_rate)
        lo, hi = self.config.uav_band_hz
        band = (freqs >= lo) & (freqs <= hi)
        total = float(np.sum(spectrum)) + 1e-12
        return float(np.sum(spectrum[band]) / total)
