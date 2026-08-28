# UGTS Atlas Pocket SLAM 3.9.4.1 — POCO X7 Pro performance report

**Measured on:** 28 August 2026  
**Device:** POCO X7 Pro 12 GB (`2412DPC0AG`, MT6899), Android 16 / OS3.0.301.0.WOJEUXM  
**App:** `org.ugts.atlas.slam.pocox7pro`, release 3.9.4.1, target SDK 36  
**Bottom line:** the phone runs the app comfortably, but the current reconstruction is a research prototype rather than a dependable measuring tool.

## ELI5 verdict

Imagine the phone has two jobs:

1. show the camera and controls without stuttering;
2. look at pairs of pictures, find matching speckles, and guess where those speckles sit in 3D.

The POCO is very good at job 1. The display stayed smooth, memory stayed small relative to 12 GB, and Android never declared the phone warm enough to throttle the scanner.

Job 2 is the limiting part. The app actually analyzed about **9.6–9.7 pictures per second**, not the **15 fps** shown in its “normal/15 fps” label. It used about **1.47 CPU cores** while scanning. The moved-camera run created **1,758 voxels**, while the stationary run created only **17**. That difference is expected: translation supplies the changing viewpoints needed for 3D, whereas a stationary camera should create little geometry. Both runs ended at tracking quality **0.01**, so reconstruction accuracy and useful tracking range still require controlled validation.

This is therefore more interesting as an **offline, privacy-conscious capture and evidence pipeline** than as a finished “3D scanner.” It has useful ingredients—trajectory, event history, calibration/scale declarations, compact geometry, and per-entry hashes—but its geometric estimator needs stronger validation and correction.

## What was built and run

- The minified release APK built after correcting two invalid `Surface.close()` calls to Android's real `Surface.release()` API.
- The APK was installed and launched on the connected POCO X7 Pro.
- Camera permission was granted. The manifest requests no network, location, microphone, or broad-storage permission.
- Live Camera2 preview negotiated **1280×960**; the analysis stream was **720×480**, then resampled to a 640-pixel long edge.
- Both runs viewed a textured desk/object scene. The camera was moved during the first run and held stationary during the second. Neither run used a measured path or ground-truth geometry, so they are deliberately **not** claimed as reconstruction-accuracy tests.
- Initial battery was 98% and the phone was connected by USB for ADB. Battery-life/power draw is therefore not reported: the charging cable confounds the reading, and Xiaomi denied shell access to the raw current counter.
- No crash, fatal exception, or ANR was observed.

## Measured performance

| Metric | Result | ELI5 meaning |
|---|---:|---|
| Actual analysis rate | **about 9.6–9.7 fps** | The vision brain digested roughly ten camera pictures each second. |
| Configured normal ceiling | **15 fps** | This is a throttle target, not achieved throughput. The UI label is optimistic if read as a measurement. |
| Thermal fallbacks | 10 fps moderate / 6 fps severe | Neither activated in these two-minute runs. |
| Whole-process CPU while scanning | **146.6%** | Android counts one fully occupied CPU core as 100%; the app averaged about 1.47 cores. |
| Paused camera-preview CPU | **79.6%** | Preview, Y-plane conversion, sensors, and UI consume about 0.8 core even when SLAM is paused. Scanning added roughly another 0.67 core in this comparison. |
| Memory, clean run | **117,742 → 120,936 kB PSS** | Roughly 118–121 MB in Android's accounting; tiny beside 12 GB. No monotonic runaway appeared in two minutes, but this is not a long-duration leak proof. |
| Wider observed memory range | **112,617–126,792 kB PSS** | Sampling, export, and garbage collection moved memory within a modest band. |
| Modern janky-frame rate | **1.19%** | About 99 out of 100 rendered frames met Android's current frame deadline. |
| UI render latency | p50 10 ms; p90 14 ms; p95 16 ms; p99 19 ms | Controls/overlay were usually quick; an occasional frame crossed a 16.7 ms 60 Hz budget. |
| GPU render latency | p50 3 ms; p90 4 ms; p95 5 ms; p99 6 ms | The GPU has ample headroom. This workload is CPU/algorithm limited, not GPU limited. |
| Thermal state | **0 / normal throughout** | Android requested no thermal reduction. |
| Highest observed CPU/GPU sensor | **60.5°C** | Well below the reported 85°C severe threshold during this short run. |
| Highest observed skin/battery sensor | **37.2°C** | Warm but ordinary to hold; no sustained-duration claim beyond the measured runs. |
| APK size | **72,234 bytes (70.5 KiB)** | Exceptionally small because it has no AndroidX, OpenCV, model, or native-library payload. |

