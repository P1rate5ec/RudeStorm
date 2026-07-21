"""End-to-end pipeline: adapters -> fusion -> provenance -> operator JSON.

The pipeline routes each raw sample to the adapter registered for its modality,
feeds resulting detections into the fusion engine, hash-chains every detection
and emitted event into the provenance log, and hands finished ThreatEvents to an
operator sink (stdout JSON by default; swap for MQTT/NATS in deployment).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from rudestorm.adapters.base import SensorAdapter
from rudestorm.config import RudestormConfig
from rudestorm.events import Detection, ThreatEvent
from rudestorm.fusion import CorrelationProfile, FusionEngine
from rudestorm.governance import ProvenanceLog

OperatorSink = Callable[[ThreatEvent], None]


class Pipeline:
    def __init__(self, config: Optional[RudestormConfig] = None,
                 profiles: Optional[List[CorrelationProfile]] = None,
                 sink: Optional[OperatorSink] = None,
                 provenance: Optional[ProvenanceLog] = None) -> None:
        self.config = config or RudestormConfig()
        self.fusion = FusionEngine(self.config.fusion, profiles=profiles)
        self.provenance = provenance or ProvenanceLog(self.config.governance.audit_log_path)
        self.sink = sink
        self._adapters: Dict[str, SensorAdapter] = {}
        self.emitted: List[ThreatEvent] = []

    def register(self, adapter: SensorAdapter) -> "Pipeline":
        """Register an adapter, keyed by "<modality>:<source_id>"."""
        self._adapters[self._key(adapter.modality.value, adapter.source_id)] = adapter
        return self

    @staticmethod
    def _key(modality: str, source_id: str) -> str:
        return f"{modality}:{source_id}"

    def ingest(self, modality: str, source_id: str, sample: Any) -> List[ThreatEvent]:
        """Ingest one raw sample; return any operator events it produced."""
        adapter = self._adapters.get(self._key(modality, source_id))
        if adapter is None:
            raise KeyError(f"no adapter for {modality}:{source_id}")

        detection = adapter.process(sample)
        if detection is None:
            return []

        self.provenance.append("detection", detection.to_dict())
        events = self.fusion.add(detection)
        for event in events:
            record = self.provenance.append("threat_event", event.to_dict())
            event.provenance_hash = record.this_hash
            self.emitted.append(event)
            if self.sink is not None:
                self.sink(event)
        return events

    def stats(self) -> Dict[str, Any]:
        return {
            "adapters": [a.stats for a in self._adapters.values()],
            "events_emitted": len(self.emitted),
            "provenance_head": self.provenance.head,
            "provenance_verified": self.provenance.verify(),
            "fusion_window_size": self.fusion.window_size,
        }
