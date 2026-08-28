# POCO X7 Pro performance report — UGTS-KC 4.1

Measured on 28 August 2026 on the connected Xiaomi 2412DPC0AG (`rodin`), Android 16 / HyperOS 3.0 build OS3.0.301.0.WOJEUXM. The clean POCO release APK was built with SDK 36, NDK 29.0.14206865 and CMake 3.22.1, installed, and left running on the phone.

## ELI5 verdict

Imagine the camera delivers 30 envelopes every second. The code inside each envelope is quick to inspect: normally 1.36 ms, and 99% finish within 6.37 ms. But the worker only opens about 23 envelopes per second because its timer is synchronized badly with a 60 Hz screen loop. About seven envelopes per second get replaced by newer ones before they are opened.

The phone is not struggling. The work uses about half of one CPU core, adds only a few MiB during this run, and stays cool with no Android thermal throttling. The main defect is scheduling, not insufficient POCO hardware.

This is also not a 3D scanner. It has no visual-inertial pose solver, triangulation, depth, metric scale, loop closure, dense point cloud, or mesh construction. It records sparse 2D luma features, IMU summaries and a chained event ledger. Calling the current output a scan would be misleading.

## Measured results

| Item | Result | Plain meaning |
|---|---:|---|
| Clean APK | 1,215,025 bytes (1.16 MiB) | Very small app package |
| Cold launch | 328 ms | Opens in roughly one third of a second |
| Camera | rear ID 0, 1280×720 YUV at requested 30 FPS | Real camera path, not demo fallback |
| IMU | accelerometer + gyro + rotation vector active | All requested sensor feeds opened |
| Sustained capture | 361.58 s | About 6 minutes |
| Camera arrivals | estimated 30.03 FPS | Camera/HAL met the request |
| Frames analyzed | 23.03 FPS | App consumed only about 77% |
| Overwritten frames | 2,529 / 10,857 (23.29%) | Roughly one in four camera frames was superseded |
| Analysis latency | p50 1.355 ms; p95 3.289 ms; p99 6.368 ms; max 26.646 ms | The actual feature/ledger work fits comfortably inside 33.3 ms |
| Camera age at finished analysis | p50 106.739 ms; p95 118.541 ms; p99 122.921 ms | Results describe the scene about a tenth of a second earlier |
| Render + vsync wait | p50 15.684 ms; p95 22.266 ms; p99 25.364 ms; max 31.848 ms | Usually one 60 Hz refresh, with a late tail |
| CPU | ~52% of one logical core | About 6.5% of eight-core capacity; ISP/GPU power excluded |
| Memory | idle 109.2 MiB PSS / 237.2 MiB RSS; peak 113.0 / 241.8 MiB | Only ~3.8 MiB PSS and ~4.6 MiB RSS growth |
| Thermals | status 0 throughout; SoC 47.3–48.6 °C; skin 36.9–37.0 °C | No throttling or meaningful heat ramp in six minutes |
| Ledger output | 805,002 bytes; ~130.5 KiB/min; projected 7.64 MiB/hour | Tiny storage footprint in this scene |
| Captured content | 8,328 observations, 348 keyframes, 8,702 events | About 0.96 keyframes/s and 24.1 events/s |
| Integrity | all header/chunk CRCs, decoded CRCs and SHA-256 chain valid; complete final summary | The pulled file is internally consistent |

The display profile requested 120 Hz, but HyperOS kept the active display/render mode at 60 Hz. The `eglSwapBuffers` wait therefore dominates render timing. The camera-processing limiter checks a 33.33 ms deadline from a roughly 16.67 ms display loop; small timing differences frequently push work to the third display tick. That aliasing explains why fast 1–6 ms analysis still delivers only 23 FPS.

The session observed 7.68 GB of raw luma input while writing 805 KB, a 9,534× ratio. This is **not** a 9,534× image codec. Raw images were discarded. The ledger preserves selected descriptors/events, not the pixels needed to reconstruct the original scene.

