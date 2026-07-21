"""Passive sensor adapters.

Each adapter converts raw, modality-specific input into a normalized `Detection`.
Adapters do the modality-local work (signal processing, decode, edge inference)
and nothing else — correlation across modalities is the fusion engine's job.
"""

from rudestorm.adapters.acoustic import AcousticAdapter
from rudestorm.adapters.base import SensorAdapter
from rudestorm.adapters.csi_presence import CSIPresenceAdapter
from rudestorm.adapters.remote_id import RemoteIDAdapter, RemoteIDParseError

__all__ = [
    "SensorAdapter",
    "CSIPresenceAdapter",
    "RemoteIDAdapter",
    "RemoteIDParseError",
    "AcousticAdapter",
]