### What “PSS memory” means

**PSS** means **Proportional Set Size**. Android counts all memory that belongs only to this app, then gives the app a proportional share of memory also used by the camera service, graphics driver, Android framework, or another process. For example, if two processes share a 10 MB buffer, each is charged roughly 5 MB PSS.

PSS is usually the most useful single answer to “how much physical RAM is this app responsible for?” It is closer than RSS, which counts every shared page in full for every process and therefore makes camera/graphics apps look much larger. The observed RSS was roughly 232–259 MB, but much of that was shared or mapped memory; it should not be read as 259 MB uniquely consumed by UGTS. PSS is still a moving estimate rather than a permanent reservation, because Android can reclaim caches and the number of processes sharing a page can change.

The clean scan's roughly **118–121 MB PSS is about 1% of the phone's 12 GB class of RAM**. That is not high for a live-camera application and leaves ample per-app headroom. The short run showed no steadily increasing trend, although only a longer soak can rule out a slow leak.

Before scanning, the live-preview process had this measured 104,478 kB PSS breakdown:

| Android memory bucket | PSS | Share | What it mostly represents here |
|---|---:|---:|---|
| Graphics | 40,070 kB | 38% | Full-screen window, TextureView/camera surfaces, Vulkan resources, and buffer sharing. |
| Java heap | 21,780 kB | 21% | Activity/UI objects plus current grayscale frames, features, matches, snapshots, trajectory, and map objects. |
| Native heap | 16,620 kB | 16% | Android graphics/camera plumbing and runtime/native allocations. |
| System share | 12,440 kB | 12% | Proportional share of framework/driver pages. |
| Private other | 8,444 kB | 8% | Runtime and memory mappings not classified above. |
| Code | 4,248 kB | 4% | APK/DEX, Android framework code, and shared libraries. |
| Stack | 876 kB | <1% | Java/native thread stacks. |

### Is hardware-camera streaming causing it?

**Yes, substantially—but it is the whole display/camera buffer chain, not a saved video.** The app does not encode or retain a video stream. Camera2 continuously supplies surfaces so the sensor/ISP, camera service, app, GPU, and screen compositor can work without waiting for one another. Multiple buffers are required: while one is displayed, another can be filled and another can be processed.

The phone's graphics report exposed the main allocations:

- the app window is **1220×2712**; each reported full-screen graphics buffer was about **13.2 MiB**, and five were visible in the allocator snapshot;
- the camera preview is **1280×960** with roughly **1.8 MiB** per imported YUV preview buffer;
- analysis is **720×480**, roughly **0.53 MiB** per imported YUV buffer;
- the analysis `ImageReader` is explicitly bounded to **two acquired images** and uses `acquireLatestImage()`, so slow processing drops old frames instead of accumulating a video queue;
- the Vulkan graphics report showed about **67.1 MB of GPU cache/resource usage**, while the imported gralloc view showed about **82.5 MiB**. These are overlapping/shared allocator views and must **not** be added on top of PSS.

