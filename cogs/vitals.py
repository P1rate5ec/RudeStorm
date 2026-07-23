"""Respiration and cardiac extraction from CSI phase.

Chain, per modality:

    raw CSI phase (wrapped)
      -> per-frame linear detrend across subcarriers   [removes CFO/SFO/PDD]
      -> unwrap along time
      -> most-responsive subcarrier selection (once per window, not per frame)
      -> dominant-frequency precondition
      -> zero-phase Butterworth bandpass
      -> zero-crossing rate -> BPM

Two gates keep this from manufacturing readings out of noise, and both were
added because the test suite caught the cog inventing them:

**Dominant frequency.** A bandpass filter always returns something that
zero-crosses. In-band energy alone cannot tell respiration from the residue of a
strong out-of-band source, so the largest spectral peak of the window must
itself lie in band before any rate is reported. A 2 Hz fan yields silence, not a
16 BPM reading.

**Circular variance** (breathing only). A chest wall produces a narrow, coherent
phase excursion; walking or an HVAC vent produces a broad one. This is measured
on the sanitized series the estimate is actually computed from — *not* on a
frame-averaged raw phase, which cancels a frequency-selective body term and so
inspects nothing.

A note on the cardiac band. The stated capability is 40-120 BPM, but a 0.8 Hz
low cutoff passes nothing below 48 BPM — the band and the range disagree at the
bottom end. The filter is the authority here, so `HeartRateCog` reports
`CARDIAC_BPM_RANGE = (48, 120)` and declares the gap in its manifest limits
rather than claiming a bradycardic reading it structurally cannot produce.
Widening `CARDIAC_BAND_HZ` to 0.67 Hz recovers the full 40 BPM floor at the cost
of admitting more respiration harmonic into the cardiac estimate.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Optional, Tuple

import numpy as np
import scipy.signal

from rudestorm.adapters.csi_presence import CSISample
from rudestorm.cogs.base import (
    Capability,
    Cog,
    CogCategory,
    CogManifest,
    NodeProfile,
    PrivacyClass,
)
from rudestorm.events import Detection, Modality

RESPIRATION_BAND_HZ: Tuple[float, float] = (0.1, 0.5)
RESPIRATION_BPM_RANGE: Tuple[int, int] = (6, 30)

CARDIAC_BAND_HZ: Tuple[float, float] = (0.8, 2.0)
CARDIAC_BPM_RANGE: Tuple[int, int] = (48, 120)

#: Below this many buffered samples, no estimate is emitted at all. Respiration
#: at 6 BPM has a 10 s period; three cycles is the minimum for a stable
#: zero-crossing count, so the buffer must span >= 30 s of signal.
MIN_WINDOW_SECONDS = 30.0

#: Circular variance above this means the phase excursion is too broad to be a
#: chest wall. Empirical, and the first thing to retune per deployment.
MAX_CIRCULAR_VARIANCE = 0.65

#: Minimum fraction of window energy that must lie inside the physiological band.
#: Without this floor, a strong out-of-band source (a fan at 2 Hz, a walking
#: subject) is attenuated by the filter but its residual noise still zero-crosses
#: at a plausible-looking rate — producing a confident-sounding respiration
#: reading from a signal with ~1% in-band energy. A rate estimate is only
#: meaningful if the band actually contains the signal.
MIN_IN_BAND_POWER_RATIO = 0.10


def sanitize_phase(phase: np.ndarray) -> np.ndarray:
    """Remove the linear phase ramp across subcarriers.

    Commodity NICs contribute carrier frequency offset, sampling frequency
    offset and packet detection delay, all of which appear as a per-frame linear
    ramp across subcarrier index. Fitting and subtracting it leaves the
    body-induced component. Operates per antenna row.
    """
    if phase.ndim != 2:
        raise ValueError(f"phase must be 2D (antennas x subcarriers), got {phase.shape}")
    n_sub = phase.shape[1]
    if n_sub < 2:
        return phase - phase.mean(axis=1, keepdims=True)

    idx = np.arange(n_sub, dtype=float)
    unwrapped = np.unwrap(phase, axis=1)
    # Least-squares line per antenna, vectorised.
    idx_centered = idx - idx.mean()
    denom = float(np.sum(idx_centered ** 2)) or 1.0
    slope = (unwrapped - unwrapped.mean(axis=1, keepdims=True)) @ idx_centered / denom
    ramp = slope[:, None] * idx_centered[None, :]
    return unwrapped - unwrapped.mean(axis=1, keepdims=True) - ramp


def circular_variance(angles: np.ndarray) -> float:
    """1 - |mean resultant vector|. 0 = perfectly coherent, 1 = uniform."""
    if angles.size == 0:
        return 1.0
    resultant = np.abs(np.mean(np.exp(1j * angles)))
    return float(np.clip(1.0 - resultant, 0.0, 1.0))


def bandpass(signal: np.ndarray, fs: float, band: Tuple[float, float]) -> np.ndarray:
    """Zero-phase 4th-order Butterworth bandpass.

    Zero-phase (filtfilt) matters because a causal filter's group delay would
    shift the zero crossings and bias the BPM estimate.
    """
    low, high = band
    nyquist = fs / 2.0
    if high >= nyquist:
        raise ValueError(
            f"band upper edge {high} Hz is at or above Nyquist ({nyquist} Hz); "
            f"raise the CSI sampling rate above {2 * high} Hz"
        )
    sos = scipy.signal.butter(
        4, [low / nyquist, high / nyquist], btype="bandpass", output="sos"
    )
    # filtfilt doubles the effective order and needs padlen*3 samples.
    if signal.size <= 18:
        return np.zeros_like(signal)
    return scipy.signal.sosfiltfilt(sos, signal)


def dominant_frequency(signal: np.ndarray, fs: float) -> float:
    """Frequency of the largest spectral peak, ignoring DC.

    Used as a precondition on any rate estimate: a bandpass filter will always
    hand back *something* that zero-crosses, so in-band energy alone cannot
    distinguish respiration from the residue of a strong out-of-band source. If
    the dominant motion in the window is a 2 Hz fan, there is no respiration
    reading to report, however clean the filtered residue looks.
    """
    if signal.size < 4:
        return 0.0
    windowed = signal * np.hanning(signal.size)
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(signal.size, d=1.0 / fs)
    spectrum[0] = 0.0  # ignore DC
    return float(freqs[int(np.argmax(spectrum))])


def zero_crossing_bpm(signal: np.ndarray, fs: float) -> float:
    """BPM from zero-crossing count. Two crossings per cycle."""
    if signal.size < 2:
        return 0.0
    centered = signal - float(np.mean(signal))
    crossings = int(np.count_nonzero(np.diff(np.signbit(centered))))
    duration_s = signal.size / fs
    if duration_s <= 0:
        return 0.0
    return (crossings / 2.0) / duration_s * 60.0


class _PhaseVitalsCog(Cog):
    """Shared buffering and estimation for the two vitals cogs."""

    band: Tuple[float, float]
    bpm_range: Tuple[int, int]
    kind: str
    require_coherence: bool = False

    def __init__(self, source_id: str, sampling_rate: float = 100.0) -> None:
        super().__init__(source_id)
        self.fs = sampling_rate
        self._buffer: Deque[np.ndarray] = deque(maxlen=self._buffer_size())

    def _buffer_size(self) -> int:
        return max(64, int(MIN_WINDOW_SECONDS * self.fs))

    def on_load(self, node: NodeProfile) -> None:
        """Shrink the window on memory-constrained nodes."""
        if node.ram_mb < 1024:
            self._buffer = deque(self._buffer, maxlen=min(len(self._buffer) or 1, 2048))

    @staticmethod
    def _select_series(window: np.ndarray) -> np.ndarray:
        """Pick the single most responsive subcarrier across the whole window.

        Selection must be made once over the buffered window, not per frame.
        A per-frame argmax lets consecutive samples come from different
        subcarriers, and the resulting switching transients dominate the
        low-frequency band we are trying to measure — it biases the recovered
        rate by several BPM.
        """
        variance = window.var(axis=0)
        return window[:, int(np.argmax(variance))]

    def process(self, sample: CSISample) -> Optional[Detection]:
        # Collapse antennas, keep subcarriers: selection happens over the window.
        self._buffer.append(sanitize_phase(sample.phase).mean(axis=0))

        if len(self._buffer) < self._buffer.maxlen:
            return None  # still filling the window; say nothing

        window = np.asarray(self._buffer, dtype=float)
        series = self._select_series(window)

        # Coherence is measured on the sanitized series we actually estimate
        # from, not on a running mean of raw phase. The raw-phase mean is a bad
        # proxy: a frequency-selective body term is mean-zero across
        # subcarriers, so averaging over the frame cancels exactly the
        # excursion the gate is meant to inspect.
        if self.require_coherence and circular_variance(series) > MAX_CIRCULAR_VARIANCE:
            return None  # excursion too broad to be a chest wall

        series = series - float(np.mean(series))

        # Precondition: the strongest motion in this window must itself be in
        # band. Otherwise we are measuring filter residue, not a chest wall.
        peak_hz = dominant_frequency(series, self.fs)
        if not self.band[0] <= peak_hz <= self.band[1]:
            return None

        filtered = bandpass(series, self.fs, self.band)
        bpm = zero_crossing_bpm(filtered, self.fs)

        lo, hi = self.bpm_range
        if not lo <= bpm <= hi:
            return None  # out of physiological band -> not a person, no claim

        # Confidence from in-band power ratio: how much of the signal's energy
        # actually lives in the physiological band versus everywhere else.
        total_power = float(np.sum(series ** 2)) or 1.0
        band_power = float(np.sum(filtered ** 2))
        confidence = float(np.clip(band_power / total_power, 0.0, 1.0))

        if confidence < MIN_IN_BAND_POWER_RATIO:
            # A rate can always be computed from filter residue. Refuse to
            # report one the band does not actually support.
            return None

        self._emitted += 1
        return Detection(
            modality=Modality.WIFI_CSI,
            source_id=self.source_id,
            timestamp=sample.timestamp,
            confidence=confidence,
            kind=self.kind,
            attributes={
                "bpm": round(bpm, 1),
                "band_hz": list(self.band),
                "in_band_power_ratio": round(confidence, 4),
                "window_seconds": round(series.size / self.fs, 1),
                "cog_id": self.manifest.cog_id,
            },
        )


class BreathingRateCog(_PhaseVitalsCog):
    """Respiration rate, 6-30 BPM."""

    band = RESPIRATION_BAND_HZ
    bpm_range = RESPIRATION_BPM_RANGE
    kind = "breathing_rate"
    require_coherence = True

    manifest = CogManifest(
        cog_id="vitals-breathing",
        name="Breathing rate",
        category=CogCategory.PHYSICAL,
        version="0.1.0",
        privacy_class=PrivacyClass.BIOMETRIC,
        requires=frozenset({Capability.CSI_EXTRACTION}),
        emits=Modality.WIFI_CSI,
        min_ram_mb=64,
        description="0.1-0.5 Hz bandpass on sanitized CSI phase, circular-variance "
                    "gated, zero-crossing BPM.",
        limits="Single-subject only. A second moving body in the Fresnel zone "
               "corrupts the estimate rather than producing two readings. "
               "Requires >=30 s of continuous buffered signal before first output.",
    )


class HeartRateCog(_PhaseVitalsCog):
    """Cardiac rate, 48-120 BPM (see module docstring on the 40 BPM floor)."""

    band = CARDIAC_BAND_HZ
    bpm_range = CARDIAC_BPM_RANGE
    kind = "heart_rate"

    manifest = CogManifest(
        cog_id="vitals-heart",
        name="Heart rate",
        category=CogCategory.PHYSICAL,
        version="0.1.0",
        privacy_class=PrivacyClass.BIOMETRIC,
        requires=frozenset({Capability.CSI_EXTRACTION}),
        emits=Modality.WIFI_CSI,
        min_ram_mb=64,
        description="0.8-2.0 Hz bandpass on sanitized CSI phase, zero-crossing BPM.",
        limits="Reports 48-120 BPM, not the advertised 40-120: a 0.8 Hz low cut "
               "cannot pass 40 BPM. Subject must be near-stationary; the "
               "respiration 3rd harmonic sits inside the cardiac band and is not "
               "separated by this filter alone.",
    )
