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
from datetime import datetime, timedelta, timezone
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
        try:
            self._validate_decoded_fields(fields)
        except (TypeError, ValueError) as exc:
            raise RemoteIDParseError(f"invalid decoded Remote ID fields: {exc}") from exc

        drone = GeoPoint(fields["drone_lat"], fields["drone_lon"], fields["drone_alt_m"])
        operator = None
        if fields["operator_lat"] is not None and fields["operator_lon"] is not None:
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
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise RemoteIDParseError(f"invalid confidence: {confidence!r}")

        detection = Detection(
            modality=self.modality,
            source_id=self.source_id,
            timestamp=fields["timestamp"],
            confidence=confidence,
            kind="drone_broadcast",
            location=drone,
            attributes={
                "uav_type": fields["uav_type"],
                "operator_location": operator.to_dict() if operator else None,
                "serial": fields.get("serial"),
                "speed_mps": fields["speed_mps"],
                "range_to_aoi_center_m": round(dist, 1),
                "rid_standard": "ASTM F3411",
                "source": fields.get("source", "decoded broadcast"),
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
            timestamp = d.get("timestamp")
            if timestamp is None:
                timestamp = datetime.now(timezone.utc)
            elif isinstance(timestamp, (int, float)):
                if not math.isfinite(float(timestamp)):
                    raise ValueError("timestamp must be finite")
                timestamp = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
            elif not isinstance(timestamp, datetime):
                raise TypeError("timestamp must be datetime or Unix seconds")
            elif timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)

            operator_lat = d.get("operator_lat")
            operator_lon = d.get("operator_lon")
            if (operator_lat is None) != (operator_lon is None):
                raise ValueError("operator_lat and operator_lon must be provided together")

            fields = {
                "timestamp": timestamp,
                "uav_type": d.get("uav_type", "unknown"),
                "drone_lat": float(d["drone_lat"]),
                "drone_lon": float(d["drone_lon"]),
                "drone_alt_m": float(d.get("drone_alt_m", 0.0)),
                "operator_lat": float(operator_lat) if operator_lat is not None else None,
                "operator_lon": float(operator_lon) if operator_lon is not None else None,
                "speed_mps": float(d.get("speed_mps", 0.0)),
                "link_quality": float(d.get("link_quality", 0.7)),
                "serial": d.get("serial"),
                "source": d.get("source", "decoded broadcast"),
            }
            return fields
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise RemoteIDParseError(f"invalid Remote ID dict: {exc}") from exc

    @staticmethod
    def _validate_decoded_fields(fields: Dict[str, Any]) -> None:
        numeric = (
            "drone_lat", "drone_lon", "drone_alt_m", "speed_mps", "link_quality",
        )
        for name in numeric:
            if not math.isfinite(fields[name]):
                raise ValueError(f"{name} must be finite")
        if not -90.0 <= fields["drone_lat"] <= 90.0:
            raise ValueError("drone_lat must be in [-90, 90]")
        if not -180.0 <= fields["drone_lon"] <= 180.0:
            raise ValueError("drone_lon must be in [-180, 180]")
        if fields["operator_lat"] is not None:
            if not math.isfinite(fields["operator_lat"]) or not -90.0 <= fields["operator_lat"] <= 90.0:
                raise ValueError("operator_lat must be finite and in [-90, 90]")
            if not math.isfinite(fields["operator_lon"]) or not -180.0 <= fields["operator_lon"] <= 180.0:
                raise ValueError("operator_lon must be finite and in [-180, 180]")
        if not 0.0 <= fields["link_quality"] <= 1.0:
            raise ValueError("link_quality must be in [0, 1]")

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


class ReplayedRemoteIDAdapter(RemoteIDAdapter):
    """Replay decoded OpenDroneID records through the production AOI gate.

    The reference simulator may omit operator coordinates. That absence is
    preserved rather than filled with fabricated data. Relative timestamps are
    anchored to ``start`` before the record enters the production adapter.
    """

    def __init__(self, source_id: str, config: Optional[RemoteIDConfig] = None,
                 start: Optional[datetime] = None) -> None:
        super().__init__(source_id, config)
        self.start = start or datetime.now(timezone.utc)
        if self.start.tzinfo is None:
            self.start = self.start.replace(tzinfo=timezone.utc)

    def process(self, sample: Dict[str, Any]) -> Optional[Detection]:
        try:
            offset_s = float(sample["timestamp"])
            if not math.isfinite(offset_s):
                raise ValueError("timestamp must be finite")
            normalized = {
                "timestamp": self.start + timedelta(seconds=offset_s),
                "drone_lat": sample["lat"],
                "drone_lon": sample["lon"],
                "drone_alt_m": sample.get("alt_m", 0.0),
                "operator_lat": sample.get("operator_lat"),
                "operator_lon": sample.get("operator_lon"),
                "speed_mps": sample.get("speed_mps", 0.0),
                "link_quality": sample.get("link_quality", 0.95),
                "uav_type": sample.get("uav_type", "unknown"),
                "serial": sample.get("serial"),
                "source": sample.get(
                    "source",
                    "opendroneid-core-c simulator (encode/decode round trip)",
                ),
            }
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise RemoteIDParseError(f"invalid replayed Remote ID record: {exc}") from exc
        return super().process(normalized)
