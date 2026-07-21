"""Provenance chain + edge redaction invariants."""

from rudestorm.governance import EdgeRedactor, ProvenanceLog


def test_hash_chain_verifies():
    log = ProvenanceLog(path=None)
    log.append("detection", {"a": 1})
    log.append("detection", {"b": 2})
    log.append("threat_event", {"c": 3})
    assert log.verify() is True
    assert len(log.records) == 3


def test_tamper_breaks_chain():
    log = ProvenanceLog(path=None)
    log.append("detection", {"a": 1})
    log.append("detection", {"b": 2})
    # Tamper with a past record's payload.
    log.records[0].payload["a"] = 999
    log._records[0].payload["a"] = 999
    assert log.verify() is False


def test_deletion_breaks_chain():
    log = ProvenanceLog(path=None)
    log.append("detection", {"a": 1})
    log.append("detection", {"b": 2})
    del log._records[0]
    assert log.verify() is False


def test_redaction_marks_egress_safe_and_logs():
    log = ProvenanceLog(path=None)
    redactor = EdgeRedactor(log=log, enabled=True)
    desc = redactor.redact("frame-1", [{"type": "face", "bbox": [0, 0, 1, 1]}])
    assert desc["egress_safe"] is True
    assert desc["raw_pixels_transmitted"] is False
    assert desc["redacted_regions"] == 1
    assert log.records[-1].action == "edge_redaction"
