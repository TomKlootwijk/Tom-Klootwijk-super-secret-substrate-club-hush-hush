# UGTS-KC 4.1 Android Native Contract

## Conformance path

```text
Camera/IMU input
-> bounded native observation record
-> seeded sparse candidate generation
-> local support and compatibility
-> guard, confidence, numeric error and uncertainty gates
-> metric availability gate when required
-> verified proposal
-> deterministic ledger commit
-> pre/post state hashes
-> KSEED chunk and export projection
```

## Required invariants

1. Camera callbacks and model callbacks may produce proposals only.
2. Only `SpatialLedger::commit` may mutate accepted map/route state.
3. Every committed event has a stable identifier, sequence and pre/post hash.
4. Unknown metric scale must remain unknown. Metric-required events are rejected without a declared metric source.
5. Synthetic/demo records are explicitly tagged and never mixed into camera evidence without that tag.
6. Raw frame retention is false in the POCO default profile.
7. Renderer output is non-authoritative and cannot feed unchecked state mutation.
8. Storage corruption stops replay at the first CRC, chain or framing failure.
9. Thermal policy may reduce rate/budget or pause capture, but may not bypass verification.
10. Device-specific acceleration may optimize proposal creation only; it cannot change the canonical commit ordering.

## Android implementation requirements

- NativeActivity lifecycle and C++20 core.
- NDK Camera2 rear YUV stream with latest-frame bounded buffering.
- Android NDK accelerometer, gyroscope and rotation-vector sampling where available.
- app-private local storage with no internet permission.
- POCO X7 Pro arm64 product flavor and universal fallback.
- an owner-device build path that Codex can install and inspect.
- source-visible capture profile, calibration hash and model/version placeholders.
- deterministic host tests independent of Android.

## Explicit non-claims

Source conformance does not imply a compiled APK, phone compatibility, metric SLAM, complete 3D reconstruction, safety certification, medical validation, evidentiary admissibility, tamper-proof hardware, or production security review.
