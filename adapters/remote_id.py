"""Passive Remote ID / DroneID -> drone + operator localization.

ASTM F3411 / EN 4709 Remote ID and DJI DroneID are broadcast UNENCRYPTED over
WiFi (Beacon/NAN) and Bluetooth on the bands a commodity ESP32-S3 already hears.
A passive receiver recovers BOTH the drone's GPS position AND the operator's GPS
position with zero active emissions and no new primary sensors.

This adapter decodes a compact, self-describing Remote ID frame into a Detection.
The wire format here mirrors the OpenDroneID field set; in a field deployment the
`_parse_frame` method is the single seam where an OpenDroneID / antsdr / Kismet
DroneID decoder is dropped in. The correlation contract above it is unchanged.

Honest limit: cooperative broadcasters only. Encrypted O4-gen DroneID, spoofed or
disabled Remote ID, and fully autonomous radios-off drones are acknowledged
residual risk (radar-class, out of scope).
"""

from __future__ import annotations

import math
import struct
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from rudestorm.adapters.base import SensorAdapter
from rudestorm.config import RemoteIDConfig
from rudestorm.events import Detection, GeoPoint, Modality

_MAGIC = b"RID1"
# magic(4s) uav_type(B) status(B) drone_lat(i) drone_lon(i) drone_alt(h)
# op_lat(i) op_lon(i) speed(H)  -- lat/lon are degrees * 1e7 (OpenDroneID scaling)
_STRUCT = struct.Struct(">4sBBiihiiH")

_UA_TYPES = {
    0: "none", 1: "aeroplane", 2: "helicopter_multirotor", 3: "gyroplane",
    4: "hybrid_lift", 5: "ornithopter", 6: "glider", 7: "kite",
}


class RemoteIDParseError(Exception):
    """Raised when a Remote ID frame cannot be decoded."""


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class RemoteIDAdapter(SensorAdapter):
    modality = Modality.REMOTE_ID

    def __init__(self, source_id: str, config: Optional[RemoteIDConfig] = None) -> None:
        super().__init__(source_id)
        self.config = config or RemoteIDConfig()

    def process(self, sample: Union[bytes, Dict[str, Any]]) -> Optional[Detection]:
        fields = self._parse(sample)

        drone = GeoPoint(fields["drone_lat"], fields["drone_lon"], fields["drone_alt_m"])
        operator = GeoPoint(fields["operator_lat"], fields["operator_lon"])

        dist = _haversine_m(
            drone.lat, drone.lon,
            self.config.aoi_center_lat, self.config.aoi_center_lon,
        )
        if dist > self.config.aoi_radius_m:
            return self._count(None)

        # A decoded, standards-compliant broadcast inside the AOI is strong
        # single-modality evidence, but by policy it still cannot alert alone.
        confidence = max(self.config.min_confidence, fields["link_quality"])

        detection = Detection(
            modality=self.modality,
            source_id=self.source_id,
            timestamp=fields["timestamp"],
            confidence=confidence,
            kind="drone_broadcast",
            location=drone,
            attributes={
                "uav_type": fields["uav_type"],
                "operator_location": operator.to_dict(),
                "speed_mps": fields["speed_mps"],
                "range_to_aoi_center_m": round(dist, 1),
                "rid_standard": "ASTM F3411",
            },
        )
        return self._count(detection)

    # --- decode ------------------------------------------------------------
    def _parse(self, sample: Union[bytes, Dict[str, Any]]) -> Dict[str, Any]:
        if isinstance(sample, dict):
            return self._parse_dict(sample)
        if isinstance(sample, (bytes, bytearray)):
            return self._parse_frame(bytes(sample))
        raise RemoteIDParseError(f"unsupported sample type: {type(sample)!r}")

    def _parse_frame(self, raw: bytes) -> Dict[str, Any]:
        if len(raw) < _STRUCT.size:
            raise RemoteIDParseError("frame too short for Remote ID")
        try:
            (magic, uav_type, status, d_lat, d_lon, d_alt,
             o_lat, o_lon, speed) = _STRUCT.unpack(raw[: _STRUCT.size])
        except struct.error as exc:
            raise RemoteIDParseError(f"malformed Remote ID frame: {exc}") from exc
        if magic != _MAGIC:
            raise RemoteIDParseError("bad Remote ID magic")
        return {
            "timestamp": datetime.now(timezone.utc),
            "uav_type": _UA_TYPES.get(uav_type, "unknown"),
            "drone_lat": d_lat / 1e7,
            "drone_lon": d_lon / 1e7,
            "drone_alt_m": float(d_alt),
            "operator_lat": o_lat / 1e7,
            "operator_lon": o_lon / 1e7,
            "speed_mps": speed / 100.0,
            "link_quality": min(1.0, max(0.0, status / 100.0)),
        }

    def _parse_dict(self, d: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return {
                "timestamp": d.get("timestamp") or datetime.now(timezone.utc),
                "uav_type": d.get("uav_type", "unknown"),
                "drone_lat": float(d["drone_lat"]),
                "drone_lon": float(d["drone_lon"]),
                "drone_alt_m": float(d.get("drone_alt_m", 0.0)),
                "operator_lat": float(d["operator_lat"]),
                "operator_lon": float(d["operator_lon"]),
                "speed_mps": float(d.get("speed_mps", 0.0)),
                "link_quality": float(d.get("link_quality", 0.7)),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteIDParseError(f"invalid Remote ID dict: {exc}") from exc

    @staticmethod
    def encode(drone_lat: float, drone_lon: float, operator_lat: float,
               operator_lon: float, drone_alt_m: float = 50.0,
               uav_type: int = 2, link_quality: float = 0.8,
               speed_mps: float = 5.0) -> bytes:
        """Encode a Remote ID frame (used by the synthetic generator + tests)."""
        return _STRUCT.pack(
            _MAGIC, uav_type, int(link_quality * 100),
            int(drone_lat * 1e7), int(drone_lon * 1e7), int(drone_alt_m),
            int(operator_lat * 1e7), int(operator_lon * 1e7), int(speed_mps * 100),
        )
