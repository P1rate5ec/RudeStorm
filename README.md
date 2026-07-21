# rudestorm

Passive urban-sensing **fusion middleware**. rudestorm rides a city's *existing*
wireless and IoT fabric — it deploys **no new primary sensors** — and turns weak,
individually-unreliable passive signals into high-confidence, privacy-clean
operator events.

Built for the DND/CAF IDEaS Component 1a challenge *"Turning Urban Data into
Real-Time Insight through AI."*

> We don't sell you sensors. We turn the city you already have into one.

## What it does

Three passive modalities in, one corroborated event stream out:

| Layer | Modality | Role | Honest limit |
|---|---|---|---|
| AIR | Passive **Remote ID / DroneID** (ESP32-S3, WiFi/BLE) | Locates drone **and operator** | Cooperative broadcasters only; encrypted/dark drones are out of scope (radar-class) |
| GROUND | **WiFi-CSI** presence | Coarse presence / gross motion | No identity, pose, count, or vitals — ever |
| CORROBORATION | **Acoustic** spectrogram | Supporting vote | 8–15% urban FP rate → never alerts alone |

The value is the **fusion**, not any single sensor.

## The one rule that matters

**No single passive modality raises an alert.** A high-priority event requires
**≥ 2 independent modalities corroborated inside one time window** (`FusionConfig.min_modalities`).
Acoustic and vibration are corroboration-only and can never stand up an event by
themselves. This is the false-alarm-suppression story and it also satisfies the
challenge's "≥ 2 heterogeneous sources" essential outcome.

## Privacy by design

- **Edge redaction** (`governance.EdgeRedactor`): face/plate blur runs inside the
  node; raw pixels never egress — only redacted metadata does.
- **Hash-chained provenance** (`governance.ProvenanceLog`): every detection,
  correlation, and redaction is appended to a tamper-evident SHA-256 chain for
  defensible chain-of-custody. `verify()` fails if any record is edited or removed.

## Architecture

```
[ESP32-S3 motes: Remote ID sniff + WiFi-CSI]  ┐
[edge-redacted ONVIF/RTSP CCTV]               ├─► adapters/ ─► Detection
[ESP32 + I2S mic: acoustic CNN]               ┘                  │
                                                                 ▼
                                          fusion.FusionEngine (sliding window, ≥2-modality)
                                                                 │
                                     governance.ProvenanceLog (hash chain)  ─┐
                                                                 ▼           │
                                            ThreatEvent.to_json() ───────────┘
                                          (operator sink: stdout / MQTT / NATS)
```

Everything runs offline on edge hardware (Jetson-class / municipal server) — the
same RF jamming that kills a drone's C2 link could kill your backhaul, so local
autonomy is a requirement, not a nice-to-have.

## Run it

```bash
pip install -r requirements.txt
python -m rudestorm.demo        # three synthetic scenarios end-to-end
pytest -q                       # tests
```

The demo shows the two behaviors that matter: a lone drone-like sound produces
**no alert**, while corroborated modalities produce a signed, geolocated event.

## Data

Component 1a ships **no DND data and no GFP**, so `synthetic.py` self-sources
labelled scenarios (background / cooperative-UAS / perimeter intrusion) for all
three modalities. Field-deployment seams are marked in each adapter: drop in
OpenDroneID / antsdr / Kismet at `RemoteIDAdapter._parse_frame`, a trained CNN at
`AcousticAdapter._band_energy_ratio`, and a real CSI feed at `CSIPresenceAdapter`.

## Provenance of the code

The CSI signal-processing chain is distilled from the reusable parts of the
open-source `wifi-densepose` project, with its pose/vitals modeling removed. Those
claims are deliberately dropped — this system reports presence/motion only.

MIT licensed.
