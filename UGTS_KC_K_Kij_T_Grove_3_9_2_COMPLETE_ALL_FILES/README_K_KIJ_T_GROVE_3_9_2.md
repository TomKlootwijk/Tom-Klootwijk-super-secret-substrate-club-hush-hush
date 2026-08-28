# UGTS-KC 3.9.2 — K-Kij-T / Grove

Native Android release focused on game-feel (juiciness) and Mali-G720 MC7 execution, with adaptive fallbacks for general Android phones.

## What is actually in this release
- Native Android Studio project, no HTML5 runtime in Grove.
- GLES 3 scene renderer with dynamic internal resolution.
- Full-screen juice/post pass: bloom-like glow, flash, chromatic separation, vignette, saturation/contrast response and pickup/goal shockwave.
- Deterministic Grove juice controller driven by jump/land/pickup/hazard/goal events.
- Device-aware Mali/POCO tuning profile with compatibility tiers.
- KC3D392 scene-pack identifier; parser remains backward compatible with KC3D391.
- 3D interchange files and the original 3.9/3.9.1 assets retained.

## PCG
Procedural content generation remains a future TODO. No PCG implementation is claimed here.

## Build boundary
The Android SDK/NDK and physical POCO X7 Pro are not present in the delivery environment, so no APK/AAB is claimed as compiled or device-tested.
