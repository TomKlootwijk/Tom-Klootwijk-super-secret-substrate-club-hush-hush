# Build, install, and measurement

## Rebuild with Android SDK/NDK

Requirements:

- JDK 17 or newer
- Android SDK platform 36
- Android Gradle Plugin 8.13.2
- Gradle 8.13-compatible installation
- CMake 3.22.1
- Android NDK r29 / 29.0.14206865

```bash
gradle :app:assembleRelease
```

## Install the bundled test build

```bash
adb install -r dist/UGTS_KC_Bayer_Direct_3_9_4_arm64-v8a.apk
```

The APK has a self-signed test certificate. Uninstall a package signed with another key before installation, or use a distinct package ID. This release uses `nl.tomklootwijk.ugtskc.bayer.poco`, separate from the retained Grove package.

## Physical-device acceptance gates

Record at minimum:

- exact device and OS build;
- sustained 10-minute and 30-minute frame pacing;
- CPU utilization and frequency residency;
- memory footprint and buffer format actually granted;
- surface resolution and compositor scaling behavior;
- thermal status and battery discharge;
- p50/p95/p99 frame production time;
- launch/install result and crash-free lifecycle transitions.

No physical-device result is claimed by this package.
