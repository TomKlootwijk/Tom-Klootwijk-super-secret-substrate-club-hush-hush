# Codex Build and Deploy Guide

This guide assumes a Linux/macOS shell, Java 17 or newer, Android SDK Platform 36, Build Tools, CMake 3.22.1, NDK 29.0.14206865, `adb`, `curl`, `unzip`, and a USB-connected POCO X7 Pro with developer options/USB debugging enabled.

## 1. Verify the package

From the package root:

```bash
python3 tools/verify_package.py
python3 tools/source_contract_check.py
python3 tools/kseed_inspect.py examples/demo_session.kseed --json
```

## 2. Configure Android SDK

```bash
export ANDROID_SDK_ROOT="$HOME/Android/Sdk"
cp android_project/local.properties.example android_project/local.properties
# Edit sdk.dir in local.properties if your SDK is elsewhere.
```

The project pins:

```text
AGP 8.13.2
Gradle 8.13
compileSdk/targetSdk 36
NDK 29.0.14206865
CMake 3.22.1
```

## 3. Build the POCO flavor

```bash
cd android_project
./gradlew --no-daemon clean :app:assemblePocoX7ProRelease
```

Expected APK:

```text
app/build/outputs/apk/pocoX7Pro/release/app-pocoX7Pro-release.apk
```

The custom `gradlew` bootstrap downloads the official Gradle 8.13 binary and checks its pinned SHA-256 before execution.

## 4. Inspect the phone before install

```bash
adb devices
adb shell getprop ro.product.manufacturer
adb shell getprop ro.product.model
adb shell getprop ro.product.device
adb shell getprop ro.product.cpu.abilist
adb shell getprop ro.build.version.release
adb shell getprop ro.build.version.sdk
```

Confirm an `arm64-v8a` ABI and manually verify that the connected device is the intended phone.

## 5. Install and launch

```bash
APK=android_project/app/build/outputs/apk/pocoX7Pro/release/app-pocoX7Pro-release.apk
APP_ID=nl.tomklootwijk.ugtskc.spatial.poco
adb install -r "$APK"
adb shell pm grant "$APP_ID" android.permission.CAMERA || true
adb shell am start -n "$APP_ID/android.app.NativeActivity"
```

Watch native logs:

```bash
adb logcat -s UGTS-KC-4.1:* AndroidRuntime:E
```

## 6. Smoke test

1. Confirm the Bayer-dithered view appears.
2. Swipe horizontally through Camera, Map Demo and Ledger views.
3. Tap or press Volume Up to start recording.
4. Move the phone slowly for at least 30 seconds.
5. Stop recording.
6. Confirm logcat reports a closed session and byte count.

## 7. Pull sessions

Because this owner-device handoff is debuggable:

```bash
APP_ID=nl.tomklootwijk.ugtskc.spatial.poco
mkdir -p pulled_sessions
adb exec-out run-as "$APP_ID" sh -c 'cd files && tar cf - sessions' | tar xf - -C pulled_sessions
find pulled_sessions -type f -maxdepth 3 -print
python3 tools/kseed_inspect.py pulled_sessions/sessions/<session>.kseed --json
```

## 8. Required device validation record

Record at minimum:

- phone model/device codename, RAM edition and OS build;
- selected camera ID, actual stream size and FPS;
- GPU renderer string and display mode;
- p50/p95/p99 frame processing latency;
- memory peak, storage per minute and dropped-frame count;
- thermal status over 5, 15 and 30 minute runs;
- battery change/energy estimate;
- KSEED integrity and replay result;
- false/missed-event comparison against a conventional baseline.

Do not describe the source as a validated scanner or safety tool until these measurements and task-specific accuracy studies exist.
