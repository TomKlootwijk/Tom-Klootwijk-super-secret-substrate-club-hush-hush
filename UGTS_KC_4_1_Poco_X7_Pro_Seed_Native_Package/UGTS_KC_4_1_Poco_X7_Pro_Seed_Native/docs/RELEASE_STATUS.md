# Release Status - 4.1.0

## Completed

- NativeActivity Android source with C++20, EGL and OpenGL ES 3.0.
- POCO X7 Pro arm64 flavor plus universal fallback flavor.
- NDK Camera2 YUV capture and app-private storage.
- NDK accelerometer, gyroscope and rotation-vector acquisition.
- Seeded sparse luma feature extraction and keyframe selection.
- UGTS-style observation proposal, ordered verification and ledger commit.
- Stable identifiers, two 64-bit spatial key profiles, uncertainty and reason masks.
- KSEED 4.1 delta/varint/zlib/CRC32/SHA-256 storage.
- Thermal adaptation, 120 Hz presentation request and Bayer 8x8 output.
- Deterministic synthetic fallback and route/ledger views.
- Host tests, independent KSEED inspector, source-contract checks and package verification tooling.

## Deferred to Codex/device stage

- Actual Android SDK/NDK compile and APK generation.
- Installation and runtime permission test on the named POCO X7 Pro.
- Camera stream negotiation confirmation on the physical rear camera.
- p50/p95/p99 capture and processing latency.
- thermal, energy, battery, memory and sustained-session measurement.
- accuracy comparison against a calibrated SLAM or scanning baseline.
- distilled transformer or NNAPI model weights.
- production signing, Play policy review and external distribution hardening.

The source is structured so these tasks can be performed without changing the 4.0 authority boundary: camera and model outputs remain proposals; only the verifier/ledger path may mutate accepted state.
