# Android Native Architecture

## Runtime path

```text
NativeActivity lifecycle
  -> camera permission gate
  -> NDK Camera2 YUV_420_888 stream
  -> latest-frame luma copy
  -> NDK IMU snapshot
  -> seeded 160x90 sparse feature analysis
  -> deterministic keyframe gate
  -> typed Observation/EventProposal records
  -> ordered ProposalVerifier gates
  -> SpatialLedger verified commit
  -> KSEED chunk writer + SHA-256 chain
  -> Bayer-dithered display projection
```

## Authority split

`camera_ndk.cpp` and `imu_ndk.cpp` provide observations. `feature_extractor.cpp` provides deterministic candidates. Neither writes authoritative state.

`verifier.cpp` applies support, compatibility, guard, confidence, numeric error, uncertainty and metric availability gates. `ledger.cpp` is the only state mutation boundary. Every accepted event has a pre-state and post-state hash.

`renderer_bayer.cpp` is a projection. It displays camera luma, feature marks, a deterministic route demo, or a state-hash visualization. It cannot commit an event and cannot be used as measurement authority.

## Threads and buffers

- Camera callbacks acquire the latest image and replace one mutex-protected luma buffer. Old frames are intentionally dropped rather than queued without bound.
- Sensor callbacks update one mutex-protected latest IMU state.
- The NativeActivity loop consumes at the thermal-policy process rate.
- KSEED writes are sequential and chunk bounded.
- The renderer uses one 160x90 R8 texture and a fullscreen triangle.

This design trades dense imagery and large queues for bounded memory, low storage, deterministic replay, and graceful thermal reduction.

## Real and synthetic sources

When the camera is active, records originate from actual Y-plane measurements plus NDK sensor values. When the camera cannot start, the app generates a deterministic fallback pattern so the UI, ledger and storage can be tested offline. Synthetic proposals carry bit 31 in `tag_mask` and must never be presented as camera evidence.

## Extension point for SLAM/model inference

A future visual-inertial or transformer module should be inserted between feature extraction and proposal creation. It may add pose, depth, normal, semantic, topology and uncertainty proposals. It may not bypass `ProposalVerifier` or write directly to `SpatialLedger`.
