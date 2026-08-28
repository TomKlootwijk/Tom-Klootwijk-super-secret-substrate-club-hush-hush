# UGTS-KC 3.9.4 - Bayer Direct Native Edition

A deliberately tiny arm64-only Android `NativeActivity` that turns deterministic integer field values into a four-level RGB565 display through an exact 8x8 Bayer ordered-dither matrix.

## Release result

- Final candidate APK: `dist/UGTS_KC_Bayer_Direct_3_9_4_arm64-v8a.apk`
- Formal report: `report/UGTS_KC_3_9_4_Bayer_Direct_Native_Tom_Klootwijk.pdf`
- APK size: **9,438 bytes**
- Native shared object: **6,656 bytes**
- Supplied 3.9.2 APK comparison: **110.20x smaller** by raw file width
- Supplied 3.9.2 native-library comparison: **149.08x smaller** by raw file width
- Release tests: **11/11 pass**

The comparison is not equal-functionality compression. This edition intentionally removes the richer scene, input, asset and graphics stack from the installable hot path.

## Display path

```text
seed + tick + mode
-> integer field F(x,y,q)
-> exact 8x8 Bayer threshold
-> one of four RGB565 palette entries
-> ANativeWindow lock/write/post
-> Android compositor scaling
```

The application:

- requests a 480-class internal buffer and lets the Android compositor scale it to the physical screen;
- uses RGB565, integer-only field evaluation, four compact palettes and four auto-cycling procedural modes;
- runs at a nominal 30 Hz and idles when paused or unfocused;
- contains no app asset, DEX file, mesh, texture, shader, OpenGL ES import, Vulkan import, ray traversal, ray marching or geometry-raster pipeline.

A screen necessarily has a finite pixel surface. The design avoids geometric rasterization: every output sample is a direct field-to-palette query, while the system compositor is only the downstream display endpoint.

## Scope and controls

The four modes are Grove, shell, Kij lattice and SCLP cone/shell. They auto-cycle every 450 ticks, approximately every 15 seconds at the nominal cadence. Touch, audio, networking and persistence are intentionally omitted from this minimal release.

## Installable candidate

```bash
adb install -r dist/UGTS_KC_Bayer_Direct_3_9_4_arm64-v8a.apk
```

The APK is v1 + v2 signed with a self-signed test certificate and targets arm64-v8a, API 26+. No private signing key is included. Replace the test signature for production distribution.

The package was structurally verified, but it was not installed or benchmarked on a physical Android phone in the build environment. First-device launch, lifecycle, buffer format, sustained pacing, memory, power and thermal behavior remain acceptance gates.

## Standard source rebuild

Install Android SDK platform 36, Android Gradle Plugin 8.13.2, CMake 3.22.1 and Android NDK r29 (`29.0.14206865`), then run:

```bash
gradle :app:assembleRelease
```

The Gradle/CMake project is conventional. The bundled ultra-small candidate was also linked from the same C sources through a freestanding AArch64 build and packaged with a verified APK v2 signer because a complete Android SDK/NDK installation was unavailable in the build container. Use the standard NDK path for a production rebuild.

## Verification

```bash
python -m unittest discover -s tests -v
python tools/apk_v2_verify.py dist/UGTS_KC_Bayer_Direct_3_9_4_arm64-v8a.apk
jarsigner -verify dist/UGTS_KC_Bayer_Direct_3_9_4_arm64-v8a.apk
```

Exact hashes, measurements and evidence boundaries are in `manifest/RELEASE_METRICS.json` and `validation/`.