The SLAM data is not the dominant baseline cost. Only the previous frame and active adjacent keyframe retain heavy grayscale/descriptor data; older keyframes release those payloads. Collections are capped at 1,100 features per frame, 260,000 voxels, 480 keyframes, 4,096 trajectory points, and 2,400 overlay map samples. The measured moved scan had only 1,758 voxels, far below the cap. Temporary feature/match/snapshot allocations and garbage-collection timing explain some of the rise and fluctuation from the 104 MB preview snapshot to the roughly 118–121 MB scanning level.

The strongest optimization targets would be using a more direct camera presentation path such as `SurfaceView`, avoiding unnecessary full-screen redraw/composition, and skipping luma conversion/SLAM-facing analysis while paused. Lowering preview resolution would reduce camera-buffer size, but the full-resolution app-window buffers would remain unless the presentation design also changes.

### Run details

**Instrumented moved-camera run:** the scan ledger records 142.82 seconds from session start to pause, 1,385 processed frames (**9.70 fps**), 71 keyframes, 1,758 voxels, and final quality 0.01. Camera movement explains the substantially larger map. Repeated accessibility probes added measurement overhead, although the resulting throughput agreed with the cleaner run.

**Clean stationary run:** no UI probe was made during capture. It produced 1,153 frames in approximately 120.5 seconds (**about 9.6 fps**), 29 keyframes, 17 voxels, and final quality 0.01. The low voxel count is directionally appropriate for a stationary null case. Process CPU time increased by 180.10 seconds over 122.88 seconds of wall-clock measurement, yielding the 146.6% figure above.

These two runs cannot measure reconstruction repeatability because only the first included deliberate camera motion. The stationary result is encouraging as a basic null check, although its 29 committed keyframes and 17 voxels show that small image/pose changes still reach parts of the mapping pipeline. A controlled tripod trial and repeated measured trajectories are needed to quantify false geometry and repeatability. The deferred loop-closure proposals still do not correct geometry because bundle adjustment is absent.

## Export and file formats, without the alphabet soup

The measured scan exported as a **15,886-byte** container holding 1,758 voxels and 71 keyframes. The decoder verified every internal SHA-256 value with zero errors. Conversion to PLY succeeded and produced a **69,143-byte** point cloud.

Think of `.ugtsscan` as a labelled lunchbox:

- `map.ugtsbin` is the compact box of quantized voxel centres, grayscale intensity, confidence, and observation counts;
- `trajectory.csv` is the camera breadcrumb trail at accepted keyframes;
- `ledger.ndjson` says what the estimator accepted or deferred and in what order;
- `capture_policy.json` says whether scale is metric, where camera intrinsics came from, and what privacy choices were used;
- `manifest.json` contains hashes that reveal changed/corrupted entries;
- `README.txt` carries human-readable boundaries.

It is an ordinary ZIP/DEFLATE container internally, but `.ugtsscan` is the intended product extension. On this POCO, Android saved the file as **`.ugtsscan.zip`** because the app advertises `application/zip`; that double-extension behavior should be fixed before normal user delivery.

PLY is the easy-to-share photocopy of the dots. It is useful for generic point-cloud tools, but it drops the richer event/evidence context. In this capture PLY stores grayscale as equal red/green/blue values; it is not a textured, photorealistic model.

The recorded voxel size was `0.012`, but the session was `relative_units`. That is **not 12 mm**. It only becomes physically meaningful after a known-distance scale anchor, and even then an anchor fixes scale—not drift, lens distortion, rolling shutter, or bad matches.

Keyframe images are intentionally omitted. That is excellent for storage and privacy, but it prevents later phototexturing and limits offline reprocessing/debugging from the original pixels.

## Useful applications beyond a novelty scan

