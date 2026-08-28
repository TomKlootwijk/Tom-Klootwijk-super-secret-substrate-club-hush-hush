# UGTS-KC 3.9.4 Bayer Direct — POCO X7 Pro performance report (ELI5)

Date: 2026-08-28  
Package: `nl.tomklootwijk.ugtskc.bayer.poco`  
Version: `3.9.4-bayer-direct-v001` (`versionCode` 394)

## Bottom line

The source-built release installs, launches, and continuously renders on the POCO X7 Pro. It really does use a tiny 480×216 RGB565 surface and lets Android scale that to the 2712×1220 landscape screen. It stays cool and uses only about one quarter of one CPU core.

It is not ready to ship as an interactive app:

- It delivers about **22.68 fps**, not the intended 30 fps.
- A tap causes an **Application Not Responding (ANR)** because the native activity never consumes its input events.
- It has no external data input, mode selection, persistence, networking, audio, or accessibility path, so the current APK is primarily a procedural display/demo and display-pipeline probe.

The tiny APK is real, but APK size is no longer the main engineering problem. Frame pacing, input handling, useful data integration, and unplugged power behavior matter more.

## Test target and build

| Item | Measured value |
|---|---:|
| Phone | Xiaomi POCO X7 Pro, model `2412DPC0AG`, device `rodin` |
| SoC / CPU ABI | MediaTek `MT6899`, arm64-v8a, 8 CPU cores |
| OS | HyperOS `OS3.0.301.0.WOJEUXM`, Android 16 / API 36 |
| Build fingerprint | `POCO/rodin_eea/rodin:16/BP2A.250605.031.A3/OS3.0.301.0.WOJEUXM:user/release-keys` |
| Physical display | 1220×2712; app ran landscape at 2712×1220 |
| Display during measurement | 120 Hz, fixed brightness setting 255; display service reported approximately 0.50 / 500 nits mapping |
| Build stack | Gradle 8.13, AGP 8.13.2, NDK 29.0.14206865, CMake 3.22.1 |
| Clean release build | Success, 50 Gradle tasks, 20.847 seconds |
| Install | Success via device-side `pm install`; HyperOS rejected the desktop `adb install` frontend with `INSTALL_FAILED_USER_RESTRICTED` |
| Valid cold starts | 246–313 ms |
| Signing | Temporary local test certificate; deployed APK verifies with APK Signature Scheme v2 and v3 |

The production signing key is deliberately absent from the repository. The test certificate was created only for this device run.

## Performance in five-year-old language

Imagine the phone has eight workers. This app keeps roughly **one quarter of one worker** busy. That is light for this phone, but it is not zero work.

The app wants to show 30 pictures every second. It sleeps for 33.3 ms after making each picture. Making and handing over the picture takes roughly another 8–17 ms, so the real interval is usually 41.7–50.1 ms. The nap and the work are added together. That is why it lands near 23 fps instead of 30 fps.

| Metric | POCO X7 Pro result | ELI5 meaning |
|---|---:|---|
| Sustained wall-clock sample | 629.48 s | About 10½ minutes |
| Continuously tracked surface window | 13,328 frames / about 587.6 s | Android recreated the surface near the end; the same process continued rendering on the new surface |
| Delivered frame rate | **22.68 fps** | 24.4% below the nominal 30 fps target |
| Frame interval p50 | **41.694 ms** | Half of frames took at most about 42 ms to arrive |
| Frame interval p95 | **50.077 ms** | 95% arrived within about 50 ms |
| Frame interval p99 | **50.221 ms** | The slow tail is still around 50 ms |
| Maximum observed interval | **66.638 ms** | Worst tracked gap was about two 30 fps slots |
| Intervals over 33.334 ms | 13,183 / 13,327 (**98.9%**) | Almost every frame missed the intended 30 fps interval |
| Intervals over 50.001 ms | 1,662 / 13,327 (**12.5%**) | About one in eight crossed 50 ms, including 120 Hz timestamp quantization/jitter |
| CPU, average | **22.69% of one core** | About 2.84% of the phone's eight-core total capacity if normalized evenly |
| CPU p50 / p95 / max | 22.89% / 26.92% / 27.32% of one core | No sustained CPU spike at mode changes |
| Approximate CPU time per delivered frame | about 10 ms | Derived from steady CPU and frame rate; not an instrumented render-function timer |
| Runtime PSS | 32,690–39,949 KiB; median 38,687 KiB | The app's proportional live-memory bill was roughly 32–39 MiB |
| Runtime RSS | 128,860–144,404 KiB | Includes mapped Android/framework/shared pages; do not confuse it with private app ownership |
| RGB565 buffers | 3 × 202.5 KiB = **607.5 KiB** | Three very small drawing sheets |
| Buffer format and dimensions | format 4 / RGB565, 480×216, stride 480 | The requested compact path was actually granted |
| Thermal status | **0 throughout** | Android reported no thermal throttling |
| Skin temperature | 34.0 °C start, 33.3 °C end, no observed rise | The app did not heat the phone in this connected run |
| CPU temperature | 40.65 °C start, 43.65 °C observed max, 40.23 °C end | Plenty of thermal headroom |

