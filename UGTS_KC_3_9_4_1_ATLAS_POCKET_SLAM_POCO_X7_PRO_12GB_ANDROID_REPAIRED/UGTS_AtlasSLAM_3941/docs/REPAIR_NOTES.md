# 3.9.4.1 repair notes

## Defects in the superseded ZIP

The prior archive passed a basic ZIP CRC test, but it was broken as a practical Android handoff:

1. `gradlew` was a 189-byte shell shim that required an already installed system Gradle.
2. No `gradle-wrapper.jar` or wrapper properties were present despite documentation implying a wrapper was included.
3. The archive nested generated `build/` and `.cxx/` trees plus large upstream snapshots.
4. Its longest member path was approximately 308 characters, increasing extraction failure risk on common Windows setups.
5. Build status contained no SLAM APK and admitted that no Android build had been attempted.
6. The CameraX/AndroidX dependency graph increased first-build downloads and package complexity.

## Repairs

- New shallow root: `UGTS_AtlasSLAM_3941`.
- Generated build/caches and nested full-package snapshots removed.
- Source-backed, checksum-verifying Gradle 8.13 bootstrap included and tested locally.
- Native Camera2 replaces CameraX.
- Android document picker replaces AndroidX FileProvider export.
- Application dependencies reduced to the local Java core module only.
- Keyframe image/descriptor retention reduced to the active adjacent keyframe.
- Bounded trajectory decimation added.
- Factory intrinsic metadata receives a distinct status from focal-length estimates/fallbacks.
- Release audit checks archive paths, forbidden debris, manifest hashes, and ZIP extraction.
- Documentation now distinguishes host validation, Android build status, and physical-device validation.

## Non-repair claims

The repaired package does not claim that an APK was built when no Android SDK was available, and it does not relabel the older Grove APK as this SLAM application. The source project is the authoritative repaired handoff; build it with the pinned toolchain and then validate the resulting APK on the target phone.
