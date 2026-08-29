# UGTS-KC 3.9.2 — K-Kij-T / Grove

Creation-engine release focused on a learnable desktop workflow and a compact native Mali-G720 MC7
result, with adaptive fallbacks for general Android phones.

## What is actually in this release

- Dockable PySide6 UGTS Studio with 2D/3D scene authoring, undo/redo, picture/shape/material choices,
  real preview, readable checks and direct build targets.
- Typed visual Logic Blocks shared by the desktop runtime, the retained 2D HTML5 exporter and a
  deliberately validated native Android subset.
- ECS composition plus two-word packed log-polar pose/motion components and shared binary16 LUTs.
- Native Android Studio/Gradle project with a GLES3 renderer, dynamic internal resolution,
  pointer-ID-aware two-thumb controls and adaptive Poco/general-device profiles.
- Full-screen Grove juice/post pass with glow, flash, chromatic separation, vignette,
  saturation/contrast response and pickup/goal shockwave.
- KC3D392 scene packs, glTF interchange and all retained 3.9/3.9.1 2D, browser and 3D APIs.

## PCG

Procedural content generation remains a future TODO. No PCG implementation is claimed here.

## Build boundary

The local Android SDK/NDK compiles the included child-friendly project into a v2-signed ARM64 Poco
debug APK. No physical Poco X7 Pro is attached, so installation, on-device touch feel, Mali rendering,
frame pacing, thermals and battery behavior are not claimed. Vulkan and a full AAA asset/content
pipeline remain future work.
