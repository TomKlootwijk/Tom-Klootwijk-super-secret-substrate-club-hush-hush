# UGTS-KC 3.9.2 — Native Android Source

This is a dependency-free `NativeActivity` project. The game loop, scene loader, GLES 3.0 renderer,
dynamic-resolution framebuffer, fixed-step gameplay, device tier selection, touch/gamepad input and
adaptive thermal/FPS quality logic, Grove juice events, particles and optional post-processing are
implemented in C++.

## Build

Open this directory in Android Studio, or use the checked, pinned Gradle 8.13 wrapper with Android
SDK 36, Android Gradle Plugin 8.13.2, CMake 3.22.1 and Android NDK r29 (`29.0.14206865`):

```powershell
.\gradlew.bat assemblePocoX7ProDebug
```

Common variants:

- `pocoX7ProDebug`: ARM64-only, explicit POCO X7 Pro 12 GB profile.
- `universalDebug`: ARM64, ARMv7 and x86_64 with runtime profile selection.
- Release variants are source-ready but require your own signing configuration.

The wrapper is copied from the verified UGTS 4.1.1 parent package and pins the distribution SHA-256.
The project intentionally includes no private signing key; use debug builds for direct learning and
device testing, then configure a private release key only when publishing.

## Controls

- Left side drag: movement; left-side tap: jump.
- Right side drag: orbit camera; right-side tap: dash.
- Two-finger spacing: camera distance.
- Gamepad left/right sticks: movement/look; A: jump; B: dash.
- Keyboard: WASD/arrows and Space; Shift: dash.

The runtime currently uses OpenGL ES 3.0. Vulkan is declared optional and reserved as a future backend.
