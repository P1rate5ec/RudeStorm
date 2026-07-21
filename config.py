"""Configuration for the rudestorm middleware.

Plain dataclasses (no external settings dependency) so the middleware runs
offline on edge hardware with zero network calls at import time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class CSIConfig:
    """WiFi Channel State Information presence detection parameters."""

    sampling_rate: float = 100.0       # Hz
    noise_threshold_db: float = -60.0  # amplitudes quieter than this are floored
    motion_threshold: float = 0.30     # gross-motion score gate
    presence_threshold: float = 0.55   # smoothed confidence to declare presence
    smoothing_factor: float = 0.80     # exponential moving average weight
    max_history: int = 256


@dataclass
class RemoteIDConfig:
    """Passive Remote ID / DroneID decode parameters."""

    min_confidence: float = 0.60
    # Geofence: alert only on drones inside an operator-defined area of interest.
    aoi_center_lat: float = 44.6488     # Halifax harbour, illustrative
    aoi_center_lon: float = -63.5752
    aoi_radius_m: float = 3000.0


@dataclass
class AcousticConfig:
    """Edge acoustic classifier parameters (corroboration only)."""

    uav_band_hz: tuple = (100.0, 8000.0)
    detection_threshold: float = 0.45


@dataclass
class FusionConfig:
    """Sliding-window correlation parameters."""

    window_seconds: float = 4.0
    min_modalities: int = 2            # the hard corroboration rule
    alert_confidence: float = 0.60     # fused score gate for an operator event


@dataclass
class GovernanceConfig:
    """Privacy / provenance parameters."""

    # File persistence is opt-in. Edge deployments must choose an explicit,
    # writable, access-controlled path rather than inheriting the process cwd.
    audit_log_path: Optional[str] = None
    redact_video: bool = True
    operator_node_id: str = "ops-node-1"


@dataclass
class RudestormConfig:
    """Top-level configuration."""

    csi: CSIConfig = field(default_factory=CSIConfig)
    remote_id: RemoteIDConfig = field(default_factory=RemoteIDConfig)
    acoustic: AcousticConfig = field(default_factory=AcousticConfig)
    fusion: FusionConfig = field(default_factory=FusionConfig)
    governance: GovernanceConfig = field(default_factory=GovernanceConfig)

    node_locations: Dict[str, tuple] = field(default_factory=dict)
