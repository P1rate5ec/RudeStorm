"""Multi-modal fusion engine — rudestorm's core IP.

The engine holds a time-aligned sliding window of `Detection`s and applies
correlation profiles. A profile fires only when its required modalities are all
present in the window and its combined confidence clears a gate. This is the
false-alarm-suppression story: no single passive sensor triggers an alert alone.

Confidence fusion uses noisy-OR across contributing detections, which rewards
independent corroboration without letting one loud modality dominate.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, Deque, List, Optional, Protocol, Sequence, Set

from rudestorm.config import FusionConfig
from rudestorm.events import (
    CORROBORATION_ONLY,
    Detection,
    GeoPoint,
    Modality,
    ThreatEvent,
)


@dataclass
class CorrelationProfile:
    """A named rule mapping a set of corroborating modalities to a threat class.

    `required` lists modalities that must ALL appear in the window. `min_distinct`
    can raise the bar beyond len(required) when using `any_of`. A profile is
    rejected if every contributing modality is corroboration-only (acoustic /
    vibration can support but never stand up an event by themselves).
    """

    name: str
    threat_class: str
    required: Set[Modality]
    taxonomy: List[str] = field(default_factory=list)
    min_distinct: Optional[int] = None
    geolocate_from: Optional[Modality] = None

    def matches(self, present: Set[Modality]) -> bool:
        if not self.required.issubset(present):
            return False
        need = self.min_distinct or len(self.required)
        if len(present & self._pool()) < need:
            return False
        if (present & self.required).issubset(CORROBORATION_ONLY):
            return False
        return True

    def _pool(self) -> Set[Modality]:
        return set(self.required)


def default_profiles() -> List[CorrelationProfile]:
    """Profiles covering the two lead use cases in the challenge."""

    return [
        CorrelationProfile(
            name="cooperative_uas",
            threat_class="uas_cooperative_intrusion",
            required={Modality.REMOTE_ID, Modality.ACOUSTIC},
            taxonomy=["counter-uas", "cooperative-broadcaster"],
            geolocate_from=Modality.REMOTE_ID,
        ),
        CorrelationProfile(
            name="uas_visual_confirmed",
            threat_class="uas_visual_confirmed",
            required={Modality.REMOTE_ID, Modality.VIDEO},
            taxonomy=["counter-uas", "visual-confirmed"],
            geolocate_from=Modality.REMOTE_ID,
        ),
        CorrelationProfile(
            name="perimeter_intrusion",
            threat_class="presence_intrusion",
            required={Modality.WIFI_CSI, Modality.ACOUSTIC},
            taxonomy=["critical-infrastructure", "anonymous-presence"],
            geolocate_from=Modality.WIFI_CSI,
        ),
        CorrelationProfile(
            name="structural_anomaly",
            threat_class="structural_anomaly",
            required={Modality.WIFI_CSI, Modality.VIBRATION},
            taxonomy=["critical-infrastructure", "structural"],
        ),
    ]


def noisy_or(confidences: Sequence[float]) -> float:
    product = 1.0
    for c in confidences:
        product *= (1.0 - max(0.0, min(1.0, c)))
    return 1.0 - product


class WindowScorer(Protocol):
    """A drop-in replacement for noisy-OR (e.g. learning.LearnedFusion).

    Must honor the single-modality safety rule itself (return 0.0 when fewer than
    two independent modalities are present); the engine also enforces the gate.
    """

    def score(self, detections: Sequence[Detection]) -> float: ...


class FusionEngine:
    def __init__(self, config: Optional[FusionConfig] = None,
                 profiles: Optional[List[CorrelationProfile]] = None,
                 scorer: Optional[WindowScorer] = None) -> None:
        self.config = config or FusionConfig()
        self.profiles = profiles if profiles is not None else default_profiles()
        self.scorer = scorer  # if set, replaces noisy_or with a learned model
        self._window: Deque[Detection] = deque()

    def add(self, detection: Detection) -> List[ThreatEvent]:
        """Add a detection and return any threat events it corroborates into."""
        self._window.append(detection)
        self._evict(detection)
        return self._evaluate()

    def _evict(self, latest: Detection) -> None:
        horizon = latest.timestamp - timedelta(seconds=self.config.window_seconds)
        while self._window and self._window[0].timestamp < horizon:
            self._window.popleft()

    def _evaluate(self) -> List[ThreatEvent]:
        present = {d.modality for d in self._window}
        if len(present) < self.config.min_modalities:
            return []

        events: List[ThreatEvent] = []
        for profile in self.profiles:
            if not profile.matches(present):
                continue
            contributing = [d for d in self._window if d.modality in profile.required]
            if self.scorer is not None:
                fused = self.scorer.score(contributing)
            else:
                fused = noisy_or([d.confidence for d in contributing])
            if fused < self.config.alert_confidence:
                continue
            events.append(self._build_event(profile, contributing, fused))
        return events

    def _build_event(self, profile: CorrelationProfile,
                     contributing: List[Detection], fused: float) -> ThreatEvent:
        geo: Optional[GeoPoint] = None
        if profile.geolocate_from is not None:
            for d in contributing:
                if d.modality == profile.geolocate_from and d.location is not None:
                    geo = d.location
                    break
        latest_ts = max(d.timestamp for d in contributing)
        return ThreatEvent(
            threat_class=profile.threat_class,
            confidence=fused,
            timestamp=latest_ts,
            window_seconds=self.config.window_seconds,
            contributing=list(contributing),
            geolocation=geo,
            taxonomy=list(profile.taxonomy),
        )

    @property
    def window_size(self) -> int:
        return len(self._window)
