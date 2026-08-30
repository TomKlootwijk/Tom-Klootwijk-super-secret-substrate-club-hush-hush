# Polar Glow manual APK evidence

Status: `built_only`

This folder preserves the fresh `poco-debug` build of `packed-polar-glow-burst-128-lut-subtle.json`. The source export used `build_android_project(..., profile_hint="auto", clean=False, include_authoring_assets=False)` in a new short system-temp workspace, followed by `build_apk(..., variant="poco-debug", clean=False)`. The temporary Android project was removed after the evidence was copied here.

## APK

- File: `packed-polar-glow-burst-128-lut-subtle-poco-debug.apk`
- Size: 1,817,430 bytes
- SHA-256: `17b3dae3c4479b1bd09d335ace551a9414bfd3bacb97bc1c976fa6e5e9c801f4`
- Application ID: `org.ugts.games.packed_polar_recipe_lab_3d.pocox7pro`
- Version: code `392`, name `3.9.2-poco-x7-pro`
- SDK: minimum `26`, target `36`
- ABI: `arm64-v8a` only
- Signature: APK Signature Scheme v2 verified; Android debug certificate SHA-256 `e32bb1f2b68c55f4af54944c3ce5d0384716a01b77ac7fc66df9aa2132db45ba`
- Alignment: `zipalign -c -P 16 -v 4` verified successfully
- Native library: 1,785,400 bytes, SHA-256 `894f3342ff2ad6b9b6eeffe8751998e88a0aa8d22451929874ae919772e22f70`, ELF build ID `fb508e289a93df3f968481ac36b44053e6c82cd8`

The APK contains the native library, scene, visual-graph pack, five runtime shaders, KCPK, KCPR, and KCRP. It contains no authoring project JSON or inspection JSON.

## Packed workload

The generated build report identifies one KCPR v3 Radial Burst recipe: 128 displays from one ECS prototype plus 127 generated non-entity copies. Glow-by-distance is enabled with strength `1.25`; rendering is shared-LUT polar mode with Subtle 64-level Bayer at strength `0.3`.

The preserved runtime packs exactly match their APK entries:

| Pack | Bytes | SHA-256 |
|---|---:|---|
| `packed_kinematics.kcpk` | 1,690 | `9752c2a9c9a892a87628e71b3d9e5a88b41dcac2410a9f8f1360bd79666480b0` |
| `polar_populations.kcpr` | 288 | `4d7f69c230d247188274f963f1896ac1292a54ac216c5e35c34a4668400151a5` |
| `render_substrate.kcrp` | 32 | `e1b6504739e2fbe3c33fefb5bd78a1172a3f93640822dc05aea5c1b6cf38fcfe` |

## Build record

- UTC: `2026-08-30T01:20:54.916185+00:00` to `2026-08-30T01:21:22.930533+00:00`
- Total orchestration: 28.015 seconds
- Source export: 2.094 seconds
- Gradle invocation: 25.896 seconds; Gradle reported `BUILD SUCCESSFUL in 24s`
- Task: `assemblePocoX7ProDebug`
- Project content hash: `ddef49d8c5bccada7d94973940eeb18f635d9e0e3674b712dc917da5b1a1aeb5`

`evidence.json` contains the structured manifest. Raw command evidence is preserved in `aapt-badging.txt`, `apkanalyzer-summary.txt`, `apksigner-verify.txt`, `zipalign-check.txt`, and `native-readelf-notes.txt`. `build-report.json`, `output-metadata.json`, and the complete `gradle-output.txt` are also retained.

## Honest boundary

No installation or ADB command was performed. The ADB serial list is empty. This evidence makes no Poco/Mali runtime, visual-correctness, frame-time, thermal, or performance claim. It proves only that this exact APK built and passed static package inspection.

The build was successful with one NDK deprecation warning for `app_dummy` and a Gradle deprecated-feature notice; both are retained verbatim in `gradle-output.txt`.
