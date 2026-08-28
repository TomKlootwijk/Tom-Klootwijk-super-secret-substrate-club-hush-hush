# UGTS-KC 4.1 POCO Spatial Seed - Android Project

Build the named-device flavor:

```bash
./gradlew :app:assemblePocoX7ProRelease
```

The project is C++20 `NativeActivity` source. It uses Camera2 NDK, Media NDK image reader, Android NDK sensors, EGL/OpenGL ES 3.0, zlib and the portable UGTS 4.1 core. No Java/Kotlin runtime layer and no external Maven runtime dependency are required beyond the Android Gradle Plugin.

See `../docs/CODEX_BUILD_AND_DEPLOY.md` for installation, smoke-test and session-pull commands.

Release source status: host core and source contracts validated; Android SDK/NDK compile and physical-device execution deferred to Codex.
