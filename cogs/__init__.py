"""Cogs: capability-gated, privacy-classed capability modules.

    from rudestorm.cogs import CogRegistry, PI_4B, PrivacyClass
    from rudestorm.cogs.vitals import BreathingRateCog

    registry = CogRegistry(PI_4B, log=provenance)
    registry.load(BreathingRateCog, source_id="node-01")
    # -> rejected: privacy class 'biometric' exceeds ceiling 'coarse_presence'

    registry.unlock_privacy_class(PrivacyClass.BIOMETRIC, authorization="CHG-4471")
    registry.load(BreathingRateCog, source_id="node-01")
    # -> loaded, and both the unlock and the load are in the provenance chain
"""

from rudestorm.cogs.base import (
    DEFAULT_PRIVACY_CEILING,
    Capability,
    Cog,
    CogCategory,
    CogManifest,
    NodeProfile,
    PrivacyClass,
)
from rudestorm.cogs.nodes import (
    ESP32_S3,
    NODE_PROFILES,
    PI_4B,
    PI_5,
    PI_ZERO_2W,
    WORKSTATION,
    get_profile,
)
from rudestorm.cogs.registry import CogRegistry, CogRejected, LoadResult

__all__ = [
    "Capability",
    "Cog",
    "CogCategory",
    "CogManifest",
    "CogRegistry",
    "CogRejected",
    "DEFAULT_PRIVACY_CEILING",
    "ESP32_S3",
    "LoadResult",
    "NODE_PROFILES",
    "NodeProfile",
    "PI_4B",
    "PI_5",
    "PI_ZERO_2W",
    "PrivacyClass",
    "WORKSTATION",
    "get_profile",
]
