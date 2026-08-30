# Polar Grow POCO handoff

Status: **installed, launched and profiled on the connected POCO**.

This is the exact 128-display Radial Burst / shared-LUT / Subtle-Bayer Grow lab. It leaves one real
ECS prototype in the world and derives the other 127 visible copies from one compact, seeded KCPR v4
recipe. The generated copies are render data: they do not receive ECS identities, colliders, graph
state, snapshots or picking records.

## What happened on the phone

- Device: Xiaomi/Poco `2412DPC0AG`, codename `rodin`, serial `XOVSTSHYNREMZ5D6`.
- Install: successful; the final Grow build was reinstalled and launched after the A/B. A later
  final check found the USB/ADB connection disconnected, so live control is not claimed now.
- Profile: 30 seconds, six samples, 756 measured frame intervals.
- Result: **120.33 effective FPS** on a 120 Hz surface.
- Frame delivery: p50 **8.380 ms**, p95 **10.113 ms**, p99 **11.295 ms**; one interval exceeded
  1.5 display periods.
- CPU: mean **8.313% of all eight-core capacity**, equivalent to **66.508% of one core**.
- Memory: PSS **143,165–148,551 KiB** (about 139.8–145.1 MiB); RSS **262,770–270,174 KiB**
  (about 256.6–263.8 MiB). This is the whole Android process, not the 304-byte recipe.
- Temperature: exposed GPU sensor **41.897–46.710 °C**; battery **33.0–33.1 °C**; Android thermal
  status **0**.
- Battery: 98% at start and end of the 30-second sample.
- Stability: zero crash-buffer lines and no profile warnings.

The driver did not expose a usable `GL_EXT_disjoint_timer_query`, so GPU-only milliseconds are
honestly unavailable. SurfaceFlinger frame cadence, process CPU/memory and Android thermal values
were available.

## What the native runtime proved

Startup telemetry reported KCPR **format v4**, 128 GPU instances, one shared LUT profile, two GPU
batches, 127 generated GPU copies, zero generated CPU copies, zero CPU fallbacks, one Glow recipe,
128 Glow samples, one Grow recipe, 127 grown copies, 36-byte visible-instance stride and
`ecs_generated=false`. It also reported shared-LUT polar execution and final Subtle Bayer at 64
levels / strength 0.3.

In child-sized language: one real thing carries the game rules; a tiny recipe tells the GPU how to
draw 127 cousins. The same seeded log-polar field first makes each cousin glow and then determines
how much it grows, bounded from 1x to 5x. The original thing and its collider never grow. Bayer is
applied only after the scene is shaded.

## Sizes

| Item | Bytes | Meaning |
| --- | ---: | --- |
| APK | **1,819,202** | Complete ARM64 debug app (about 1.735 MiB) |
| Native ARM64 library | 1,786,936 | C++ engine/runtime inside the APK |
| Editable project JSON | 21,694 | One-click lab source |
| KCPK packed movement | 1,690 | One profile LUT plus one real packed ECS mover |
| KCPR v4 Grow recipe | **304** | Nine meanings, one recipe, 128 requested displays |
| KCRP render settings | **32** | Seed, LUT mode and Bayer settings |
| Visible instance payload | 4,608 | 128 × 36-byte transient GPU staging records |
| Installed private data | 18 KiB | Fresh debug app data measured with `run-as` |

The preserved KCPK/KCPR/KCRP hashes exactly match their entries inside the APK. No authoring JSON or
inspection JSON was packaged.

## Glow v3 versus Grow v4

One sequential 30-second A/B used the same phone, 128 displays, shared LUT and Subtle Bayer:

| Build | Effective FPS | p50 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: |
| Glow v3 | 120.33 | 8.372 ms | 10.041 ms | 11.021 ms |
| Grow v4 | 120.33 | 8.380 ms | 10.113 ms | 11.295 ms |

Both held 120 Hz. The 0.072 ms p95 difference is too small for a single sequential pair to establish
causal overhead; treat it as run-to-run noise, not a victory lap.

## Static verification

- APK SHA-256: `e5348442b3b9e313d10ead1afb636acfa9943cd11f415226f6ea5d255b50232c`
- ARM64 only; min/target SDK 26/36; GLES 3.
- APK Signature Scheme v2 verified with the Android debug certificate.
- `zipalign -c -P 16 -v 4` verified successfully.
- Full suite: **763 tests and 305 subtests passed** in 238.71 seconds.
- Focused integration selection: **48 tests and 62 subtests passed**.
- Independent re-review: clean after version-freezing, sample-reuse and launcher-provenance fixes.

## Files to inspect

- `device-screenshot.png`: physical-device screenshot of the running Grow lab.
- `device-profile-grow-v4.json`: complete Grow metrics.
- `device-profile-glow-v3.json` and `device-profile-comparison.json`: A/B evidence.
- `device-engine-log.txt`: exact native mode/ECS/Glow/Grow telemetry.
- `evidence.json`: structured build, package, workload and device manifest.
- `aapt-badging.txt`, `apksigner-verify.txt`, `zipalign-check.txt`: static APK checks.

This proves a compact technical rendering slice. It does **not** prove finished AAA visuals, broad
gameplay, a production-ready editor UX, statistical power efficiency, or every Direct/LUT/Bayer
matrix combination on the phone.
