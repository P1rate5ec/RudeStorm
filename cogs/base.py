"""Cog: the unit of deployment.

A cog is a self-describing capability module — a detector, an analytic, or both
— that declares up front what hardware it needs and what class of information it
produces. Inspired by RuView's edge-module catalog, with two additions that the
original leaves to documentation and we enforce in code:

1. **Capability gating.** A cog names the hardware capabilities it requires. A
   node that lacks them refuses to load it. This is why a Pi Zero 2W cannot
   silently run a degraded version of a CSI cog and report confident nonsense:
   its radio (CYW43438) is not on Nexmon's supported-chip list, so it does not
   advertise `CSI_EXTRACTION`, so the cog never loads.

2. **Privacy classing.** Every cog declares the most invasive class of
   information it can produce. Anything above `COARSE_PRESENCE` is refused by
   default and requires an explicit, logged unlock. This is the structural
   version of rudestorm's honest-limits rule: "we do not infer identity" stops
   being a promise in a README and becomes a load-time failure.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, FrozenSet, List, Optional, Sequence

from rudestorm.events import Detection, Modality


class Capability(str, Enum):
    """A hardware or platform capability a node may or may not have."""

    CSI_EXTRACTION = "csi_extraction"      # per-frame CSI (Nexmon / ESP32 / research NIC)
    MONITOR_MODE = "monitor_mode"          # promiscuous 802.11 capture
    PACKET_INJECTION = "packet_injection"  # active tx — assessment mode only
    BLE_SCAN = "ble_scan"
    CELLULAR_SCAN = "cellular_scan"        # requires SDR or cellular modem
    I2S_AUDIO = "i2s_audio"
    NEURAL_INFERENCE = "neural_inference"  # enough CPU/RAM for on-device models
    PERSISTENT_STORE = "persistent_store"  # vector store / long-horizon history
    GPIO = "gpio"


class PrivacyClass(int, Enum):
    """Most invasive class of information a cog can produce. Ordered.

    The gate sits between COARSE_PRESENCE and IDENTITY. Everything at or below
    COARSE_PRESENCE is deployable by default; everything above requires an
    explicit unlock and is written to the provenance log when granted.
    """

    NONE = 0             # RF metadata only — no humans in the output at all
    COARSE_PRESENCE = 1  # "someone is in this zone" — no count, pose, or identity
    IDENTITY = 2         # device or person fingerprinting / re-identification
    BIOMETRIC = 3        # vitals, pose, gait — physiological inference

    @property
    def label(self) -> str:
        return self.name.lower()


#: The highest privacy class a node will load without an explicit unlock.
DEFAULT_PRIVACY_CEILING = PrivacyClass.COARSE_PRESENCE


class CogCategory(str, Enum):
    """Coarse grouping, used for catalog display and bulk enable/disable."""

    RF_HYGIENE = "rf_hygiene"          # rogue AP, evil twin, deauth, replay
    SENSING_DEFENSE = "sensing_defense"  # 802.11bf abuse, CSI poisoning
    PHYSICAL = "physical"              # presence, perimeter, tailgating
    AIRSPACE = "airspace"              # drone / Remote ID
    INTEGRITY = "integrity"            # witness chain, attestation, audit
    FLEET = "fleet"                    # mesh, consensus, deployment, health


@dataclass(frozen=True)
class NodeProfile:
    """What a physical node can actually do.

    Built from measured hardware facts, not aspiration. `describe_gap` exists so
    an operator who plugs in the wrong board gets told why a cog is missing
    instead of quietly getting fewer alerts.
    """

    tier: str
    ram_mb: int
    cores: int
    capabilities: FrozenSet[Capability]
    notes: str = ""

    def supports(self, required: Sequence[Capability]) -> bool:
        return set(required).issubset(self.capabilities)

    def missing(self, required: Sequence[Capability]) -> List[Capability]:
        return sorted(set(required) - self.capabilities, key=lambda c: c.value)


@dataclass(frozen=True)
class CogManifest:
    """A cog's self-declaration. Immutable, and hashed into the provenance log.

    `attack_ids` maps the cog to MITRE ATT&CK technique IDs so events land in a
    SOC's existing taxonomy rather than inventing a private one.
    """

    cog_id: str
    name: str
    category: CogCategory
    version: str
    privacy_class: PrivacyClass
    requires: FrozenSet[Capability] = frozenset()
    emits: Optional[Modality] = None
    consumes: FrozenSet[Modality] = frozenset()
    min_ram_mb: int = 32
    attack_ids: FrozenSet[str] = frozenset()
    description: str = ""
    #: Honest statement of what this cog cannot do. Surfaced in the UI next to
    #: every alert it raises, so an operator never over-reads a detection.
    limits: str = ""

    def __post_init__(self) -> None:
        if not self.cog_id or " " in self.cog_id:
            raise ValueError(f"cog_id must be a non-empty slug, got {self.cog_id!r}")
        if self.min_ram_mb <= 0:
            raise ValueError("min_ram_mb must be positive")
        if self.emits is not None and self.emits in self.consumes:
            raise ValueError(
                f"cog {self.cog_id} both emits and consumes {self.emits.value}; "
                "this creates a fusion feedback loop"
            )

    def to_dict(self) -> dict:
        return {
            "cog_id": self.cog_id,
            "name": self.name,
            "category": self.category.value,
            "version": self.version,
            "privacy_class": self.privacy_class.label,
            "requires": sorted(c.value for c in self.requires),
            "emits": self.emits.value if self.emits else None,
            "consumes": sorted(m.value for m in self.consumes),
            "min_ram_mb": self.min_ram_mb,
            "attack_ids": sorted(self.attack_ids),
            "description": self.description,
            "limits": self.limits,
        }


class Cog(ABC):
    """Base class for all cogs.

    A cog is either a *producer* (turns raw samples into Detections, like a
    SensorAdapter) or an *analytic* (turns a window of Detections into a
    derived Detection). Both shapes return `Detection | None` so the fusion
    engine's corroboration rule applies uniformly — a cog cannot bypass it by
    emitting a ThreatEvent directly.
    """

    manifest: CogManifest

    def __init__(self, source_id: str) -> None:
        self.source_id = source_id
        self._emitted = 0

    @abstractmethod
    def process(self, sample: Any) -> Optional[Detection]:
        """Handle one sample or one detection window. None means 'nothing to say'."""

    def on_load(self, node: NodeProfile) -> None:
        """Hook for cogs that need to size buffers against the host node."""

    @property
    def stats(self) -> dict:
        return {
            "cog_id": self.manifest.cog_id,
            "source_id": self.source_id,
            "emitted": self._emitted,
        }
