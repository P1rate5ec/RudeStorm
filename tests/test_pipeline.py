"""End-to-end pipeline behavior on labelled synthetic scenarios."""

from datetime import datetime, timezone

from rudestorm.adapters import AcousticAdapter, CSIPresenceAdapter, RemoteIDAdapter
from rudestorm.config import RudestormConfig
from rudestorm.governance import ProvenanceLog
from rudestorm.pipeline import Pipeline
from rudestorm import synthetic


def _pipeline():
    cfg = RudestormConfig()
    p = Pipeline(config=cfg, provenance=ProvenanceLog(path=None))
    p.register(RemoteIDAdapter("mote-rf-1", cfg.remote_id))
    p.register(AcousticAdapter("mote-mic-1", cfg.acoustic))
    p.register(AcousticAdapter("mote-mic-2", cfg.acoustic))
    p.register(CSIPresenceAdapter("mote-csi-1", cfg.csi))
    return p


def test_cooperative_uas_scenario_alerts():
    p = _pipeline()
    events = []
    for s in synthetic.scenario_cooperative_uas(seed=1):
        events.extend(p.ingest(s.modality, s.source_id, s.payload))
    assert len(events) >= 1
    assert events[0].threat_class == "uas_cooperative_intrusion"
    assert events[0].provenance_hash is not None
    assert p.stats()["provenance_verified"] is True


def test_single_acoustic_scenario_does_not_alert():
    p = _pipeline()
    events = []
    for s in synthetic.scenario_false_alarm_single(seed=2):
        events.extend(p.ingest(s.modality, s.source_id, s.payload))
    assert events == []


def test_perimeter_intrusion_scenario_alerts():
    p = _pipeline()
    events = []
    for s in synthetic.scenario_perimeter_intrusion(seed=3):
        events.extend(p.ingest(s.modality, s.source_id, s.payload))
    assert len(events) >= 1
    assert events[0].threat_class == "presence_intrusion"
