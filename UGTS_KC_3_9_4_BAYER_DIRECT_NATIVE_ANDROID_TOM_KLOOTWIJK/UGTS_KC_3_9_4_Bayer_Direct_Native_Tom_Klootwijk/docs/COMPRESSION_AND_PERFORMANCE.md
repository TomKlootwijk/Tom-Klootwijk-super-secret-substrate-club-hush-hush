# Compression and performance design

## Compression hierarchy

1. Remove representation layers before applying compression codecs.
2. Ship one ABI only: arm64-v8a.
3. Reconstruct frames from seed, tick and mode instead of storing images.
4. Use a 480-class finite internal lattice and RGB565.
5. Keep one C shared object with one exported application entry.
6. Exclude DEX, Java/Kotlin, assets, textures, meshes, shaders and graphics libraries.
7. Build for size with LTO, hidden visibility and section garbage collection.

The final 9,438-byte APK is 110.20x smaller than the supplied 1,040,086-byte 3.9.2 APK. The 6,656-byte shared object is 149.08x smaller than the supplied 992,256-byte stripped native library. These are raw byte-width comparisons, not equal-functionality compression ratios.

## Bounded frame budget

The 480x216 reference lattice contains 103,680 samples. RGB565 occupies 207,360 bytes per frame, or 202.5 KiB. At a nominal 30 Hz, direct fill traffic is approximately 5.93 MiB/s before system-side buffer management and compositor overhead.

The bundled x86_64 host benchmark reached a median 70.303 million pixels/s across five runs. That result validates deterministic reference behavior and algorithmic headroom on the host only. It is not an Android phone benchmark.

## Target-device gates

A mobile performance claim requires an exact device/OS build, actual native-window dimensions and format, p50/p95/p99 producer time, missed 30 Hz intervals, memory footprint, CPU frequency residency, battery discharge, thermal status and sustained 10- and 30-minute runs.
