"""Self-sourced synthetic data generators.

Component 1a provides NO DND data and NO government-furnished property, so the
project must generate its own evaluation data. These generators produce labelled
scenarios — background vs. a cooperative-drone incursion vs. a perimeter
intrusion — for the three passive modalities, so the whole pipeline can be
exercised and its false-alarm-suppression measured offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import numpy as np

from rudestorm.adapters.acoustic import AcousticSample
from rudestorm.adapters.csi_presence import CSISample
from rudestorm.adapters.remote_id import RemoteIDAdapter


@dataclass
class TimedSample:
    """A raw sample tagged with modality + emission time for the pipeline."""

    modality: str
    source_id: str
    timestamp: datetime
    payload: object
    label: str  # ground-truth label for evaluation


def _rng(seed: Optional[int]) -> np.random.Generator:
    return np.random.default_rng(seed)


def make_csi(moving: bool, antennas: int = 3, subcarriers: int = 56,
             seed: Optional[int] = None,
             timestamp: Optional[datetime] = None) -> CSISample:
    """Generate a CSI frame. `moving=True` injects correlated motion variance."""
    rng = _rng(seed)
    base = 0.5 + 0.05 * rng.standard_normal((antennas, subcarriers))
    if moving:
        # A moving body perturbs a contiguous band of subcarriers across antennas.
        band = slice(rng.integers(0, subcarriers // 2), subcarriers)
        base[:, band] += 0.4 * rng.standard_normal((antennas, subcarriers - band.start))
    amplitude = np.abs(base)
    phase = np.angle(np.exp(1j * (rng.standard_normal((antennas, subcarriers)))))
    return CSISample(amplitude=amplitude, phase=phase, timestamp=timestamp)


def make_acoustic(drone: bool, sample_rate: int = 16000, dur_s: float = 0.25,
                  seed: Optional[int] = None,
                  timestamp: Optional[datetime] = None) -> AcousticSample:
    """Generate an audio frame. `drone=True` adds rotor harmonics in-band."""
    rng = _rng(seed)
    n = int(sample_rate * dur_s)
    t = np.arange(n) / sample_rate
    wf = 0.05 * rng.standard_normal(n)
    if drone:
        for f0 in (220.0, 440.0, 1200.0, 2400.0):
            wf += 0.3 * np.sin(2 * np.pi * f0 * t)
    else:
        # Ambient low-frequency city rumble (out of the UAV band emphasis).
        wf += 0.2 * np.sin(2 * np.pi * 60.0 * t)
    return AcousticSample(waveform=wf, sample_rate=sample_rate, timestamp=timestamp)


def make_remote_id(inside_aoi: bool,
                   center: Tuple[float, float] = (44.6488, -63.5752),
                   seed: Optional[int] = None) -> bytes:
    """Encode a Remote ID frame near (inside) or far from the area of interest."""
    rng = _rng(seed)
    offset = 0.005 if inside_aoi else 0.2  # ~0.5 km vs ~20 km
    d_lat = center[0] + offset * rng.standard_normal()
    d_lon = center[1] + offset * rng.standard_normal()
    o_lat = d_lat + 0.002 * rng.standard_normal()
    o_lon = d_lon + 0.002 * rng.standard_normal()
    return RemoteIDAdapter.encode(
        drone_lat=d_lat, drone_lon=d_lon,
        operator_lat=o_lat, operator_lon=o_lon,
        drone_alt_m=60.0, uav_type=2, link_quality=0.85, speed_mps=8.0,
    )


def scenario_cooperative_uas(seed: int = 0,
                             start: Optional[datetime] = None) -> List[TimedSample]:
    """A cooperative drone enters the AOI; acoustic corroborates within window."""
    start = start or datetime.now(timezone.utc)
    return [
        TimedSample("remote_id", "mote-rf-1", start,
                    make_remote_id(inside_aoi=True, seed=seed), "uas"),
        TimedSample("acoustic", "mote-mic-1", start + timedelta(seconds=1.0),
                    make_acoustic(drone=True, seed=seed + 1), "uas"),
    ]


def scenario_false_alarm_single(seed: int = 0,
                                 start: Optional[datetime] = None) -> List[TimedSample]:
    """Acoustic drone-like sound alone — must NOT alert (corroboration-only)."""
    start = start or datetime.now(timezone.utc)
    return [
        TimedSample("acoustic", "mote-mic-1", start,
                    make_acoustic(drone=True, seed=seed), "background"),
    ]


def scenario_perimeter_intrusion(seed: int = 0,
                                  start: Optional[datetime] = None) -> List[TimedSample]:
    """Motion (CSI) + acoustic corroboration at a perimeter."""
    start = start or datetime.now(timezone.utc)
    return [
        TimedSample("wifi_csi", "mote-csi-1", start,
                    make_csi(moving=True, seed=seed), "intrusion"),
        TimedSample("wifi_csi", "mote-csi-1", start + timedelta(seconds=0.5),
                    make_csi(moving=True, seed=seed + 5), "intrusion"),
        TimedSample("acoustic", "mote-mic-2", start + timedelta(seconds=1.2),
                    make_acoustic(drone=True, seed=seed + 2), "intrusion"),
    ]