The display was powered over USB during the run. Battery level rose from 97% to 98%, charge counter rose from 5,525,000 to 5,620,000 µAh, and battery temperature fell from 34.0 °C to 33.3 °C. Therefore this run **cannot honestly claim battery drain or watts**. A controlled unplugged run at a fixed brightness is still required.

Android's `gfxinfo` showed no application GL/Vulkan context and three 480×216 format-4 buffers. The Android window framework itself still maps graphics/runtime libraries, which is one reason live memory is much larger than the APK.

## Deployed APK size: where every byte went

The source-built unsigned release was **7,687 bytes**. The exact signed APK deployed to the phone was **17,054 bytes** (16.65 KiB), SHA-256 `ef7242bfa07789fd9a712e19edcde0694499357a393ff7c75e2dc380bb5d975c`.

| Part inside the deployed APK | Stored bytes | Share | What it pays for |
|---|---:|---:|---|
| Compressed native arm64 library | 4,287 | 25.1% | The actual Bayer renderer; 8,616 bytes after extraction |
| `classes.dex` | 662 | 3.9% | Gradle-generated DEX payload; 1,228 bytes raw |
| Binary Android manifest | 970 | 5.7% | Package/activity/SDK declarations |
| Compiled resources table | 840 | 4.9% | App label and theme resource plumbing |
| Gradle/build metadata | 101 | 0.6% | App metadata and version-control metadata entries |
| JAR-signature files | 1,998 | 11.7% | `MANIFEST.MF`, `.SF`, and `.RSA` files; present even though `apksigner` did not count the APK as v1-verified |
| APK v2/v3 signing block | 4,096 | 24.0% | Modern whole-file authenticity seal |
| ZIP headers, alignment and directory records | 4,100 | 24.0% | Container labels, indexes, alignment padding, and end records |
| **Total** | **17,054** | **100%** | The downloadable/deployed APK file |

ELI5: the renderer is only one quarter of the parcel. Nearly half of this unusually tiny parcel is the tamper-proof seal plus the box, labels, and packing space. That overhead looks enormous as a percentage only because the program itself is microscopic.

The deployed APK differs from the bundled hand-packed 9,438-byte candidate:

- The bundled candidate's native library is 6,656 bytes; the standard NDK build's is 8,616 bytes.
- The bundled candidate has no DEX entry; the standard Gradle build includes a 1,228-byte raw `classes.dex` despite the manifest declaring `android:hasCode="false"`.
- The locally generated test signing block is larger. A production key/signing configuration may produce a different final width.

So **9,438 bytes is not the size of the APK tested here**. The tested file is 17,054 bytes.

## Installed footprint: download size is not disk or RAM size

Android stores the 17,054-byte APK and extracts the 8,616-byte native library because `extractNativeLibs` is enabled.

| Installed item | Logical bytes | Allocated/PackageManager view |
|---|---:|---:|
| `base.apk` | 17,054 | 20,480 bytes in filesystem blocks |
| Extracted `libugts_kc_bayer.so` | 8,616 | 12,288 bytes in filesystem blocks |
| APK + extracted native file | 25,670 | 32,768 bytes for the two files alone |
| Whole installed code | — | PackageManager reported **47,104 bytes / 46.0 KiB** |
| App data / cache at measurement | 0 / 0 bytes | No persistent payload was created |

ELI5: the 17 KB suitcase is unpacked at the hotel, so one shirt (the native library) exists both zipped in the suitcase and unpacked in the wardrobe. The filesystem also rents whole storage blocks and directories. When the app runs, Android opens a much larger hotel room—roughly 32–39 MiB PSS—full of shared operating-system furniture.

## Reliability findings

### Release blocker: touch causes ANR

Taps on two separate launches reproduced the same failure. Android's reason was:

`Input dispatching timed out ... NativeActivity is not responding. Waited 5000ms for MotionEvent(action=DOWN).`

The C activity installs no `onInputQueueCreated`/`onInputQueueDestroyed` handlers and never drains or finishes native input events. Even a display-only app must consume/finish input or deliberately configure a safe non-interactive window. This explains why the untouched sustained run was stable while a touched run froze.

