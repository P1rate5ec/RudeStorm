"""Adapter-level checks: Remote ID decode round-trip, CSI honesty, acoustic."""

import numpy as np
import pytest

from rudestorm.adapters import (
    AcousticAdapter,
    CSIPresenceAdapter,
    RemoteIDAdapter,
    RemoteIDParseError,
    ReplayedRemoteIDAdapter,
)
from rudestorm.adapters.acoustic import AcousticSample
from rudestorm.config import RemoteIDConfig
from rudestorm.events import Modality
from rudestorm import synthetic


def test_remote_id_roundtrip_and_geofence():
    cfg = RemoteIDConfig(aoi_center_lat=44.6488, aoi_center_lon=-63.5752,
                         aoi_radius_m=3000.0)
    adapter = RemoteIDAdapter("mote-rf-1", cfg)
    frame = RemoteIDAdapter.encode(44.6490, -63.5750, 44.6495, -63.5748)
    det = adapter.process(frame)
    assert det is not None
    assert det.modality == Modality.REMOTE_ID
    assert det.location is not None
    assert "operator_location" in det.attributes


def test_remote_id_outside_aoi_suppressed():
    adapter = RemoteIDAdapter("mote-rf-1", RemoteIDConfig())
    frame = synthetic.make_remote_id(inside_aoi=False, seed=7)
    assert adapter.process(frame) is None


def test_remote_id_rejects_garbage():
    adapter = RemoteIDAdapter("mote-rf-1")
    with pytest.raises(RemoteIDParseError):
        adapter.process(b"not a valid frame")


def test_replayed_remote_id_uses_production_geofence_without_operator_location():
    cfg = RemoteIDConfig(aoi_center_lat=44.6488, aoi_center_lon=-63.5752,
                         aoi_radius_m=3000.0)
    adapter = ReplayedRemoteIDAdapter("mote-rf-1", cfg)
    det = adapter.process({
        "timestamp": 0.0,
        "serial": "SYNTH-001",
        "lat": 44.6490,
        "lon": -63.5750,
        "alt_m": 50.0,
        "speed_mps": 8.0,
    })
    assert det is not None
    assert det.attributes["operator_location"] is None
    assert det.attributes["serial"] == "SYNTH-001"
    assert det.attributes["range_to_aoi_center_m"] < 3000.0


def test_replayed_remote_id_outside_aoi_is_suppressed():
    adapter = ReplayedRemoteIDAdapter("mote-rf-1", RemoteIDConfig())
    assert adapter.process({
        "timestamp": 0.0,
        "serial": "SYNTH-PORTLAND",
        "lat": 45.5393092,
        "lon": -122.9662894,
    }) is None


def test_remote_id_rejects_non_finite_input():
    adapter = ReplayedRemoteIDAdapter("mote-rf-1", RemoteIDConfig())
    with pytest.raises(RemoteIDParseError):
        adapter.process({
            "timestamp": 0.0,
            "serial": "SYNTH-NAN",
            "lat": float("nan"),
            "lon": -63.5752,
        })


def test_replayed_remote_id_wraps_timestamp_overflow():
    adapter = ReplayedRemoteIDAdapter("mote-rf-1", RemoteIDConfig())
    with pytest.raises(RemoteIDParseError):
        adapter.process({
            "timestamp": 1e18,
            "serial": "SYNTH-OVERFLOW",
            "lat": 44.6488,
            "lon": -63.5752,
        })


def test_csi_static_scene_no_presence():
    adapter = CSIPresenceAdapter("mote-csi-1")
    for i in range(20):
        det = adapter.process(synthetic.make_csi(moving=False, seed=i))
    assert det is None  # a still scene should not declare presence


def test_csi_reports_presence_not_identity():
    adapter = CSIPresenceAdapter("mote-csi-1")
    det = None
    for i in range(30):
        det = adapter.process(synthetic.make_csi(moving=True, seed=100 + i))
        if det is not None:
            break
    assert det is not None
    assert det.kind == "presence"
    # Honest envelope: no identity/pose fields are ever attached.
    assert "identity" not in det.attributes and "pose" not in det.attributes


def test_acoustic_is_corroboration_only():
    adapter = AcousticAdapter("mote-mic-1")
    det = adapter.process(synthetic.make_acoustic(drone=True, seed=1))
    assert det is not None
    assert det.attributes["role"] == "corroboration_only"
