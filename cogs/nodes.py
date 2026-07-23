"""Measured hardware profiles for supported node tiers.

These are deliberately conservative and sourced from what the silicon actually
does, not from what a datasheet implies. The single most consequential fact
encoded here: **the Pi Zero 2W cannot extract CSI.**

Nexmon CSI supports bcm4339, bcm43455c0, bcm4358 and bcm4365/4366c0. The Zero 2W
ships a CYW43438, which is not on that list. It is a fine passive 802.11 and BLE
node; it is not a sensing node, and `PI_ZERO_2W` therefore omits
`Capability.CSI_EXTRACTION`. Any cog that needs CSI will refuse to load on it and
say why.

The Pi 4B (bcm43455c0) is Nexmon's best-supported target and is the cheapest
single board that does both CSI and monitor mode — it, not the Zero 2W, is the
natural full-capability sensor.
"""

from __future__ import annotations

from typing import Dict

from rudestorm.cogs.base import Capability, NodeProfile

#: Cheap throw-anywhere RF/WIDS node. No CSI — wrong Broadcom part.
PI_ZERO_2W = NodeProfile(
    tier="pi_zero_2w",
    ram_mb=512,
    cores=4,
    capabilities=frozenset({
        Capability.MONITOR_MODE,
        Capability.BLE_SCAN,
        Capability.I2S_AUDIO,
        Capability.GPIO,
    }),
    notes=(
        "CYW43438: not supported by Nexmon CSI, so no CSI extraction. Monitor "
        "mode on the onboard radio is unreliable; pair with a USB adapter "
        "(Atheros/Ralink) via the OTG port for dependable capture. 512 MB RAM "
        "rules out on-device neural inference."
    ),
)

#: Cheapest single board that does CSI *and* monitor mode. The workhorse sensor.
PI_4B = NodeProfile(
    tier="pi_4b",
    ram_mb=2048,
    cores=4,
    capabilities=frozenset({
        Capability.CSI_EXTRACTION,
        Capability.MONITOR_MODE,
        Capability.BLE_SCAN,
        Capability.I2S_AUDIO,
        Capability.NEURAL_INFERENCE,
        Capability.PERSISTENT_STORE,
        Capability.GPIO,
    }),
    notes="bcm43455c0 — Nexmon CSI's best-supported chip. Recommended sensor tier.",
)

#: Hub / 'seed': runs fusion, provenance, web console, model inference.
PI_5 = NodeProfile(
    tier="pi_5",
    ram_mb=8192,
    cores=4,
    capabilities=frozenset({
        Capability.CSI_EXTRACTION,
        Capability.MONITOR_MODE,
        Capability.BLE_SCAN,
        Capability.I2S_AUDIO,
        Capability.NEURAL_INFERENCE,
        Capability.PERSISTENT_STORE,
        Capability.GPIO,
    }),
    notes=(
        "Nexmon CSI works via the driver-independent setup (verified on RPi OS "
        "Lite Trixie, Nov 2025) rather than the older patched-brcmfmac path."
    ),
)

#: $9 mote. Native CSI, but no room for anything above trivial DSP.
ESP32_S3 = NodeProfile(
    tier="esp32_s3",
    ram_mb=8,
    cores=2,
    capabilities=frozenset({
        Capability.CSI_EXTRACTION,
        Capability.MONITOR_MODE,
        Capability.BLE_SCAN,
    }),
    notes="Native CSI + Remote ID sniffing. Firmware target, not a Python host.",
)

#: Analyst laptop / server running the console against remote nodes.
WORKSTATION = NodeProfile(
    tier="workstation",
    ram_mb=16384,
    cores=8,
    capabilities=frozenset({
        Capability.NEURAL_INFERENCE,
        Capability.PERSISTENT_STORE,
    }),
    notes="No radio of its own; consumes detections from field nodes.",
)

NODE_PROFILES: Dict[str, NodeProfile] = {
    p.tier: p for p in (PI_ZERO_2W, PI_4B, PI_5, ESP32_S3, WORKSTATION)
}


def get_profile(tier: str) -> NodeProfile:
    """Look up a node profile by tier slug."""
    try:
        return NODE_PROFILES[tier]
    except KeyError:
        known = ", ".join(sorted(NODE_PROFILES))
        raise ValueError(f"unknown node tier {tier!r}; known tiers: {known}") from None
