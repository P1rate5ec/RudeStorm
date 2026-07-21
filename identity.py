"""Post-fusion Remote ID triage for confirmed UAS events.

Identity triage never creates, upgrades, or suppresses an alert. It labels an
already-confirmed event based on whether an operational Remote ID receiver saw a
time-aligned broadcast:

* ``IDENTIFIED_TRACK``: a matching cooperative broadcast exists.
* ``UNIDENTIFIED_DRONE``: the receiver was operational but heard no match.
* ``IDENTITY_UNAVAILABLE``: the Remote ID source was unavailable, so silence
  cannot honestly be interpreted as a non-cooperative aircraft.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Sequence

from rudestorm.events import ThreatEvent

IDENTIFIED_TRACK = "IDENTIFIED_TRACK"
UNIDENTIFIED_DRONE = "UNIDENTIFIED_DRONE"
IDENTITY_UNAVAILABLE = "IDENTITY_UNAVAILABLE"
DEFAULT_TOLERANCE_S = 1.0


@dataclass(frozen=True)
class IdentityResult:
    status: str
    remote_id: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity_status": self.status,
            "remote_id": self.remote_id,
            "reason": self.reason,
        }


def _record_seconds(value: Any, start: Optional[datetime]) -> float:
    if isinstance(value, datetime):
        if start is not None:
            return (value - start).total_seconds()
        return value.timestamp()
    seconds = float(value)
    if not math.isfinite(seconds):
        raise ValueError("Remote ID timestamp must be finite")
    return seconds


def resolve_identity(
    event: ThreatEvent,
    rid_records: Optional[Sequence[Dict[str, Any]]],
    tolerance_s: float = DEFAULT_TOLERANCE_S,
    start: Optional[datetime] = None,
) -> IdentityResult:
    """Match a confirmed event against decoded Remote ID records.

    ``rid_records=None`` means the receiver or stream was unavailable. An empty
    sequence means the receiver was operational but observed no broadcasts.
    Relative replay timestamps use ``start``; live records may use datetimes or
    Unix seconds.
    """
    if not math.isfinite(tolerance_s) or tolerance_s < 0:
        raise ValueError("tolerance_s must be finite and non-negative")
    if rid_records is None:
        return IdentityResult(
            IDENTITY_UNAVAILABLE,
            reason="Remote ID source unavailable; absence is not threat evidence",
        )

    event_t = (
        (event.timestamp - start).total_seconds()
        if start is not None
        else event.timestamp.timestamp()
    )
    candidates = []
    for record in rid_records:
        if "timestamp" not in record:
            continue
        try:
            record_t = _record_seconds(record["timestamp"], start)
        except (TypeError, ValueError, OverflowError):
            continue
        delta = abs(record_t - event_t)
        if delta <= tolerance_s:
            candidates.append((delta, record))

    if candidates:
        _, match = min(candidates, key=lambda item: item[0])
        return IdentityResult(IDENTIFIED_TRACK, dict(match))
    return IdentityResult(
        UNIDENTIFIED_DRONE,
        reason="receiver operational; no time-aligned Remote ID broadcast",
    )