| Use case | Value available now | What blocks dependable deployment |
|---|---|---|
| Offline maintenance walk-around | Compact local geometry, camera path, timestamps, and an ordered event record without uploading a factory/home view. | Needs repeatability testing, stronger drift rejection, and a workflow for attaching inspection notes. |
| Before/after change capture | Two sessions could become lightweight evidence that an area or asset changed. | Needs reliable cross-session alignment, stable metric calibration, uncertainty bounds, and proven false-change rates. |
| Privacy-preserving spatial inventory | Images are discarded while coarse shape/intensity survives; useful where raw photos are undesirable. | Shape alone may be insufficient to identify items, and repeatability has not yet been measured well enough for automated decisions. |
| Robotics/AR research dataset | Trajectory, quantized map, confidence, calibration source, and estimator decisions are packaged together. | Not safe for navigation/control: no committed loop closure, global optimization, relocalization, obstacle/free-space model, or real-time safety case. |
| Incident/site context record | Hashes detect later byte changes and the ledger explains estimator decisions better than a naked PLY. | Hashes are not signatures, identity, trusted time, or legal chain of custody. External signing and custody controls are required. |
| Rough layout/previsualization | A scale-anchored scan can provide a coarse starting reference for visualization or planning. | Do not use for survey, construction fit, quotes, clearances, volume, or safety decisions without independent control measurements and an accuracy study. |
| SLAM algorithm benchmark/reference | Tiny dependency-free Java implementation is easy to inspect, modify, and compare on phones. | It needs ground-truth datasets and physical trajectories to quantify drift, precision, recall, and reconstruction error. |

The most credible near-term product is not “replace a laser scanner.” It is **an offline spatial notebook with explicit uncertainty and provenance**, aimed at research, maintenance context, or privacy-sensitive capture. Making measurements or autonomous decisions from it would be premature.

## Practical problems found on the real phone

1. **Original source did not compile.** `Surface.close()` was used twice; Android requires `Surface.release()`. The installed APK includes the fix.
2. **The 15 fps label is a policy ceiling, not measured throughput.** Real throughput was about 9.6 fps while the label continued to say `normal/15 fps`.
3. **Accuracy and repeatability remain unmeasured.** The 1,758-voxel run involved camera movement and the 17-voxel run was stationary, so comparing their map sizes is not a repeatability test. Q 0.01 in both runs still deserves explanation before accuracy marketing.
4. **System-bar layout is not Android-16-safe.** The top banner draws under the status bar and the lower buttons overlap the navigation bar. The controls worked, but field ergonomics are visibly compromised.
5. **Export receives a double extension.** The document picker added `.zip` to `.ugtsscan`.
6. **Release signing is still the Android debug key.** Fine for this owner-device build; unsuitable for public distribution or update continuity.

## Recommended next engineering steps

1. Show **measured analysis fps** and processing latency next to the thermal policy label.
2. Validate the existing low-parallax guards with controlled tripod trials; tighten keyframe/triangulation rejection if stationary false geometry remains material.
3. Record confidence distributions and rejection counts so “Q 0.01” has an actionable explanation.
4. Run controlled paths against ground truth: checkerboard intrinsics/distortion, known lengths, repeated loops, static-tripod null tests, and dynamic-scene tests.
5. Add bundle adjustment or another globally consistent correction before promising room-scale repeatability.
6. Fix Android system-bar insets and export MIME/extension handling.
7. Perform a 15–30 minute unplugged thermal and battery trial using an external power meter or a controlled Android energy profiler.

## Reproducibility artifacts

- Installed APK SHA-256: `38943739105e5d23ace1b895bc26f4ec238e151b45490ae6e0598b37e0b8bd72`
- Exported scan SHA-256: `1c30767af1ad3d3d957aae82a2e62c96b9d7fbcc832bc04528c2405c8a2f7cc7`
- Export verification errors: none
- Scan capture-policy claim: offline; factory Camera2 intrinsic calibration; images not persisted; unknown space is not treated as free space

These results apply to this APK, this phone, this scene, and these short runs. They do not establish survey accuracy, long-duration thermals, battery life, or performance on other devices.
