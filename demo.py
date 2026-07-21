"""Runnable end-to-end demonstration.

    python -m rudestorm.demo

Runs three synthetic scenarios through the full middleware and prints the
operator JSON events plus a provenance summary. Shows the two properties that
matter for evaluation: (1) a lone drone-like sound produces NO alert
(false-alarm suppression), and (2) corroborated modalities produce a signed,
geolocated operator event.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from rudestorm.adapters import AcousticAdapter, CSIPresenceAdapter, RemoteIDAdapter
from rudestorm.config import RudestormConfig
from rudestorm.governance import EdgeRedactor, ProvenanceLog
from rudestorm.pipeline import Pipeline
from rudestorm import synthetic


def build_pipeline(config: RudestormConfig, provenance: ProvenanceLog) -> Pipeline:
    pipeline = Pipeline(config=config, provenance=provenance,
                        sink=lambda ev: None)
    pipeline.register(RemoteIDAdapter("mote-rf-1", config.remote_id))
    pipeline.register(AcousticAdapter("mote-mic-1", config.acoustic))
    pipeline.register(AcousticAdapter("mote-mic-2", config.acoustic))
    pipeline.register(CSIPresenceAdapter("mote-csi-1", config.csi))
    return pipeline


def run_scenario(title: str, samples, config, provenance) -> None:
    pipeline = build_pipeline(config, provenance)
    print(f"\n{'=' * 70}\nSCENARIO: {title}\n{'=' * 70}")
    events = []
    for s in samples:
        events.extend(pipeline.ingest(s.modality, s.source_id, s.payload))
    if not events:
        print("  -> NO operator alert (corroboration rule not satisfied). Correct.")
    for ev in events:
        print(f"  -> ALERT [{ev.threat_class}] confidence={ev.confidence:.2f} "
              f"modalities={[m.value for m in ev.modalities]}")
        print(json.dumps(ev.to_dict(), indent=2))


def main() -> None:
    config = RudestormConfig()
    provenance = ProvenanceLog(path=None)  # in-memory for the demo
    start = datetime.now(timezone.utc)

    # Edge redaction demo: a CCTV frame is redacted before egress.
    redactor = EdgeRedactor(log=provenance, enabled=True)
    desc = redactor.redact("cam-07-frame-0001",
                           [{"type": "face", "bbox": [10, 20, 50, 80]},
                            {"type": "plate", "bbox": [120, 200, 60, 25]}])
    print(f"Edge redaction: {desc}")

    run_scenario("Cooperative UAS incursion (Remote ID + acoustic)",
                 synthetic.scenario_cooperative_uas(seed=1, start=start),
                 config, provenance)
    run_scenario("Lone drone-like sound (acoustic only -> must NOT alert)",
                 synthetic.scenario_false_alarm_single(seed=2, start=start),
                 config, provenance)
    run_scenario("Perimeter intrusion (WiFi-CSI motion + acoustic)",
                 synthetic.scenario_perimeter_intrusion(seed=3, start=start),
                 config, provenance)

    print(f"\n{'=' * 70}\nPROVENANCE\n{'=' * 70}")
    print(f"  records:  {len(provenance.records)}")
    print(f"  head:     {provenance.head[:16]}...")
    print(f"  verified: {provenance.verify()}  (append-only hash chain intact)")


if __name__ == "__main__":
    main()