Battery drain was not measurable honestly: the handset remained USB-powered and charging. It stayed at 99%, and the charge counter increased by 29 mAh during the monitored five-minute portion. That proves only that the charger exceeded the phone's net load; it does not reveal app watts or unplugged runtime.

## Useful jobs beyond a novelty scanner

### Useful with the code that exists now

- **On-device sensor pipeline benchmark:** it is now a compact reproducible camera + IMU + storage workload with p50/p95/p99 timing, thermal policy and integrity checks.
- **Sparse capture index:** it can mark when luma structure and sensor orientation were observed without retaining raw photos. That is useful for deciding which time ranges deserve a later, richer capture, but the ledger alone cannot show a human what was seen.
- **Offline session provenance:** it produces deterministic event ordering and an internally chained record. This becomes tamper-evident only after the final hash is anchored somewhere an attacker cannot rewrite.
- **Edge-compute feasibility probe:** it shows the POCO has ample CPU and thermal headroom for adding a real model, detector or pose front end.

### Plausible products after specific additions

- **Industrial maintenance walkthroughs:** add manual/object annotations, calibrated timestamps/location, selected encrypted images and hardware-backed signing. The current feature rays do not identify defects.
- **Robot or drone black-box recorder:** add control commands, GNSS/VIO pose, system faults and an off-device signed hash anchor. The current app is not a navigation or safety controller.
- **Repeat-pass change detection:** add pose registration against a reference map and retain enough visual evidence to explain each change. Current luma signatures are not spatially registered.
- **Accessibility or route surveying:** replace the deterministic route demo with calibrated depth/scale, ground-plane estimation, pose tracking and ground-truth studies for clearance and slope. The demo nodes are synthetic, not measurements.
- **Privacy-aware ML triage:** use the sparse ledger to choose short clips or keyframes for upload, with consent and encryption. Raw data is currently unavailable for training or human review.
- **Incident/evidence capture:** add trusted time, hardware-backed signing/attestation and an immutable remote anchor. CRC and a self-contained hash chain detect damage but do not prove who created the file.

## What should be fixed first

1. Decouple capture/analysis scheduling from presentation. Schedule against camera timestamps or a carried-forward deadline instead of resetting `last_processed_ns_` from the 60 Hz render loop. The measured analysis headroom says 30 FPS should be achievable.
2. Avoid copying a full 921,600-byte luma plane from the camera's latest buffer again on consumption. A double buffer or shared ownership would reduce CPU traffic and camera age.
3. Allocate the 160×90 GL texture once and update it with `glTexSubImage2D`; do not call `glTexImage2D` every displayed frame.
4. Bound or page the in-memory ledger for multi-hour use. Growth was small here, but a moving scene can select keyframes as often as every 150 ms—far above this run's roughly one per second.
5. Add hardware-backed session signing and external hash anchoring before using words such as authentic, forensic or tamper-proof.
6. Run controlled moving, low-light and high-detail scenes for 15 and 30 minutes, unplugged power tests, and false/missed-event comparisons against ground truth before making scanner, mapping, safety or accuracy claims.

## Scope and caveats

This is one real handset and one roughly six-minute, uncontrolled camera scene. It is a valid device performance snapshot, not a full product validation. No calibrated route, deliberate motion pattern, low-light sequence, unplugged battery run, 15/30-minute thermal soak, reconstruction-quality study or false/missed-event baseline was performed. A moving/high-detail scene may create keyframes and events much faster, increasing storage and ledger memory.

Artifacts:

- `ugts_perf_20260828.kseed` SHA-256: `076d8f772e30f9d1c53be26c986003acee9a1cf5af1541f6aff2e67fdb36155e`
- clean APK SHA-256: `b9e870520c72ab3c07c0980e6cf688644954e6d05a2d883425125b2ec637e0a0`
- session state hash: `f232762e774fdb5c1f49ac83fd63849bd1b8c463474d3cc49c4c5cff83810fa2`
