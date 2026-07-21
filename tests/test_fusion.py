"""Fusion engine: the corroboration rule is the thing that must hold."""

from datetime import datetime, timedelta, timezone

import pytest

from rudestorm.config import FusionConfig
from rudestorm.events import Detection, GeoPoint, Modality
from rudestorm.fusion import FusionEngine, noisy_or


def _det(modality, ts, conf=0.8, source="s", location=None):
    return Detection(modality=modality, source_id=source, timestamp=ts,
                     confidence=conf, kind="k", location=location)


def test_single_modality_never_alerts():
    engine = FusionEngine(FusionConfig(window_seconds=5, min_modalities=2))
    t0 = datetime.now(timezone.utc)
    events = engine.add(_det(Modality.REMOTE_ID, t0, conf=0.99,
                             location=GeoPoint(44.6488, -63.5752)))
    assert events == []


def test_corroboration_only_pair_does_not_alert():
    # Acoustic + vibration are both corroboration-only; must not stand up alone.
    engine = FusionEngine(FusionConfig(window_seconds=5, min_modalities=2))
    t0 = datetime.now(timezone.utc)
    engine.add(_det(Modality.ACOUSTIC, t0, conf=0.9))
    events = engine.add(_det(Modality.VIBRATION, t0, conf=0.9))
    assert events == []


def test_two_modalities_in_window_alert():
    engine = FusionEngine(FusionConfig(window_seconds=5, min_modalities=2,
                                       alert_confidence=0.6))
    t0 = datetime.now(timezone.utc)
    engine.add(_det(Modality.REMOTE_ID, t0, conf=0.8,
                    location=GeoPoint(44.6488, -63.5752)))
    events = engine.add(_det(Modality.ACOUSTIC, t0 + timedelta(seconds=1), conf=0.7))
    assert len(events) == 1
    ev = events[0]
    assert ev.threat_class == "uas_cooperative_intrusion"
    assert Modality.REMOTE_ID in ev.modalities and Modality.ACOUSTIC in ev.modalities
    assert ev.geolocation is not None  # geolocated from Remote ID


def test_detections_outside_window_do_not_correlate():
    engine = FusionEngine(FusionConfig(window_seconds=2, min_modalities=2))
    t0 = datetime.now(timezone.utc)
    engine.add(_det(Modality.REMOTE_ID, t0, conf=0.9,
                    location=GeoPoint(44.6488, -63.5752)))
    events = engine.add(_det(Modality.ACOUSTIC, t0 + timedelta(seconds=10), conf=0.9))
    assert events == []


def test_noisy_or_rewards_corroboration():
    assert noisy_or([0.5]) == pytest.approx(0.5)
    assert noisy_or([0.5, 0.5]) == pytest.approx(0.75)
    assert noisy_or([0.8, 0.7]) > 0.9
