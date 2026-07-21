"""Adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from rudestorm.events import Detection, Modality


class SensorAdapter(ABC):
    """Turns one raw modality sample into an optional `Detection`.

    Returning None means "nothing worth reporting this sample" — most samples
    from a passive sensor are background and should not become detections.
    """

    modality: Modality

    def __init__(self, source_id: str) -> None:
        self.source_id = source_id
        self._samples_seen = 0
        self._detections_emitted = 0

    @abstractmethod
    def process(self, sample: Any) -> Optional[Detection]:
        """Process a single raw sample into a Detection, or None."""

    def _count(self, detection: Optional[Detection]) -> Optional[Detection]:
        self._samples_seen += 1
        if detection is not None:
            self._detections_emitted += 1
        return detection

    @property
    def stats(self) -> dict:
        return {
            "source_id": self.source_id,
            "modality": self.modality.value,
            "samples_seen": self._samples_seen,
            "detections_emitted": self._detections_emitted,
        }
