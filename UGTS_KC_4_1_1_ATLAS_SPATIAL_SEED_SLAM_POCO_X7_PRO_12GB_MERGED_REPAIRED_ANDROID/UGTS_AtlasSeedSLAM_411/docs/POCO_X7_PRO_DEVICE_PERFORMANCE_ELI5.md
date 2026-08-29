# POCO X7 Pro device performance report — ELI5

Measured on 29 August 2026 on the connected `2412DPC0AG` handset. This is a short device smoke/benchmark, not a geometric-accuracy certification or a long-duration thermal qualification.

## Bottom line

The app now builds, installs, launches, captures Camera2/IMU data, builds a relative voxel map, exports KSEED, and passes an independent integrity inspection on the actual phone.

The honest verdict is: **good compact offline spatial-evidence prototype; not yet a dependable metric 3D scanner**. Its strongest unusual feature is not the point cloud. It is the combination of an offline proposal ledger, deterministic IDs, synthetic/real isolation, and a small tamper-evident stream.

The main performance limit is CPU analysis. The UI can remain fairly smooth during a camera scan, but the analyzer consumes about 1.5 full CPU cores and delivers only 10.5–11.0 analyzed frames/s while the UI says `normal/15 fps`. That label is a policy target, not the achieved rate.

## ELI5: what the app actually does

Imagine giving the phone a stack of black-and-white postcards from its camera:

1. It finds distinctive corners on each postcard.
2. It tries to find the same corners on the next postcard.
3. The gyroscope helps it understand which way the phone turned.
4. From the apparent corner movement, it guesses how the phone moved and where some scene points might be.
5. Before accepting a keyframe, an eight-part bouncer checks IDs, support, compatibility, guard state, confidence, numeric error, uncertainty, and whether metric scale is required.
6. Accepted decisions and voxel cells go into KSEED, with checksums and a hash chain.

The phone has only one ordinary camera depth view. Until the user supplies a known-distance movement, its coordinates are rubber-ruler units. Applying one distance anchor stretches the whole map to metres, but does not remove drift or warped geometry.

## What was run

- Release build: arm64-v8a, min SDK 29, target/compile SDK 36, R8/resource shrinking enabled.
- Signing: Android debug key in the project's local-owner release configuration; not production signing.
- Cold launches: two measured launches.
- Real Camera2 run: 35.014 s used for the exported artifact; a second 48.291 s run checked map-growth behavior.
- Synthetic demo: full 300-frame, 29.953 s fixture.
- Exports: both real and synthetic KSEED files saved through Android's document picker, pulled back, and inspected independently.
- Instrumentation overhead: two monotonic-clock reads and one ring-buffer write per analyzed frame, with one log line every five seconds.

## Device facts

| Item | Measured value |
|---|---:|
| Phone / device | Xiaomi `2412DPC0AG` / `rodin` (POCO X7 Pro) |
| OS | Android 16, API 36, build `BP2A.250605.031.A3` |
| Security patch | 2026-06-01 |
| SoC identifier / ABI | `mt6899` / arm64-v8a |
| RAM reported by kernel | 11,583,908 KiB (11.05 GiB) |
| GPU | Mali-G720 MC7, OpenGL ES 3.2 |
| Active display | 1220×2712 at 60 Hz |
| Motion sensors seen | ST LSM6DSVQ accelerometer/gyroscope plus MediaTek rotation and linear-acceleration fusion |
| App version | `4.1.1-poco-x7-pro-12gb-atlas-seed-slam` (`40101`) |
| APK | 95,464 bytes; SHA-256 `95a45321c78ca5593379f448bf7181b2dd95cae815ce279ed6e2974a7442d5ff` |

## Performance metrics

### Real Camera2 scan

