"""The starter cog catalog.

A curated set spanning the categories, so a fresh node has something real to
load and the UI has a populated menu. Each cog here is either implemented
(vitals) or a declared stub whose manifest is honest about being a seam — the
manifest exists so capability/privacy gating and the menu work end to end;
`process` returns None until the detector is wired to hardware.

Stubs are marked in their `limits` string and never fabricate detections. This
is the difference between a roadmap and a lie: the menu shows the capability, the
gate enforces its requirements, and the cog stays silent rather than inventing a
signal it cannot yet measure.
"""

from __future__ import annotations

from typing import Any, List, Optional, Type

from rudestorm.cogs.base import (
    Capability,
    Cog,
    CogCategory,
    CogManifest,
    PrivacyClass,
)
from rudestorm.cogs.vitals import BreathingRateCog, HeartRateCog
from rudestorm.events import Detection, Modality


class _Stub(Cog):
    """A declared-but-unimplemented cog. Loads and gates; never emits."""

    def process(self, sample: Any) -> Optional[Detection]:  # pragma: no cover
        return None


class PresenceCog(_Stub):
    manifest = CogManifest(
        cog_id="presence-csi", name="Presence", category=CogCategory.PHYSICAL,
        version="0.1.0", privacy_class=PrivacyClass.COARSE_PRESENCE,
        requires=frozenset({Capability.CSI_EXTRACTION}), emits=Modality.WIFI_CSI,
        attack_ids=frozenset({"T1200"}),
        description="Phase-variance presence with a model-backed head (seam).",
        limits="STUB: phase-variance fallback pending hardware calibration.",
    )


class MotionCog(_Stub):
    manifest = CogManifest(
        cog_id="motion-csi", name="Motion / activity", category=CogCategory.PHYSICAL,
        version="0.1.0", privacy_class=PrivacyClass.COARSE_PRESENCE,
        requires=frozenset({Capability.CSI_EXTRACTION}), emits=Modality.WIFI_CSI,
        description="Motion-band power + phase acceleration.",
        limits="STUB: not yet implemented.",
    )


class FallCog(_Stub):
    manifest = CogManifest(
        cog_id="fall-csi", name="Fall detection", category=CogCategory.PHYSICAL,
        version="0.1.0", privacy_class=PrivacyClass.BIOMETRIC,
        requires=frozenset({Capability.CSI_EXTRACTION}), emits=Modality.WIFI_CSI,
        min_ram_mb=64,
        description="Phase-acceleration threshold, 3-frame debounce, 5 s cooldown.",
        limits="STUB: debounce/cooldown parameters need hardware validation.",
    )


class RogueAPCog(_Stub):
    manifest = CogManifest(
        cog_id="rf-rogue-ap", name="Rogue AP / evil twin",
        category=CogCategory.RF_HYGIENE, version="0.1.0",
        privacy_class=PrivacyClass.NONE,
        requires=frozenset({Capability.MONITOR_MODE}), emits=Modality.RF_EMITTER,
        attack_ids=frozenset({"T1557", "T1200"}),
        description="Beacon fingerprinting: BSSID/SSID/channel/RSSI mismatch vs "
                    "an authorized baseline.",
        limits="STUB: requires an authorized-AP baseline to compare against.",
    )


class DeauthFloodCog(_Stub):
    manifest = CogManifest(
        cog_id="rf-deauth", name="Deauth / disassoc flood",
        category=CogCategory.RF_HYGIENE, version="0.1.0",
        privacy_class=PrivacyClass.NONE,
        requires=frozenset({Capability.MONITOR_MODE}), emits=Modality.RF_EMITTER,
        attack_ids=frozenset({"T1498"}),
        description="Management-frame rate anomaly on 802.11 deauth/disassoc.",
        limits="STUB: not yet implemented.",
    )


class SensingSessionCog(_Stub):
    manifest = CogManifest(
        cog_id="def-sensing-session", name="Unauthorized 802.11bf",
        category=CogCategory.SENSING_DEFENSE, version="0.1.0",
        privacy_class=PrivacyClass.NONE,
        requires=frozenset({Capability.MONITOR_MODE}),
        emits=Modality.SENSING_SESSION,
        description="Detects 802.11bf sensing-measurement solicitation — someone "
                    "turning the building into a sensor without authorization.",
        limits="STUB: 802.11bf sounding frames need an 11ax/be capture path.",
    )


class CSIIntegrityCog(_Stub):
    manifest = CogManifest(
        cog_id="def-csi-integrity", name="CSI poisoning / replay",
        category=CogCategory.SENSING_DEFENSE, version="0.1.0",
        privacy_class=PrivacyClass.NONE,
        requires=frozenset({Capability.CSI_EXTRACTION}),
        emits=Modality.CSI_INTEGRITY,
        description="Flags injected or replayed CSI trying to blind our own "
                    "physical detections.",
        limits="STUB: needs a labelled injection corpus to calibrate.",
    )


class RemoteIDCog(_Stub):
    manifest = CogManifest(
        cog_id="air-remote-id", name="Drone Remote ID",
        category=CogCategory.AIRSPACE, version="0.1.0",
        privacy_class=PrivacyClass.NONE,
        requires=frozenset({Capability.MONITOR_MODE, Capability.BLE_SCAN}),
        emits=Modality.REMOTE_ID,
        description="Passive ASTM F3411 / DJI DroneID broadcast decode.",
        limits="STUB: wraps the existing RemoteIDAdapter parse seam.",
    )


class WitnessChainCog(_Stub):
    manifest = CogManifest(
        cog_id="int-witness", name="Witness chain",
        category=CogCategory.INTEGRITY, version="0.1.0",
        privacy_class=PrivacyClass.NONE, min_ram_mb=64,
        description="Ed25519 signing over the provenance head for attributable, "
                    "not merely tamper-evident, custody.",
        limits="STUB: key management and signing pending.",
    )


class MeshCog(_Stub):
    manifest = CogManifest(
        cog_id="fleet-mesh", name="Mesh sync",
        category=CogCategory.FLEET, version="0.1.0",
        privacy_class=PrivacyClass.NONE,
        description="Delta-sync detections and provenance between field nodes and "
                    "the Pi brain.",
        limits="STUB: transport (MQTT/NATS) not yet wired.",
    )


#: Everything a node is offered at boot. The registry keeps what the hardware and
#: privacy ceiling allow and records a reason for the rest.
STARTER_CATALOG: List[Type[Cog]] = [
    PresenceCog, MotionCog, FallCog, BreathingRateCog, HeartRateCog,
    RogueAPCog, DeauthFloodCog, SensingSessionCog, CSIIntegrityCog,
    RemoteIDCog, WitnessChainCog, MeshCog,
]
