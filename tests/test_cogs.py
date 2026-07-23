"""Cog framework: capability gating, privacy gating, and vitals extraction."""

from __future__ import annotations

import numpy as np
import pytest

from rudestorm.adapters.csi_presence import CSISample
from rudestorm.cogs import (
    PI_4B,
    PI_ZERO_2W,
    Capability,
    CogRegistry,
    CogRejected,
    PrivacyClass,
    get_profile,
)
from rudestorm.cogs.vitals import (
    BreathingRateCog,
    HeartRateCog,
    bandpass,
    circular_variance,
    sanitize_phase,
    zero_crossing_bpm,
)
from rudestorm.governance import ProvenanceLog

FS = 100.0


def _breathing_stream(bpm: float, seconds: float, fs: float = FS,
                      antennas: int = 3, subcarriers: int = 56,
                      coherent: bool = True) -> list:
    """Synthesize CSI samples whose phase carries a known respiration rate.

    The body term must be *frequency-selective* across subcarriers to be
    physically meaningful. `sanitize_phase` removes the common-mode and linear
    components of each frame by design (that is how CFO/SFO/PDD are stripped),
    so a body signal modeled as constant across subcarriers is annihilated
    along with the hardware artefacts. Real chest motion modulates a multipath
    channel and therefore lands differently on each subcarrier, which is what
    the sinusoidal `selectivity` profile below represents.
    """
    rng = np.random.default_rng(1337)
    n = int(seconds * fs)
    freq = bpm / 60.0
    t = np.arange(n) / fs
    chest = 0.9 * np.sin(2 * np.pi * freq * t)

    # Frequency-selective multipath profile: non-linear across subcarrier index,
    # so it survives the linear detrend. Mean-removed so it is not common-mode.
    sub_idx = np.arange(subcarriers)
    selectivity = np.sin(2 * np.pi * sub_idx / 17.0) + 0.5 * np.cos(
        2 * np.pi * sub_idx / 7.0
    )
    selectivity -= selectivity.mean()

    samples = []
    for i in range(n):
        # Linear CFO/SFO ramp across subcarriers, which sanitize_phase removes.
        ramp = np.linspace(0.0, 2.4, subcarriers)[None, :]
        base = chest[i] if coherent else chest[i] + rng.uniform(-np.pi, np.pi)
        body = base * selectivity[None, :]
        phase = body + ramp + rng.normal(0, 0.02, (antennas, subcarriers))
        amp = np.abs(rng.normal(10, 0.4, (antennas, subcarriers)))
        samples.append(CSISample(amplitude=amp, phase=phase))
    return samples


class TestSignalPrimitives:
    def test_sanitize_phase_removes_linear_ramp(self):
        n_sub = 56
        ramp = np.linspace(0.0, 5.0, n_sub)
        phase = np.vstack([ramp, ramp + 0.3, ramp - 0.7])
        out = sanitize_phase(phase)
        # A pure ramp plus a per-antenna offset should flatten to ~zero.
        assert np.allclose(out, 0.0, atol=1e-9)

    def test_sanitize_phase_preserves_body_component(self):
        n_sub = 56
        ramp = np.linspace(0.0, 5.0, n_sub)[None, :]
        body = 0.8
        out = sanitize_phase(np.repeat(ramp + body, 3, axis=0))
        # The constant body term is absorbed by mean-centering, but a
        # non-linear component must survive.
        bump = np.zeros(n_sub)
        bump[20:30] = 1.5
        out2 = sanitize_phase(np.repeat(ramp + bump[None, :], 3, axis=0))
        assert np.abs(out2).max() > 0.5

    def test_sanitize_phase_rejects_1d(self):
        with pytest.raises(ValueError, match="must be 2D"):
            sanitize_phase(np.zeros(56))

    def test_circular_variance_coherent_vs_uniform(self):
        coherent = np.full(500, 0.4)
        uniform = np.linspace(-np.pi, np.pi, 500, endpoint=False)
        assert circular_variance(coherent) < 0.01
        assert circular_variance(uniform) > 0.95

    def test_zero_crossing_bpm_recovers_known_rate(self):
        for bpm in (12.0, 18.0, 25.0):
            t = np.arange(int(60 * FS)) / FS
            sig = np.sin(2 * np.pi * (bpm / 60.0) * t)
            assert zero_crossing_bpm(sig, FS) == pytest.approx(bpm, abs=1.0)

    def test_bandpass_rejects_band_above_nyquist(self):
        with pytest.raises(ValueError, match="Nyquist"):
            bandpass(np.zeros(500), fs=2.0, band=(0.8, 2.0))

    def test_bandpass_attenuates_out_of_band_tone(self):
        t = np.arange(int(60 * FS)) / FS
        in_band = np.sin(2 * np.pi * 0.25 * t)      # 15 BPM, inside 0.1-0.5 Hz
        out_band = np.sin(2 * np.pi * 5.0 * t)      # 5 Hz, well outside
        filtered = bandpass(in_band + out_band, FS, (0.1, 0.5))
        # The 5 Hz component should be gone; the 0.25 Hz one should survive.
        assert np.std(filtered) == pytest.approx(np.std(in_band), rel=0.2)