| Metric | Result | ELI5 meaning |
|---|---:|---|
| Cold launch | 353–451 ms, n=2 | Opens in under half a second. |
| Negotiated streams | 1280×960 preview; 720×480 YUV input | Real device negotiation succeeded. |
| Analysis frame stored | 426×640 luma after rotation/resampling | 272,640 grayscale bytes enter the analyzer per accepted frame. |
| Camera calibration source | Camera2 factory intrinsic calibration | Better than a guessed lens model, but still not a completed per-session calibration check. |
| Effective analyzed rate, 35 s | 10.967 fps | 27% below the 15 fps target. |
| Analysis latency, 35 s | p50 90.498 ms; p95 96.343 ms; p99 121.629 ms | A typical frame needs about one tenth of a second. |
| Effective analyzed rate, 48 s | 11.265 fps at 5 s → 10.478 fps final | Work slows as the map grows. |
| Analysis latency growth, 48 s | p50 89.634 ms at 5 s → 95.425 ms final | Roughly 6.5% median slowdown during this short run. |
| CPU | 148–155% in `top` | About 1.5 fully occupied CPU cores. |
| Memory | 98–102 MiB PSS; 227–238 MiB RSS | Reasonable for a 12 GB phone; native/graphics mappings make RSS larger. |
| UI frame time | p50 12 ms; p95 21 ms; p99 26 ms | Usually responsive at 60 Hz. |
| UI jank | 42 / 2,152 frames, 1.95% | About two visibly late frames per hundred. |
| Thermal, first 35 s | SoC 41.2→56.2 °C; battery/skin 31.2→32.2 °C; Android thermal status 0 | Fast chip heating, but no OS thermal tier or app FPS governor change yet. |
| Real KSEED encoding + fsync | 49.914 ms for 64,733 bytes | Export preparation is effectively instant. |
| Stored rate | ~108.3 KiB/min at this scene/rate | Very small because raw photos are deliberately not retained. |

The exported real run contained 384 frames, 50 keyframes, 102 ledger events, and 12,464 voxels. Its final on-screen tracking quality was only `0.01`, it remained unanchored, and it recorded zero rejected proposals. No deliberate physical scan path or reference target was supplied by the automated run, so this is a throughput result—not evidence that those voxels match the room. Committing many voxels at very low displayed quality deserves controlled static-scene and ground-truth testing.

### Synthetic demo

| Metric | Result | ELI5 meaning |
|---|---:|---|
| Effective rate | 10.016 fps for 300 frames | It holds its designed 10 fps schedule. |
| Generate + process latency | p50 50.726 ms; p95 53.920 ms; p99 62.361 ms | About half of each 100 ms slot is computation. |
| CPU | 66.6–92.3%, median about 70% | Usually less than one full CPU core. |
| Memory endpoint | 116 MiB PSS; 247 MiB RSS | Slightly above the camera-run PSS. |
| UI frame time | p50 17 ms; p95 26 ms; p99 28 ms | The median misses a 60 Hz frame deadline. |
| UI jank | 282 / 782 frames, 36.06% | Demo visualization is much less smooth than real scan mode. |
| KSEED encoding + fsync | 11.180 ms for 43,907 bytes | Export preparation is very quick. |

The demo produced 300 frames, 44 keyframes, 89 events, 8,483 voxels, and one rejected proposal. Every chunk carries the synthetic bit, and the session summary also marks it synthetic.

### Metrics not honestly available from this run

- Battery energy per minute: the phone was USB-powered and charging, so charge-counter movement is not a valid consumption measurement.
- 5/15/30-minute thermal stability: only short 30–48 second runs were performed.
- Metric distance error, closed-loop drift, false/missed proposal rates, and comparison to a calibrated scanner: these need a moved phone, measured control targets, a repeatable route, and an external ground-truth device.
- Legal/authentic custody: KSEED is hash-chained but is not signed by a protected device/user identity and has no trusted timestamp.

## KSEED file format in plain English

KSEED is like a box of numbered, sealed envelopes:

- The 128-byte box label records the format version, seed, dimensions, target FPS, feature budget, and hashes of the capture/calibration descriptions.
- Each 64-byte envelope label records its type, order, item count, compressed/uncompressed sizes, CRCs, schema ID, and the next SHA-256 chain link.
- The envelopes contain frame evidence, accepted keyframes, ordered decisions, Morton-sorted voxels, calibration/profile information, and a final summary.
- Delta coding, varints, int16 sensor values, sorted voxel keys, and optional zlib level 1 keep it small.

What the seals prove: the captured file has not been silently changed after export, assuming the verifier itself is trusted.

What they do **not** prove: that the camera saw the claimed place, that the operator is who they claim, that the clock is trusted, or that the geometry is accurate. SHA-256 here is neither encryption nor a digital signature. KSEED also omits raw frames, so its 1,617× real-run “raw input to stored evidence” ratio is not reversible image compression.

