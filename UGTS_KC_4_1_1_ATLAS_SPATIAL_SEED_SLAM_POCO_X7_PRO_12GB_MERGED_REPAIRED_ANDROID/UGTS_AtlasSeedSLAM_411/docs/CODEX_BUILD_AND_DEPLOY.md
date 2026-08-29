# Codex build, deploy and device-validation sequence

## 1. Build host

Install JDK 17+, Android SDK Platform 36, NDK 29.0.14206865 and CMake 3.22.1. From the package root:

```bash
./gradlew --bootstrap-self-test
./gradlew :app:clean :app:assembleRelease --stacktrace
```

Record the SHA-256 and size of `app/build/outputs/apk/release/app-release.apk`.

## 2. Install

```bash
adb devices -l
adb install -r app/build/outputs/apk/release/app-release.apk
adb shell dumpsys package org.ugts.atlas.slam.pocox7pro | head -80
```

Record exact model, RAM edition, Android/HyperOS build, security patch, ABI, GPU string, display mode and app version.

## 3. Camera and sensor negotiation

Capture logcat while starting the app:

```bash
adb logcat -c
adb logcat | tee validation/device_logcat.txt
```

Record selected camera ID, requested and actual YUV dimensions, actual frame cadence, intrinsic source, sensor availability and thermal tier.

## 4. Functional sequence

1. Run the synthetic Demo and export its `.kseed` file.
2. Inspect it independently with `tools/kseed_inspect.py`.
3. Start a real scan in a textured, static scene.
4. Translate slowly with overlapping views; avoid pure rotation.
5. Apply one known-distance anchor and verify a second independent control distance.
6. Export the real `.kseed` file through the document picker.
7. Inspect CRCs, zlib framing, SHA chain, counts and stored size independently.
8. Convert voxels to PLY only for downstream inspection; the PLY is not the authoritative ledger.

## 5. Required device measurements

- p50/p95/p99 analysis latency and KSEED storage latency.
- Actual accepted frame cadence and dropped frames.
- Peak Java/native memory and bytes per minute.
- 5, 15 and 30 minute thermal and battery traces.
- Camera-intrinsic/calibration source.
- Known-distance and repeated-control error.
- Drift over closed paths; loop-closure proposals remain uncommitted.
- False/missed proposal rates under a task-specific oracle.
- Comparison against a conventional calibrated scanner at equal error.

## 6. Promotion stop conditions

Do not call the app a validated 3D scanner when scale is unanchored, camera calibration is unknown, error exceeds the application margin, the SHA chain fails, real and synthetic data are mixed, thermal collapse changes acquisition policy, or the task lacks an independent reference.
