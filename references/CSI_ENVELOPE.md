# WiFi-CSI capability envelope (honest claims)

This file pins down exactly what the WiFi-CSI presence layer may and may not
claim. It exists because overclaiming CSI is a documented way to fail a technical
review, and because the challenge's privacy gate is pass/fail.

## CLAIM (supportable)

- Coarse **human presence** and **gross motion** near a node.
- Works through ~one interior wall, in the dark, and around visual corners.
- **Device-free** — no phone or wearable required on the person.
- Captures **no imagery and no identity** — more privacy-preserving than a camera.
- Multi-node corroboration suppresses hallway / neighbour walk-by false positives.

## DO NOT CLAIM (not physically supportable on commodity single-node ESP32-S3 CSI)

- Reliable person **counting**.
- Body **pose** / skeleton estimation as a shipped capability.
- **Biometric identity**.
- **Vitals** (breathing / heart rate) accuracy.
- Fine localization or trajectory (`~7.5 m` range resolution at 20 MHz rules it out).
- Outdoor sensing (CSI exploits indoor multipath; no credible outdoor basis).

## Grounding

- CMU *DensePose-from-WiFi* (arXiv:2301.00250) — through-wall sensing from
  commodity WiFi; used as physics grounding, not as a shipped accuracy claim.
- MIT *Wi-Vi* (Adib/Katabi) — tracking moving humans through walls off WiFi.

Do NOT cite RF-Pose / RF-Capture / WiTrack as WiFi proof — those use custom FMCW
radios, not `$9` chips; citing them to back a WiFi mesh is a category error.

## Why this maps to the program

Entry is TRL 1–3. The plan is to **independently benchmark and validate** the CSI
layer on self-sourced data and advance it toward TRL 4/5 — de-risking a real
capability, not shipping a finished product. Any third-party CSI implementation is
treated as one candidate reference to validate, never as a trusted backbone.
