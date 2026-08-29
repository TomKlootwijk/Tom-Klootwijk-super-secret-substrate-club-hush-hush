# Grove 3.9.2 build status

Actual native Android source, C++ runtime, shaders, KC3D392 scene, Python package sources and interchange assets are included.

## Verified on 29 August 2026

- All 412 Python regression tests pass, including Logic Trail immutability, Populate Area binary and
  authoring coverage, compiled host-C++ parity fixtures, and a headless browser Trigger Area lifecycle
  check.
- The offscreen UGTS Studio smoke run passes its 2D and 3D scene authoring, selection,
  appearance assignment, undo/redo, logic-graph, live-score and Poco build-target checks.
- The child-friendly mobile first-steps project exports a 496-byte two-lesson native visual-graph pack,
  a 914-byte packed log-polar kinematics asset, and a 60-byte `KCSP392` recipe that represents one
  authored crystal plus 17 deterministic render-only copies.
- The local Android SDK 36, NDK r29, Gradle 8.13 and Android Gradle Plugin 8.13.2 compile that
  project as one ARM64 Poco X7 Pro debug APK from the repository's full long Windows path.
- The resulting `build/UGTSFirstStepsPoco392-populate/app/build/outputs/apk/pocoX7Pro/debug/app-pocoX7Pro-debug.apk`
  is 1,436,161 bytes with SHA-256
  `0696375DD496ADC6D71505749BB760E4EBF7F05D2A76030F0B38577BD022B3DD`.
- Android build-tools verify its v2 debug signature. Package inspection reports the expected
  `arm64-v8a` native code, GLES 3.0, minimum SDK 26, target SDK 36 and `NativeActivity` entry point.
- The APK contains `lib/arm64-v8a/libugts_kc_native.so`, the KC3D392 scene, GLES3 shaders, the
  two-graph visual-graph pack, packed kinematics asset and `scatter_populations.kcsp`. Authoring JSON
  is deliberately excluded from the runtime assets.
- Native touch routing keeps left/right roles by pointer ID, so holding movement while tapping dash
  works regardless of Android pointer-array order. Cancel, drag-not-tap, look and pinch paths are
  covered by the host harness.
- The release wheel and source archive build cleanly. A fresh wheel install passes the complete
  offscreen editor smoke and emits the same 60-byte KCSP asset from its packaged Android template.
  Distribution hashes are recorded after packaging rather than embedded in these packaged docs.

## Remaining device boundary

ADB detected and authorized Xiaomi model `2412DPC0AG` (`rodin`, MT6899), with approximately 12 GB
physical RAM, Mali-G720 MC7 and OpenGL ES 3.2. The editor's one-click path installed and launched the
3.9.2 package, proving the build/install/open loop on real hardware. The phone disconnected before a
sustained capture, so touch feel, frame pacing, requested 120 Hz behavior, thermals, battery use and
runtime memory remain unverified. The exact current APK hash above also still needs an on-device deploy;
`adb devices -l` reported no attached device during the final build check.
The profile is a starting policy, not a performance guarantee. Vulkan is not implemented; the
demonstrated Android renderer is GLES3.
