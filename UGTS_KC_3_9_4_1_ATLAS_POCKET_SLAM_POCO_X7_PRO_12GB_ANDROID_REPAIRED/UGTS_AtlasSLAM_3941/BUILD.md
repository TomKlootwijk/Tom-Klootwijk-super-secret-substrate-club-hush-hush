# Build and install

## Required tooling

- JDK 17.
- Android SDK Platform 36.
- Android SDK Build Tools compatible with the selected Android Gradle Plugin.
- `adb` for command-line installation, or Android Studio for IDE builds.

The project pins:

```text
Android Gradle Plugin  8.13.2
Gradle distribution    8.13
compileSdk/targetSdk    36
minSdk                  29
Java source/target      17
```

## Verified bootstrap

`gradlew` and `gradlew.bat` invoke `gradle/wrapper/gradle-wrapper.jar`. In this repaired package that JAR is a small, source-included **UGTS verified bootstrap**, not an unlabeled copy of the upstream wrapper JAR. It:

1. reads `gradle-wrapper.properties`;
2. downloads the declared Gradle 8.13 binary distribution when absent;
3. verifies the required SHA-256 before extraction;
4. rejects ZIP path traversal and over-budget extraction;
5. executes the extracted Gradle launcher.

Its full source is under `tools/bootstrap-src/`. Verify the bootstrap without a network call:

```bash
./gradlew --bootstrap-self-test
./tools/test_bootstrap_local.sh
```

## Android Studio

1. Open the extracted project root.
2. Select JDK 17 for Gradle.
3. Let Android Studio install/locate Platform 36.
4. Sync the project.
5. Build `app` using the `release` or `debug` variant.

No CameraX, AndroidX, OpenCV, neural-model file, NDK, CMake, or native ABI is required by this release.

## Command line

Linux/macOS:

```bash
./gradlew :app:clean :app:assembleRelease
```

Windows:

```bat
gradlew.bat :app:clean :app:assembleRelease
```

Debug build:

```bash
./gradlew :app:assembleDebug
```

## Install

```bash
adb install -r app/build/outputs/apk/release/app-release.apk
```

Grant camera permission when prompted. The manifest intentionally does not request `INTERNET`, location, broad storage, microphone, or media permissions.

## Export behavior

The app writes a temporary compact scan only inside its private cache, then opens Android's `ACTION_CREATE_DOCUMENT` picker. The user chooses the final location. This avoids legacy broad-storage permissions and avoids a FileProvider/AndroidX dependency.

## Signing boundary

For owner-device testing, the `release` variant currently uses `signingConfigs.debug`. This makes the APK installable but is not suitable for store or public production release. Before distribution, create a private keystore, keep it outside the repository, and replace the release signing configuration.

## Clean handoff

The shipped ZIP intentionally excludes:

- `build/`, `.gradle/`, `.cxx/`, `.idea/`;
- `local.properties` and machine-specific SDK paths;
- generated APKs that were not built in the packaging environment;
- nested copies of the previous multi-megabyte substrate archives.

This keeps extraction portable and avoids presenting stale build output as a validated binary.
