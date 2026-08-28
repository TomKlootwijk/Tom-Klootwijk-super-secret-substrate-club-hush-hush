# POCO X7 Pro 12 GB Runtime Profile

Profile ID: `poco_x7_pro_12gb_seed`

The profile is selected only when runtime hints match the POCO X7 Pro family, a Mali-G720 renderer string, and at least 10,000 MB reported RAM. The product flavor also requests the profile explicitly, but runtime capability checks remain authoritative.

## Requested operating points

| Component | Requested policy |
|---|---|
| ABI | arm64-v8a only |
| Camera | nearest rear YUV_420_888 stream to 1280x720 |
| Capture | 30 fps request |
| Analysis | 160x90 luma |
| Features | up to 128 seeded candidates per keyframe |
| Presentation | 120 Hz request, display/OS permitting |
| Storage | KSEED seed plus deltas, no raw frames |
| Chunk target | 128 KiB |
| Renderer | GLES 3.0 fullscreen Bayer 8x8 dither |

These are requests and policies, not guaranteed physical results. Android display modes, camera capabilities, driver behavior, background load and thermal state remain authoritative.

## Thermal tiers

| Android thermal status | Processing policy |
|---|---|
| 0-1 | profile rate and feature budget |
| 2 | up to 24 fps, at most 80 features |
| 3 | 15 fps, 64 features |
| 4 | 10 fps, 40 features |
| 5+ | pause authoritative capture and flush |

Every thermal-policy change during a recording is itself proposed and committed as a ledger event.

## Why no proprietary accelerator dependency

The first source release intentionally avoids a bundled neural model, TFLite runtime or proprietary MediaTek API. This keeps the source small, buildable with standard Android NDK components, and honest about what is implemented. A distilled model can be added later behind the proposal interface without changing KSEED or ledger authority.
