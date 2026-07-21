# How the AI learns to read the signals (plain-language)

## The one-sentence version

rudestorm starts with sensible hand-written rules, then **learns from experience** —
both from labelled practice data and from the operator's own confirm/dismiss
clicks — so that the longer it runs in a place, the fewer false alarms it raises
and the more it trusts the signals that actually matter there.

## The problem the AI is solving

A single passive sensor is a bad witness. A WiFi node "sees" a curtain move and a
person walk the same way. A microphone hears a lawnmower and a drone the same way.
The scores they hand up ("I'm 80% sure") don't even mean the same thing from one
sensor to the next. If you just add them up, you get a jumpy, noisy alarm that
operators quickly learn to ignore — and an ignored alarm is a failed system.

The AI's job is not to be a genius single detector. It's to be a **good judge of
weak witnesses**: to figure out which witness to trust, how much, and only shout
when independent witnesses agree.

## The four things the AI actually learns

Think of it as four small, understandable models — not one black box. Each is a
few dozen lines of math that runs on the sensor itself, offline.

### 1. It learns what "normal" looks like here (`CSIBaselineModel`)
Every location has its own normal WiFi "weather." A quiet server room and a busy
lobby look completely different. The node watches during calm periods and learns
its own baseline (running average and spread). Then a new reading is scored by
*how far outside normal it is for this spot* — not against a one-size-fits-all
number. **Analogy:** a night guard who has worked the same building for a month
notices the one thing that's off, because they know what the building usually
feels like.

### 2. It learns to speak a common language (`ConfidenceCalibrator`)
Each sensor's raw "80%" is put through **calibration**, which converts it into an
honest probability. After calibration, 0.8 from the microphone and 0.8 from the RF
sniffer really do mean "right 80% of the time." Now their votes can be compared
fairly. **Analogy:** two thermometers reading in Fahrenheit and Celsius — you
convert both to the same scale before you compare them.

### 3. It learns who to trust, together (`LearnedFusion`)
Instead of a fixed formula for combining votes, the AI learns from labelled
examples which *combinations* of sensors reliably meant a real event and which
were false alarms. Maybe RF + sound is trustworthy, but sound + vibration is
mostly garbage in this city. It learns those weights. **Crucially, this learned
model is fenced in by a hard safety rule it can never break: it will not raise an
alarm on a single sensor, no matter how confident.** The AI can make a good call
sharper; it cannot make an unsafe one.

### 4. It learns from the operator (`OperatorFeedback`)
Every time an operator confirms or dismisses an alert, that click becomes a
labelled training example. Periodically the fusion model retrains on those labels.
This is **active learning**: the system is tuned by the people using it, so its
false-alarm rate drops over the deployment instead of staying fixed. **Analogy:** a
new analyst who gets better every week because their supervisor tells them which
calls were right.

## Where the AI improves the raw code's outputs

| Raw pipeline output | What the AI adds |
|---|---|
| Adapter confidence (hand-tuned) | Calibrated into a true probability (#2) |
| Fixed motion threshold | Per-location learned baseline + anomaly score (#1) |
| noisy-OR combination | Learned combination weighted by real outcomes (#3) |
| Static behavior | Retrains on operator feedback; FP rate falls over time (#4) |

## What we deliberately do NOT do

- We do **not** use ML to invent capabilities the physics can't support (no
  identifying people from WiFi, no body pose, no vitals). ML sharpens *judgement*
  of real signals; it does not manufacture new senses.
- We do **not** let a learned model override the ≥2-independent-modality safety
  rule. Learning can only move confidence within the safe envelope.
- We do **not** need a data centre. Every model here is numpy-only and trains and
  runs on an edge node, so it keeps working if the network is jammed.

## How this maps to the program (TRL)

The hand-tuned baseline is the TRL 1–3 starting point. The measurable win we
advance toward TRL 4/5 is: **calibration + learned fusion + operator feedback
lower the false-alarm rate on self-sourced validation data** versus the fixed-rule
baseline — a number we can put in the final report.
