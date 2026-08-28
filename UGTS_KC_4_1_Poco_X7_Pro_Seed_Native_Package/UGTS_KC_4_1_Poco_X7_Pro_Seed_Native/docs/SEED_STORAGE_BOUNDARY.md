# Seed-Based Storage Boundary

## What the seed does

A 64-bit session seed deterministically controls:

- sparse sample tie-breaking;
- stable proposal/node/event identifiers;
- deterministic demo generation;
- repeatable synthetic fallback frames;
- procedural display choices;
- content-addressable namespace separation.

Given the same seed and the same retained evidence deltas, the portable core reproduces the same identifiers, record order, accepted-event chain and projections.

## What the seed cannot do

A seed cannot regenerate photons that were never stored. It cannot reconstruct a room, person, object, depth field, texture, or event from nothing. It is not a replacement for measured observations and it is not a lossy codec for arbitrary real images.

The real capture record therefore stores compact measured deltas:

- keyframe time and frame index deltas;
- quantized orientation, acceleration and angular velocity;
- luma mean, deviation and 64-bit signature;
- seeded sparse feature coordinates, intensity, gradient and score;
- verified events, uncertainty, metric state, reason-relevant fields and hashes.

Raw images are disabled by the POCO profile. The optional thumbnail mode exists in the format but is not selected by default.

## Compression and integrity

Records use integer quantization, spatial ordering, Morton-coordinate deltas and unsigned/signed varints. Each chunk is zlib-compressed only when compression actually reduces size after overhead. CRC32 checks both stored and decoded payloads. SHA-256 chains each chunk to its predecessor.

Integrity detects accidental or hostile byte changes after capture. It does not by itself prove who held the phone, whether the camera was pointed at the claimed location, whether the OS was compromised, or whether an external timestamp is trustworthy.

## Privacy profile

The default is `local_only` and app-private storage. No network permission is declared. No raw camera frames are written. The user or Codex must explicitly pull sessions with ADB. A future sharing/export feature should preserve this opt-in boundary.
