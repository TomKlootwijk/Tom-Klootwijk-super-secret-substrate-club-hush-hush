# Grove 3.9.2 build status

Actual native Android source, C++ runtime, shaders, KC3D392 scene, Python package sources and interchange assets are included.

## Verified on 29 August 2026

- All 352 Python regression tests pass, including a compiled host-C++ pointer-ID gesture harness.
- The offscreen UGTS Studio smoke run passes its 2D and 3D scene authoring, selection,
  appearance assignment, undo/redo, logic-graph, live-score and Poco build-target checks.
- The child-friendly mobile first-steps project exports a 308-byte native visual-graph pack and a
  914-byte packed log-polar kinematics asset.
- The local Android SDK 36, NDK r29, Gradle 8.13 and Android Gradle Plugin 8.13.2 compile that
  project as one ARM64 Poco X7 Pro debug APK from the repository's full long Windows path.
- The resulting `build/UGTSFirstStepsPoco392/app/build/outputs/apk/pocoX7Pro/debug/app-pocoX7Pro-debug.apk`
  is 1,351,488 bytes with SHA-256
  `954ECB28E41F79C752151D7D9F9B21BD793106D8AA0DEE5923DD3CD5F069AE96`.
- Android build-tools verify its v2 debug signature. Package inspection reports the expected
  `arm64-v8a` native code, GLES 3.0, minimum SDK 26, target SDK 36 and `NativeActivity` entry point.
- The APK contains `lib/arm64-v8a/libugts_kc_native.so`, the KC3D392 scene, GLES3 shaders, the
  visual graph and the packed kinematics asset. Authoring JSON is deliberately excluded from the
  runtime assets.
- Native touch routing keeps left/right roles by pointer ID, so holding movement while tapping dash
  works regardless of Android pointer-array order. Cancel, drag-not-tap, look and pinch paths are
  covered by the host harness.
- The release wheel and source archive build and install cleanly. Both contain the Android long-path
  workaround; the source archive contains all 24 guides.

## Remaining device boundary

ADB reports no attached device. A physical Poco X7 Pro has therefore not been installed to or
launched from this checkout, so touch feel, Mali-G720 rendering, frame pacing, sustained 120 Hz,
thermals, battery use and memory behavior remain unverified. The profile is a starting policy, not
a performance guarantee. Vulkan is not implemented; the demonstrated Android renderer is GLES3.
