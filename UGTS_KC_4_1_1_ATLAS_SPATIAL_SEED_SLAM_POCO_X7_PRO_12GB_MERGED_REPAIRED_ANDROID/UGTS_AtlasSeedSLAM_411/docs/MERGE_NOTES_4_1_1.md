# 4.1.1 merge notes

## Available implementation base

The available repaired 3.9.4.1 project supplied a short-path Android Studio tree, verified Gradle bootstrap, Java Camera2/IMU capture shell, platform-independent SLAM core, compact legacy export and host validation.

## Imported from the documented 4.1.0 contract

- Session seed versus measured-evidence separation.
- KSEED 128-byte header, 64-byte chunks and 60-byte summary.
- Delta timestamps/frame indices, int16 inertial quantization, Morton coordinate deltas and base-128 varints.
- Zlib `BEST_SPEED` only when compressed payload plus 16 bytes is smaller.
- Header/chunk CRC32 and chained SHA-256 integrity.
- Ordered verifier gates and pre/post state hashes.
- Stable identity independent of coordinates.
- Synthetic fallback isolation and tag bit 31.
- Optional Bayer four-level projection.
- Arm64-v8a native profile and SDK/NDK/CMake pins.
- Explicit source/device promotion gates.

## Deliberate fusion decisions

The repaired Java Camera2 and Java SLAM front end remains the active capture/mapping implementation. A narrow C++/JNI module accelerates seed scheduling and CRC work without moving map authority out of the verified Java core. This avoids a risky total rewrite into NativeActivity while still delivering an actual native component and portable C++ oracle.

KSEED becomes the default export. The legacy `.ugtsscan` reader remains in `tools/` to preserve previous captures, but the app no longer writes it by default.

## Not silently claimed

- No metric visual-inertial estimator.
- No bundle adjustment or committed loop closure.
- No dense learned depth or transformer.
- No certified semantic/topology recognition.
- No Android assemble in this packaging environment.
- No physical POCO X7 Pro installation, sustained frame-rate, thermal, battery or accuracy result.