### Frame pacing misses its own target

The render loop does:

1. Render and post a frame.
2. Sleep 33,333 µs.
3. Repeat.

That schedules `work time + 33.3 ms`, not a 33.3 ms frame period. Use absolute deadlines (for example monotonic-clock deadline pacing) or an Android frame callback, and request an appropriate surface/display frame rate. The current 120 Hz display quantizes arrivals mostly to five or six refresh intervals.

### What was stable

- No native crash or fatal exception occurred.
- Thermal status stayed at 0.
- Memory settled rather than growing continuously.
- All four procedural modes cycled repeatedly without CPU or memory spikes.
- Android recreated the SurfaceFlinger layer near the end; the process and renderer continued on the replacement surface.

## Useful cases beyond funny wallpapers

### Useful with the current binary

- **RGB565/compositor acceptance probe:** verify that a device grants RGB565 buffers, inspect scaling, palettes, banding, Bayer pattern quality, and navigation-bar interaction.
- **Ordered-dither teaching exhibit:** show how four palette colors can suggest many brightness levels without textures or shaders.
- **Procedural-render microbenchmark:** compare integer-field functions, buffer formats, and direct window writes across Android devices—after adding internal timing counters for rigor.
- **Tiny install/lifecycle smoke artifact:** exercise native loading and surface creation with almost no content dependencies. Touch must be fixed first.

### Valuable after adding a small data/control bridge

- **Low-bandwidth synchronized signage:** send a seed, tick, palette, and a few parameters instead of streaming images. Each device reconstructs the same visual locally. Add networking, resynchronization, authentication, and clock handling.
- **Live sensor/status display:** map temperature, load, machine state, audio envelope, or environmental readings into fields and palette changes. Add data input, labels/accessibility, alarm semantics, and persistence.
- **Deterministic visual IDs:** turn a device ID, build hash, asset ID, or pairing code into a recognizable generated badge. Do not treat human-recognizable art as cryptographic authentication by itself.
- **Offline/error/loading fallback inside a larger product:** embed the tiny C core as a guaranteed asset-free visual when normal textures, networking, or the main renderer are unavailable.
- **Low-color display prototyping:** preview ordered dithering and palette choices for LED matrices, RGB565 embedded panels, retro UI, or print-style halftone work.
- **Generative kiosk/exhibit engine:** parameterize the four fields and allow curated scene changes without shipping texture packs. Add safe input, remote management, accessibility, watchdog behavior, and power-aware display control.

### Poor fits without a redesign

- Interactive apps: touch currently triggers ANR.
- Text-heavy dashboards or safety-critical readouts: four-color procedural fields do not provide labels, precision, or accessibility.
- Photo/video delivery: this renderer reconstructs fields, not arbitrary media.
- Battery-sensitive always-on displays: the app forces the screen on, does not request 30 Hz, and has no validated unplugged power result. The display at roughly 500 nits will likely dominate total power.
- Security tokens or QR replacements: visual similarity is not cryptographic proof, and dithering can hurt machine readability.

## Recommended next engineering steps

1. **Fix input handling first.** Attach and drain the `AInputQueue`, finish every event, and confirm tap/back/home/rotation lifecycle behavior without ANR.
2. **Fix pacing.** Schedule to absolute 33.333 ms deadlines rather than sleeping 33.333 ms after work; request 30 Hz where supported.
3. **Add internal counters.** Record frame work time p50/p95/p99, buffer dimensions/format changes, lock/post blocking time, missed deadlines, and surface recreations.
4. **Add one real data source and one control surface.** Until seed/mode/palette/parameters can come from outside, the broader use cases remain proposals rather than product behavior.
5. **Revisit the standard Gradle package.** Explain or remove the unexpected DEX, decide whether extracted native libraries are worth the duplicate disk bytes, and use the intended production signature configuration.
6. **Run controlled power acceptance.** Unplug USB, fix brightness and refresh policy, start from a recorded charge/temperature, and measure 30 minutes plus background/pause behavior.

## Evidence boundary

Frame intervals came from the middle `actualPresentTime` column of `SurfaceFlinger --latency`, sampled every five seconds and de-duplicated. CPU came from process user/system ticks at five-second intervals. PSS/RSS and thermal values were sampled about every 30 seconds. Percentiles use the nearest lower ranked sample. The final surface identity changed, so frame percentiles cover the continuous 13,328-frame window before that change; logs and process sampling confirm rendering continued afterward.

This report establishes build, install, launch, direct-buffer format, short sustained timing, CPU, memory, and thermal behavior on this exact phone/OS. It does not establish unplugged power, 30-minute stability, production signing/distribution, accessibility, or correctness under user input.
