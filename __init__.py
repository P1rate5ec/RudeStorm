"""rudestorm — passive urban sensing fusion middleware.

rudestorm ingests weak, individually-unreliable passive signals from existing
urban infrastructure (WiFi Channel State Information, passive Remote ID / DroneID
broadcasts, and acoustic corroboration), correlates them in a time-aligned sliding
window, and emits high-confidence, privacy-clean operator events.

Design rules that shape this package:
  * No single passive modality raises an alert on its own. A high-priority event
    requires >= 2 independent modalities corroborated inside one time window.
  * Personally identifiable data is redacted at the edge before egress.
  * Every detection, correlation, and redaction decision is written to a
    hash-chained, append-only audit log for defensible chain-of-custody.
  * WiFi-CSI is used for coarse presence / gross motion ONLY — never identity,
    pose, or vitals.
"""

from rudestorm.events import Detection, Modality, ThreatEvent
from rudestorm.fusion import CorrelationProfile, FusionEngine
from rudestorm.identity import (
    IDENTIFIED_TRACK,
    IDENTITY_UNAVAILABLE,
    UNIDENTIFIED_DRONE,
    IdentityResult,
    resolve_identity,
)
from rudestorm.learning import (
    ConfidenceCalibrator,
    CSIBaselineModel,
    LearnedFusion,
    OperatorFeedback,
)
from rudestorm.pipeline import Pipeline

__version__ = "0.1.0"

__all__ = [
    "Detection",
    "Modality",
    "ThreatEvent",
    "FusionEngine",
    "CorrelationProfile",
    "Pipeline",
    "LearnedFusion",
    "ConfidenceCalibrator",
    "CSIBaselineModel",
    "OperatorFeedback",
    "IdentityResult",
    "resolve_identity",
    "IDENTIFIED_TRACK",
    "UNIDENTIFIED_DRONE",
    "IDENTITY_UNAVAILABLE",
]