class TestCapabilityGating:
    def test_pi_zero_2w_cannot_do_csi(self):
        """The Zero 2W's CYW43438 is not a Nexmon-supported chip."""
        assert Capability.CSI_EXTRACTION not in PI_ZERO_2W.capabilities
        assert Capability.MONITOR_MODE in PI_ZERO_2W.capabilities

    def test_csi_cog_rejected_on_zero_2w_with_reason(self):
        registry = CogRegistry(PI_ZERO_2W, privacy_ceiling=PrivacyClass.BIOMETRIC)
        result = registry.load(BreathingRateCog, source_id="node-z1")
        assert not result.loaded
        assert "csi_extraction" in result.reason
        assert "CYW43438" in result.reason  # the node's notes explain why
        assert registry.active == []

    def test_csi_cog_loads_on_pi_4b(self):
        registry = CogRegistry(PI_4B, privacy_ceiling=PrivacyClass.BIOMETRIC)
        assert registry.load(BreathingRateCog, source_id="node-01").loaded

    def test_strict_mode_raises(self):
        registry = CogRegistry(PI_ZERO_2W, privacy_ceiling=PrivacyClass.BIOMETRIC)
        with pytest.raises(CogRejected, match="csi_extraction"):
            registry.load(BreathingRateCog, source_id="n", strict=True)

    def test_unknown_tier_lists_known_tiers(self):
        with pytest.raises(ValueError, match="pi_4b"):
            get_profile("pi_400")


class TestPrivacyGating:
    def test_biometric_cog_refused_by_default(self):
        registry = CogRegistry(PI_4B)  # default ceiling = coarse_presence
        result = registry.load(HeartRateCog, source_id="node-01")
        assert not result.loaded
        assert "biometric" in result.reason
        assert "unlock_privacy_class" in result.reason

    def test_unlock_permits_load(self):
        registry = CogRegistry(PI_4B)
        registry.unlock_privacy_class(PrivacyClass.BIOMETRIC, authorization="CHG-4471")
        assert registry.load(HeartRateCog, source_id="node-01").loaded

    def test_unlock_requires_authorization(self):
        registry = CogRegistry(PI_4B)
        with pytest.raises(ValueError, match="attributable"):
            registry.unlock_privacy_class(PrivacyClass.BIOMETRIC, authorization="   ")

    def test_unlock_and_load_are_in_the_provenance_chain(self):
        log = ProvenanceLog()
        registry = CogRegistry(PI_4B, log=log)
        registry.load(HeartRateCog, source_id="node-01")           # rejected
        registry.unlock_privacy_class(PrivacyClass.BIOMETRIC, authorization="CHG-4471")
        registry.load(HeartRateCog, source_id="node-01")           # loaded

        actions = [r.action for r in log.records]
        assert actions == ["cog_rejected", "privacy_ceiling_changed", "cog_loaded"]
        assert log.records[1].payload["authorization"] == "CHG-4471"
        assert log.verify()


class TestVitalsCogs:
    def test_breathing_recovers_synthetic_rate(self):
        cog = BreathingRateCog("node-01", sampling_rate=FS)
        detection = None
        for sample in _breathing_stream(bpm=15.0, seconds=40.0):
            detection = cog.process(sample) or detection
        assert detection is not None, "no breathing detection emitted"
        assert detection.kind == "breathing_rate"
        assert detection.attributes["bpm"] == pytest.approx(15.0, abs=2.5)

    def test_no_output_before_window_is_full(self):
        cog = BreathingRateCog("node-01", sampling_rate=FS)
        for sample in _breathing_stream(bpm=15.0, seconds=5.0):
            assert cog.process(sample) is None

    def test_incoherent_phase_is_gated_out(self):
        """A broad phase excursion is not a chest wall; emit nothing."""
        cog = BreathingRateCog("node-01", sampling_rate=FS)
        emitted = [
            d for s in _breathing_stream(15.0, 40.0, coherent=False)
            if (d := cog.process(s)) is not None
        ]
        assert emitted == []

    def test_out_of_band_rate_produces_no_claim(self):
        """120 BPM is not respiration; the cog must stay silent, not clamp."""
        cog = BreathingRateCog("node-01", sampling_rate=FS)
        emitted = [
            d for s in _breathing_stream(120.0, 40.0)
            if (d := cog.process(s)) is not None
        ]
        assert emitted == []

    def test_heart_cog_declares_the_48_bpm_floor(self):
        assert HeartRateCog.manifest.limits.startswith("Reports 48-120 BPM")

    def test_manifest_rejects_emit_consume_loop(self):
        from rudestorm.cogs.base import CogCategory, CogManifest

        with pytest.raises(ValueError, match="feedback loop"):
            CogManifest(
                cog_id="loopy", name="Loopy", category=CogCategory.PHYSICAL,
                version="0.1.0", privacy_class=PrivacyClass.NONE,
                emits=Modality_WIFI_CSI, consumes=frozenset({Modality_WIFI_CSI}),
            )


from rudestorm.events import Modality as _M  # noqa: E402

Modality_WIFI_CSI = _M.WIFI_CSI
