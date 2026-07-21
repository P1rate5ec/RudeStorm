"""Core event schema for rudestorm.

These are the machine-readable structures that flow through the middleware:
raw sensor input -> `Detection` (per-modality, low confidence) -> `ThreatEvent`
(fused, operator-ready). `ThreatEvent.to_json()` is the operator output contract.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class Modality(str, Enum):
    """Independent sensing modalities. Two DISTINCT modalities are required to
    satisfy the challenge's heterogeneous-source essential outcome."""

    WIFI_CSI = "wifi_csi"          # coarse presence / gross motion (no identity)
    REMOTE_ID = "remote_id"        # passive ASTM F3411 / DJI DroneID broadcast
    ACOUSTIC = "acoustic"          # edge spectrogram classifier (corroboration only)
    VIDEO = "video"               # edge-redacted CCTV small-object confirmation
    VIBRATION = "vibration"        # structural / perimeter accelerometer


# Modalities that are only ever allowed to *corroborate*, never to trigger alone.
CORROBORATION_ONLY = frozenset({Modality.ACOUSTIC, Modality.VIBRATION})


@dataclass
class GeoPoint:
    """WGS84 geolocation."""

    lat: float
    lon: float
    alt_m: Optional[float] = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.lat) or not -90.0 <= self.lat <= 90.0:
            raise ValueError(f"lat must be finite and in [-90,90], got {self.lat}")
        if not math.isfinite(self.lon) or not -180.0 <= self.lon <= 180.0:
            raise ValueError(f"lon must be finite and in [-180,180], got {self.lon}")
        if self.alt_m is not None and not math.isfinite(self.alt_m):
            raise ValueError(f"alt_m must be finite, got {self.alt_m}")

    def as_tuple(self) -> Tuple[float, float]:
        return (self.lat, self.lon)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"lat": round(self.lat, 6), "lon": round(self.lon, 6)}
        if self.alt_m is not None:
            d["alt_m"] = round(self.alt_m, 1)
        return d


@dataclass
class Detection:
    """A single-modality observation emitted by a sensor adapter.

    Confidence is deliberately treated as weak evidence: the fusion engine
    combines multiple detections rather than trusting any one of them.
    """

    modality: Modality
    source_id: str                       # node/mote identifier
    timestamp: datetime                  # UTC observation time
    confidence: float                    # 0..1 weak per-modality evidence
    kind: str                            # e.g. "presence", "drone_broadcast"
    location: Optional[GeoPoint] = None  # target or node location if known
    attributes: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "modality": self.modality.value,
            "source_id": self.source_id,
            "timestamp": self.timestamp.isoformat(),
            "confidence": round(self.confidence, 4),
            "kind": self.kind,
            "location": self.location.to_dict() if self.location else None,
            "attributes": self.attributes,
        }


@dataclass
class ThreatEvent:
    """Fused, operator-ready event. This is the middleware's external contract.

    A ThreatEvent is only produced after the fusion engine's corroboration rule
    is satisfied, so it carries per-source contribution weights and a provenance
    hash for chain-of-custody.
    """

    threat_class: str
    confidence: float
    timestamp: datetime
    window_seconds: float
    contributing: List[Detection]
    geolocation: Optional[GeoPoint] = None
    taxonomy: List[str] = field(default_factory=list)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    provenance_hash: Optional[str] = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")
        if self.window_seconds <= 0 or not math.isfinite(self.window_seconds):
            raise ValueError("window_seconds must be finite and positive")
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)

    @property
    def modalities(self) -> List[Modality]:
        return sorted({d.modality for d in self.contributing}, key=lambda m: m.value)

    def to_dict(self) -> Dict[str, Any]:
        total = sum(d.confidence for d in self.contributing) or 1.0
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "threat_class": self.threat_class,
            "confidence": round(self.confidence, 4),
            "window_seconds": self.window_seconds,
            "geolocation": self.geolocation.to_dict() if self.geolocation else None,
            "modalities": [m.value for m in self.modalities],
            "taxonomy": self.taxonomy,
            "contributions": [
                {
                    "modality": d.modality.value,
                    "source_id": d.source_id,
                    "confidence": round(d.confidence, 4),
                    "weight": round(d.confidence / total, 4),
                    "kind": d.kind,
                }
                for d in self.contributing
            ],
            "provenance_hash": self.provenance_hash,
        }

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)
