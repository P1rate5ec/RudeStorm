# Seeing with WiFi: an array of ESP32 sensors as a passive sensing grid

## The idea in one line

WiFi radio waves fill every room and street. When something moves, it disturbs
those waves. A cheap ESP32 chip can *measure that disturbance* — so a handful of
$9 chips turns the WiFi that's already in the air into a motion-and-drone sensing
grid, with **no cameras and no new primary sensors**.

## Why WiFi can "see" at all

Every WiFi packet arrives at a receiver by many paths at once: straight through,
bounced off a wall, off the floor, off *you*. The receiver already measures the
detailed shape of that combined signal — per frequency slice ("subcarrier") and
per antenna — because it needs it to decode data. That fine-grained measurement is
called **Channel State Information (CSI)**.

- When the room is still, the CSI pattern is steady.
- When a person moves, the bounced paths change, and the CSI **ripples**.
- Those ripples are enough to say *"something moved here"* — through a wall, in
  the dark, around a corner — **without any image and without any identity.**

That's the honest limit and also the privacy win: WiFi sensing gives you presence
and motion, **not** who someone is. (See `references/CSI_ENVELOPE.md` for the
exact claim envelope.)

## Why an ESP32 specifically

The **ESP32-S3** (and C6) is a ~$5–10 chip that (a) has a WiFi radio with a DSP
that can export raw CSI, and (b) can sit in **promiscuous / monitor mode** and
listen to broadcasts around it. That means one tiny board does **two passive jobs
at once**:

1. **GROUND — WiFi-CSI motion sensing.** Read the CSI ripples → coarse presence
   and gross motion near the node.
2. **AIR — passive Remote ID / DroneID sniffing.** Drones are legally required to
   broadcast their ID and GPS position (and the *operator's* position) in the
   clear over the same WiFi/Bluetooth bands the ESP32 already hears. The chip
   decodes that broadcast passively — locating both the drone and its pilot with
   zero emissions.

One $9 board, two sensing missions, nothing transmitted.

## Why an *array*, not one sensor

A single WiFi node is a poor witness — it can't tell a person in the hall from a
neighbour through the wall, and it can't tell you *where* along a street a drone
is. An **array** of nodes fixes both:

### 1. Corroboration kills false alarms
The core rule: a node's motion blip is only interesting if **another independent
node (or another modality) agrees within the same few seconds.** One node seeing a
ripple = ignore (probably a curtain, a passer-by, HVAC). Two nodes from different
angles agreeing = real. This is exactly what the fusion engine enforces, and it's
the number-one reason WiFi-sensing systems are trusted or rejected operationally.

### 2. Coverage: the city becomes the grid
Because each mote is cheap and passive, you scatter them across the area you care
about — a harbour perimeter, a base fence line, an intersection cluster. They
piggyback the **existing** WiFi field; you are adding *listeners*, not lighting up
new transmitters. Coverage grows by adding $9 nodes, not six-figure radars.

### 3. Rough localization by geometry
For drones, each mote that hears a Remote ID broadcast gets the drone's *own*
reported GPS — so localization is immediate. For non-cooperative RF and for CSI
motion, multiple nodes hearing the same event at different signal strengths let
you narrow down *which node's zone* it's in. (We claim zone-level localization,
not precise tracking — WiFi's resolution honestly doesn't support fine tracking.)

## How an array is laid out (deployment picture)

```
        Area of interest (e.g. harbour / base perimeter)
   mote ●            ●            ●            ●  mote
   (S3) │            │            │            │  (S3)
        │   each mote: passive RID sniff + WiFi-CSI motion + optional I2S mic
        └──────┬─────┴──────┬─────┴──────┬─────┘
               ▼            ▼            ▼
        edge node (Jetson / municipal server) runs rudestorm:
        adapters → fusion (≥2 nodes/modalities agree) → operator JSON
               │
               └── works OFFLINE — if backhaul is jammed, correlation still runs
                   locally; only tiny JSON events leave, never raw signals.
```

Each mote sends only **small structured detections** (a few numbers), never raw
CSI or audio. That is a privacy property and a bandwidth property at the same time
— the same pattern proven at scale by defence edge-fusion systems.

## What the array does and doesn't give you

| Gives you | Does not give you |
|---|---|
| Presence / gross motion, through a wall, in the dark | Identity, faces, body pose, person count |
| Cooperative drone + operator location (Remote ID) | Dark / radios-off autonomous drones (radar-class, out of scope) |
| Cheap, passive, offline-capable city-scale coverage | Precise sub-metre tracking (WiFi resolution won't support it) |
| False-alarm suppression via multi-node agreement | A single-sensor magic detector |

## The bill of materials story (for the proposal)

- Node: ESP32-S3 dev board (~$9) + optional I2S mic (~$3) + optional accelerometer.
- Aggregation: one Jetson-class or municipal server per cluster.
- Everything else — the intelligence — is **software** (rudestorm). That's the
  wedge: the deliverable is the fusion brain, not the hardware.
