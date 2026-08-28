# UGTS-KC 4.1 - POCO X7 Pro Spatial Seed Native

UGTS-KC 4.1 is the first Android-native implementation of the UGTS-KC 4.0 Spatial Evidence Ledger contract. It is a C++20 `NativeActivity` application designed for an owner-operated POCO X7 Pro, with a universal Android fallback flavor.

The active app captures Camera2 YUV luma and Android NDK sensor samples, converts them into deterministic sparse observations, verifies proposals before map mutation, and writes compact KSEED 4.1 evidence ledgers. The screen is a low-cost OpenGL ES 3.0 presentation surface using an 8x8 Bayer ordered dither. It performs no ray tracing and the renderer is never authoritative.

## Package status

This package contains complete source, host-native validation, a deterministic demonstration KSEED file, the retained UGTS-KC 4.0 Python reference namespace, and a source-only copy of the attached 3.9.2 Android implementation used as the native lifecycle/device-policy baseline.

It does **not** contain a newly built APK or a physical-phone benchmark. The release environment used here had no installed Android SDK/NDK and no POCO X7 Pro connected. The included Codex guide is the handoff for building, installing, smoke testing, and pulling sessions.

## Build target

```bash
cd android_project
./gradlew :app:assemblePocoX7ProRelease
```

Expected APK:

```text
android_project/app/build/outputs/apk/pocoX7Pro/release/app-pocoX7Pro-release.apk
```

The owner-device release is intentionally debug-key signed and debuggable so Codex can use ADB and `run-as`. Replace the signing configuration and disable debugging before any external distribution.

## Device interaction

- Tap or press Volume Up to start or stop a recording.
- Swipe horizontally to rotate through Camera, deterministic Map Demo, and Ledger views.
- Camera permission is requested on first launch.
- Sessions are stored under app-private `files/sessions/` as `.kseed` plus a compact JSON summary.
- When no camera is available, a visibly marked deterministic demo runs. Demo events carry a synthetic tag and are not camera evidence.

## Storage design

KSEED is **seed plus evidence deltas**, not magical seed-only reconstruction. The seed regenerates deterministic sampling schedules, stable identifiers, procedural demo content, and display choices. Real-world information still requires retained measured descriptors, IMU summaries, accepted events, uncertainty, and hashes. Raw image retention is disabled by default.

Each file uses:

- a fixed 128-byte session header;
- 64-byte chunk headers;
- varint and delta records;
- conditional zlib compression;
- CRC32 for stored and decoded payloads;
- a SHA-256 chunk chain;
- a final summary with exact stored byte count.

See `docs/SEED_STORAGE_BOUNDARY.md` and `spec/KSEED_FORMAT_4_1.md`.

## Validation included

- 23/23 portable C++ host tests pass.
- 9/9 Android-specific C++ translation units pass a mock-header syntax check.
- The deterministic demonstration KSEED passes independent header CRC, chunk CRC, zlib, record framing, hash-chain, and summary checks.
- The checked-in demo stores 300 synthetic frames as 63 keyframes and 592 verified events in 79,053 bytes. The 218.59x raw-luma-to-KSEED ratio is a synthetic host fixture only. It is not a phone benchmark, compression guarantee, or SLAM result.

## Directory map

```text
android_project/     Codex-buildable NativeActivity project
native/host_tests/   portable core tests and deterministic demo generator
substrate/           retained UGTS-KC 4.0 Python reference and schema
upstream/            source-only attached UGTS-KC 3.9.2 Android reference
tools/               build, deploy, pull, inspect, validate and verify scripts
spec/                KSEED and Android-native contracts, profile and mechanisms
docs/                architecture, device, privacy, handoff and boundaries
examples/             verified demonstration KSEED, summary and route projection
validation/           captured validation reports
report/               technical report source and packaged PDF
manifest/             package inventories
checksums/            release checksums
```
