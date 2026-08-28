# POCO X7 Pro 12 GB profile

The profile is a conservative source configuration rather than a measured benchmark.

```text
analysis long edge       640 px
normal / warm / hot      15 / 10 / 6 analysis fps
maximum features         1100
minimum visual matches   24
active voxel ceiling     260000
keyframe interval        at least 360 ms
keyframe ceiling         480
trajectory ceiling       4096 samples before deterministic decimation
semi-dense pixel step    6
keyframe image export    disabled
runtime network          disabled
```

The 12 GB device edition motivated a relatively generous bounded voxel map, but Android application heap limits are separate from installed RAM. The core therefore releases historical keyframe pixels/descriptors and bounds all principal collections.

A target-device validation run should record:

- exact OS/build and camera ID used;
- analysis and preview sizes;
- intrinsics source string;
- p50/p95/p99 analysis latency;
- sustained frame rate and dropped-frame count;
- thermal state over at least 20 minutes;
- peak Java/native memory;
- battery change and device temperature;
- reconstruction error against measured control geometry;
- exported bytes per accepted voxel and per minute.
