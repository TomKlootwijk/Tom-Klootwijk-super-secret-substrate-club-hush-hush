# Deterministic 2D Game Runtime Contract

## Clock

`GameWorld` advances only in fixed increments `fixed_dt > 0`. A call to `step(frame, steps=n)` executes exactly `n` simulation ticks. Time is derived from `tick * fixed_dt` and rounded to suppress textual drift.

## System order

Each tick executes phases in this order:

```text
input -> controller -> pre_physics -> physics -> bounds
-> post_physics -> collision -> gameplay -> update
-> lifetime -> late -> camera -> deferred despawn
```

Custom systems are ordered by integer priority and stable name within a phase.

## Components

Core components are serializable records. Unknown mapping components may be retained for custom systems/exporters. Dynamic bodies have positive mass; kinematic/static bodies have zero inverse mass. Sensors participate in contacts but not physical resolution.

## Collision lifecycle

A pair present this tick but not the prior tick emits `collision_enter`; a continuing pair emits `collision_stay`; a pair removed this tick emits `collision_exit`. Pair IDs are ordered for deterministic comparison.

## Gameplay interactions

Collectibles update a declared integer state key and may be deferred for despawn. Hazards apply health damage, contact-specific cooldown and knockback. Health is clamped to `[0, maximum]`.

## Snapshots and saves

Snapshots include schema, clock, state, entities/components, active contacts and optional event history. State hashes exclude event history and hash canonical JSON. Integral numeric spellings are normalized, making `1` and `1.0` equivalent for canonical identity.
