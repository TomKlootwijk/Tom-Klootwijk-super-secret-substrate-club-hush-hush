# UGTS-KC 3.9.4.1 — Atlas Pocket SLAM

Native Android source package for the **POCO X7 Pro 12 GB RAM edition**, repaired and repackaged after the previous 3.9.4 archive failed as a practical build handoff.

This release is deliberately small and inspectable:

- platform Camera2 preview and `YUV_420_888` analysis;
- game-rotation-vector / rotation-vector orientation and bounded linear-acceleration hints;
- deterministic FAST-9 + 256-bit BRIEF features;
- four-table descriptor LSH, ratio and mutual-best guards;
- IMU-rotation-compensated epipolar translation direction;
- guarded two-view triangulation and keyframe-only semi-dense plane sweep;
- confidence-weighted bounded voxel fusion;
- ordered UGTS ledger events;
- compact `.ugtsscan` export with hashes;
- **zero AndroidX/runtime-library dependencies** and no Android network permission.

## Quick start

Use a short extraction path, especially on Windows, for example `C:\UGTS3941`.

```text
Windows
  gradlew.bat --bootstrap-self-test
  gradlew.bat :app:assembleRelease

Linux/macOS
  ./gradlew --bootstrap-self-test
  ./gradlew :app:assembleRelease
```

The first real build needs JDK 17, Android SDK Platform 36, and access to the Gradle/Google repositories unless those artifacts are already cached. The application itself is fully offline at runtime.

The output APK is normally:

```text
app/build/outputs/apk/release/app-release.apk
```

The local release variant uses the Android debug signing key so an owner/developer can install it immediately. Replace that signing configuration with a private production key before distribution.

See [BUILD.md](BUILD.md) for exact prerequisites and installation commands.

## Package validation

Run all host-side checks without an Android SDK:

```bash
./tools/run_all_validation.sh
```

That suite compiles and tests the platform-independent core, verifies the Gradle bootstrap through a local fake distribution, checks the sample `.ugtsscan`, checks Android source policy, and audits paths/forbidden build debris.

## Accuracy boundary

This is a compact **reference monocular visual-inertial scanner**, not a calibrated survey instrument. Scale remains `relative_units` until a known-distance anchor is accepted. Camera2 factory intrinsics are used when exposed by the device; otherwise the app records a metadata estimate or declared fallback. Loop-closure candidates are logged but do not modify geometry because geometric bundle adjustment is not implemented in this compact release.

No physical POCO X7 Pro benchmark, sustained thermal test, calibrated reconstruction-error study, or battery measurement was available in the packaging environment. Read [docs/ACCURACY_AND_LIMITS.md](docs/ACCURACY_AND_LIMITS.md) before interpreting output.

## Project map

```text
app/          Native Android Camera2/IMU/UI/export shell
core/         Platform-independent visual-inertial SLAM reference core
contracts/    Atlas observation-packet contract
samples/      Verified compact scan fixture
tools/        Build, host test, decoder, and release verification tools
docs/         Architecture, accuracy, compression, repair, and device notes
provenance/   Source-baseline hashes and substrate alignment
validation/   Machine-readable validation output generated for this release
```

## Canonical authority rule

Observations do not directly mutate the map. The intended sequence is:

```text
capture → support → compatibility → numerical/uncertainty guards
→ accepted proposal → deterministic commit → lineage/checkpoint record
```

Pixels, overlays, PLY files, and other render/export artifacts remain downstream views rather than authoritative evidence.
