# UGTS-KC 3.9.1 Tom Klootwijk Signature — Native Android Source

This is a dependency-free `NativeActivity` project. The game loop, scene loader, GLES 3.0 renderer,
dynamic-resolution framebuffer, fixed-step gameplay, device tier selection, touch/gamepad input and
adaptive thermal/FPS quality logic are implemented in C++.

## Build

Open this directory in Android Studio, or use Gradle 8.13 with Android SDK 36, Android Gradle Plugin
8.13.2, CMake 3.22.1 and Android NDK r29 (`29.0.14206865`).

Common variants:

- `pocoX7ProDebug`: ARM64-only, explicit POCO X7 Pro 12 GB profile.
- `universalDebug`: ARM64, ARMv7 and x86_64 with runtime profile selection.
- Release variants are source-ready but require your own signing configuration.

The project intentionally does not include private signing keys or a fabricated Gradle wrapper JAR.

## Controls

- Left side touch: movement.
- Right side drag: orbit camera.
- Two-finger spacing: camera distance.
- Gamepad left/right sticks: movement/look; A: jump.
- Keyboard: WASD/arrows and Space.

The runtime currently uses OpenGL ES 3.0. Vulkan is declared optional and reserved as a future backend.
The 4D work is a design-only TODO documented in the parent archive.
