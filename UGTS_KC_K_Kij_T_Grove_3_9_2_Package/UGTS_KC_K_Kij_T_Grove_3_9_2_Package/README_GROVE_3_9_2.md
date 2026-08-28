# UGTS-KC 3.9.2 — K-Kij-T / Grove

Grove is the native Android upgrade of the UGTS-KC mobile-3D branch. It combines a focused POCO X7 Pro 12 GB / Mali-G720 MC7 profile with adaptive quality paths for other GLES 3 Android devices.

## Native runtime

The generated Grove application is C++ `NativeActivity` code using EGL/OpenGL ES, native input, AAudio, Android haptics, and Android timing/thermal signals. It does not use HTML5, WebView, JavaScript, or WebAssembly.

## Game-feel stack

Gameplay events feed one bounded controller that coordinates particles, trails, impact flashes, camera shake, hit stop, haptics, procedural audio, emissive response, bloom/compositing, vignette, exposure/saturation response, and restrained chromatic separation. Every budget scales through the active quality tier.

## Start points

- Android Studio project: `android/UGTSKCKKijTGrove392`
- Editable project: `examples/k_kij_t_grove_native/project.json`
- Native asset: `examples/k_kij_t_grove_native/grove_scene.kc3d`
- Interchange scene: `examples/k_kij_t_grove_native/grove_scene.gltf`
- Technical guide: `docs/GROVE_DELIVERY_GUIDE.md`
- Build evidence: `docs/BUILD_STATUS_3_9_2.md`
- PCG future scope: `docs/PCG_FUTURE_TODO.md`

## CLI

```bash
ugts-kc new-3d --template grove --creator "Tom Klootwijk" --output grove.json
ugts-kc validate-3d grove.json
ugts-kc pack-3d grove.json --output grove_scene.kc3d
ugts-kc build-android grove.json --output UGTSKCKKijTGrove392 --profile auto
```

The delivery is source-validated but does not claim an APK/AAB or physical-device benchmark. See the build-status document for the exact evidence boundary.
