"""Remote ID triage labels confirmed events without changing alert gating."""

from datetime import datetime, timedelta, timezone

from rudestorm.events import Detection, Modality, ThreatEvent
from rudestorm.identity import (
    IDENTIFIED_TRACK,
    IDENTITY_UNAVAILABLE,
    UNIDENTIFIED_DRONE,
    resolve_identity,
)


def _confirmed_event(start: datetime, offset_s: float) -> ThreatEvent:
    ts = start + timedelta(seconds=offset_s)
    contributing = [
        Detection(Modality.ACOUSTIC, "mic-1", ts, 0.9, "acoustic_uav"),
        Detection(Modality.VIDEO, "cam-1", ts, 0.8, "visual_uav"),
    ]
    return ThreatEvent(
        threat_class="uas_audio_visual_confirmed",
        confidence=0.95,
        timestamp=ts,
        window_seconds=4.0,
        contributing=contributing,
    )


def test_time_aligned_broadcast_identifies_track():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    event = _confirmed_event(start, 8.0)
    result = resolve_identity(
        event,
        [{"timestamp": 7.5, "serial": "SYNTH-001"}],
        tolerance_s=1.0,
        start=start,
    )
    assert result.status == IDENTIFIED_TRACK
    assert result.remote_id["serial"] == "SYNTH-001"


def test_operational_receiver_with_no_match_is_unidentified():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    event = _confirmed_event(start, 8.0)
    result = resolve_identity(event, [], start=start)
    assert result.status == UNIDENTIFIED_DRONE


def test_unavailable_receiver_is_not_treated_as_non_cooperative_drone():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    event = _confirmed_event(start, 8.0)
    result = resolve_identity(event, None, start=start)
    assert result.status == IDENTITY_UNAVAILABLE


def test_malformed_records_do_not_create_identity_match():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    event = _confirmed_event(start, 8.0)
    result = resolve_identity(
        event,
        [{"serial": "NO-TIME"}, {"timestamp": float("nan"), "serial": "NAN"}],
        start=start,
    )
    assert result.status == UNIDENTIFIED_DRONE
