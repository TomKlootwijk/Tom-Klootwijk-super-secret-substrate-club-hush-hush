# UGTS-KC 4.1.1 - Atlas Spatial Seed SLAM Fusion

A repaired Android Studio handoff for the **POCO X7 Pro 12 GB RAM edition**. This release merges the available UGTS-KC 3.9.4.1 Camera2/SLAM source with the documented UGTS-KC 4.1.0 Spatial Seed Native authority and KSEED contracts.

## What is actually implemented

- Platform Camera2 `YUV_420_888` capture with a two-image latest-frame queue.
- Android IMU orientation and bounded displacement hints.
- Deterministic FAST-9/BRIEF features, compact descriptor matching, rotation-compensated visual motion, guarded triangulation, adjacent-keyframe semi-dense mapping and bounded voxel fusion.
- An explicit eight-gate proposal verifier: identifier, support, compatibility, guard class, confidence, numeric margin, uncertainty and metric availability.
- Stable seed-derived proposal/keyframe/session IDs and ordered ledger events with canonical proposal, pre-state and post-state SHA-256 hashes.
- KSEED 4.1 streaming storage: 128-byte session header, 64-byte independently checked chunks, delta/varint records, int16 inertial values, Morton voxel deltas, zlib level 1 only when smaller, CRC32 and SHA-256 chain.
- A narrow arm64-v8a C++/JNI seed and CRC module plus a Java oracle/fallback.
- A visibly isolated synthetic demo. Synthetic proposals use tag bit 31 and the UI says `DEMO`.
- Optional exact 8x8 four-level Bayer projection as a downstream presentation utility.
- Legacy `.ugtsscan` decoder tooling retained for compatibility; new sessions export `.kseed` by default.
- No network permission, location permission, audio permission, broad storage permission, AndroidX, OpenCV or bundled neural-model weights.

## Important merge boundary

The actual UGTS-KC 4.1.0 source ZIP was not present in the active packaging workspace. The 4.1.0 **technical report** was available and defines the KSEED framing, seed/evidence boundary, verifier order, synthetic isolation, native target and promotion gates. This 4.1.1 release is therefore a clean source-level reimplementation of that documented contract against the repaired 3.9.4.1 source. It is not a byte-for-byte patch of an unavailable 4.1.0 tree.

## Build

Requirements:

- JDK 17 or newer
- Android SDK Platform 36
- Android Gradle Plugin 8.13.2
- Gradle 8.13 (the verified bootstrap downloads and hashes it)
- Android NDK 29.0.14206865
- CMake 3.22.1

```bash
./gradlew --bootstrap-self-test
./gradlew :app:assembleRelease
```

The local-owner release uses debug signing for immediate development installation. Replace it with a private production signing configuration before distribution.

Expected output:

```text
app/build/outputs/apk/release/app-release.apk
```

See `docs/CODEX_BUILD_AND_DEPLOY.md` for build, install, capture, pull and validation commands.

## Host validation

```bash
./tools/run_all_validation.sh
python3 tools/kseed_inspect.py samples/atlas_seed_slam_411_fixture.kseed --json
```

Completed host gates include Java core tests, portable C++ tests, Android/JNI bridge stub compilation, verified Gradle bootstrap tests, static Android source policy, independent KSEED inspection, corruption rejection, Python syntax and JSON parsing.

## Accuracy and evidence boundary

This package is a source handoff, not a physical-phone benchmark. It does not claim that the app has been assembled with the Android SDK/NDK in this environment, installed on the POCO X7 Pro, calibrated, or validated as metric visual-inertial SLAM. Monocular output remains relative until a known-distance anchor is accepted. Loop closure is proposal-only because no bundle adjustment is implemented. KSEED hashes prove byte integrity, not location, operator identity, trusted time, ownership or legal chain of custody. The seed is not encryption and cannot recreate unstored real-world photons.