The independently inspected real file passed all header/chunk CRCs, zlib decoding, sequence checks, final-summary checks, and the SHA-256 chain. Its SHA-256 is `ccb545d8a729b2819de32679f16a76629644708de2604c4e444d7a56c4601837`. A 440,265-byte PLY containing 12,464 voxel centers was also generated, but PLY is only a viewing derivative and loses the evidence ledger.

## Useful applications beyond “a funny 3D scanner”

| Use case | Why this architecture is interesting | What must improve first |
|---|---|---|
| Offline facility walk-through notes | No network permission; compact local spatial breadcrumbs can attach inspections to approximate places. | Stable relocalization, annotations, tested scale, and user-visible quality rejection. |
| Construction/progress change capture | Repeated KSEED sessions could compare occupied regions while retaining a decision ledger. | Global alignment, loop closure/bundle adjustment, exposure robustness, and ground-truth validation. |
| Privacy-conscious edge telemetry | It stores compact derived evidence instead of raw room photos and detects later file corruption. | A clear privacy model; derived geometry can still reveal sensitive layouts. |
| Robot/AR mapping research | Deterministic IDs, proposal gating, relative poses, voxels, and PLY export make a small experimental front end. | Real loop-closure optimization, better VIO, calibration, and a standard interchange bridge. Not navigation-safe now. |
| Asset-layout and inventory hints | Relative spatial relationships can answer “roughly where was this seen?” without cloud processing. | Object recognition/labels, multi-session anchors, uncertainty propagation, and false-positive testing. |
| Tamper-evident sensor decision log | The ledger/hash-chain pattern can record any edge algorithm's proposed and accepted state changes, not only SLAM. | Protected signing keys, trusted time, schema governance, and external audit tooling. |
| Reproducible algorithm QA/teaching | The synthetic seed produces a repeatable workload while clearly tagging it as non-real evidence. | More fixtures, known expected geometry, regression thresholds, and device-to-device comparison. |
| Rough digital-twin seed | A tiny voxel cloud can initialize later desktop reconstruction or visualization. | Retain/select source imagery or descriptors, add accurate poses, and use a real optimizer; current PLY is not survey data. |

The most credible near-term product is an **offline, integrity-checked spatial observation log** for non-safety-critical workflows. Calling it a measurement-grade scanner, autonomous-navigation map, legal evidence system, or emergency/medical tool would be unjustified today.

## Problems found on the actual phone

1. The original source did not compile: it called nonexistent `Surface.close()` methods. Both calls were corrected to Android's `Surface.release()`.
2. The long Windows workspace path made CMake/Ninja regenerate `build.ninja` until aborting. Building through a temporary short drive mapping succeeded without relocating the project.
3. The UI says `normal/15 fps`, but that is the thermal policy label. Actual analyzed throughput was 10.5–11.0 fps.
4. The lower button row occupies y=2530–2686 while the system navigation region starts at y=2559. On this handset, 127 pixels of the buttons are under the navigation bar; tapping their center can send the user Home instead of exporting or starting Demo.
5. Demo UI updates every synthetic frame and showed 36% jank even though processing met 10 fps.
6. Map cost grew measurably over 48 seconds. Longer runs up to the 260,000-voxel/480-keyframe caps need profiling.
7. The real exported run ended at quality 0.01 yet contained 50 committed keyframes and zero rejected proposals. A controlled static-phone test is a promotion gate.

## Recommended next engineering pass

1. Make the thermal label and achieved analysis FPS separate UI values.
2. Move controls above system insets and reduce Demo redraw frequency to the same capped UI cadence used by Camera2.
3. Add a hard low-quality/no-parallax state that blocks map growth and explains why to the operator.
4. Profile feature detection/matching and semi-dense fusion separately; adapt feature/depth budgets to a real frame-time budget.
5. Run 5/15/30-minute unplugged tests with power rails or a validated battery method.
6. Run calibrated known-distance, static-scene false-motion, repeated route, closed-loop drift, and scanner-comparison trials.
7. Add protected signing/trusted-time support only if authenticity or custody is a real requirement.

## Delivered artifacts

- `app/build/outputs/apk/release/app-release.apk` — installed device release APK.
- `validation/device_real_35s_unanchored.kseed` — real Camera2 device export; integrity PASS.
- `validation/device_real_35s_unanchored.ply` — non-authoritative voxel visualization derivative.
- `validation/device_demo_300_frames.kseed` — full synthetic device export; integrity PASS.
