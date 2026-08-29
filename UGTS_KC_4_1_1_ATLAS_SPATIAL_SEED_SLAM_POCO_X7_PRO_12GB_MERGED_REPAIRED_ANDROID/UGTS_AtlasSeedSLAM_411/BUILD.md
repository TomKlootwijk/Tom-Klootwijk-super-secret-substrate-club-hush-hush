# Build and handoff

## Recommended clean build

```bash
./gradlew --bootstrap-self-test
./gradlew :app:clean :app:assembleRelease
```

The wrapper bootstrap pins Gradle 8.13 and verifies the distribution SHA-256 before extraction. The Android build pins SDK 36, AGP 8.13.2, NDK 29.0.14206865 and CMake 3.22.1. Only `arm64-v8a` is built for the native seed module.

## Install

```bash
adb install -r app/build/outputs/apk/release/app-release.apk
```

## Pull private captures after an app-side document export

The app uses the Android document picker and does not request broad storage access. Select a user-visible destination when exporting a `.kseed` file, then verify it independently:

```bash
python3 tools/kseed_inspect.py session.kseed --json
python3 tools/kseed_inspect.py session.kseed --to-ply session.ply --voxel-size 0.012
```

## Host-only validation

```bash
./tools/run_all_validation.sh
```

Host checks do not substitute for Android assemble, installation, camera negotiation or physical accuracy/thermal measurements.
