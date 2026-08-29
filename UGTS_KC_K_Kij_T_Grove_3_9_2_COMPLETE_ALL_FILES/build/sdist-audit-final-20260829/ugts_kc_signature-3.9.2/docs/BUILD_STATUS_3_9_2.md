# Grove 3.9.2 build status

Actual native Android source, C++ runtime, shaders, KC3D392 scene, Python package sources and interchange assets are included.

## Verified on 29 August 2026

- All 390 Python regression tests pass, including compiled host-C++ pointer-ID gesture and Trigger
  Area harnesses plus a headless browser Trigger Area lifecycle check.
- The offscreen UGTS Studio smoke run passes its 2D and 3D scene authoring, selection,
  appearance assignment, undo/redo, logic-graph, live-score and Poco build-target checks.
- The child-friendly mobile first-steps project exports a 496-byte two-lesson native visual-graph pack and a
  914-byte packed log-polar kinematics asset.
- The local Android SDK 36, NDK r29, Gradle 8.13 and Android Gradle Plugin 8.13.2 compile that
  project as one ARM64 Poco X7 Pro debug APK from the repository's full long Windows path.
- The resulting `build/UGTSFirstStepsPoco392-final/app/build/outputs/apk/pocoX7Pro/debug/app-pocoX7Pro-debug.apk`
  is 1,381,492 bytes with SHA-256
  `DA0564ACE5BAB8326894DFCA92AB4ECE9632A853AD62CBDE0E635CF152F8EB1D`.
- Android build-tools verify its v2 debug signature. Package inspection reports the expected
  `arm64-v8a` native code, GLES 3.0, minimum SDK 26, target SDK 36 and `NativeActivity` entry point.
- The APK contains `lib/arm64-v8a/libugts_kc_native.so`, the KC3D392 scene, GLES3 shaders, the
  two-graph visual-graph pack and the packed kinematics asset. Authoring JSON is deliberately excluded from the
  runtime assets.
- Native touch routing keeps left/right roles by pointer ID, so holding movement while tapping dash
  works regardless of Android pointer-array order. Cancel, drag-not-tap, look and pinch paths are
  covered by the host harness.
- The release wheel and source archive build and install cleanly. Both contain the Android long-path
  workaround; the source archive contains all 24 guides.

## Remaining device boundary

ADB detected and authorized Xiaomi model `2412DPC0AG` (`rodin`, MT6899), with approximately 12 GB
physical RAM, Mali-G720 MC7 and OpenGL ES 3.2. The editor's one-click path installed and launched the
3.9.2 package, proving the build/install/open loop on real hardware. The phone disconnected before a
sustained capture, so touch feel, frame pacing, requested 120 Hz behavior, thermals, battery use and
runtime memory remain unverified. The exact final APK hash above also still needs an on-device deploy.
The profile is a starting policy, not a performance guarantee. Vulkan is not implemented; the
demonstrated Android renderer is GLES3.
