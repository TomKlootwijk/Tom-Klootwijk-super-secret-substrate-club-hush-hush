# Runtime architecture

## Thread and ownership model

```text
UI thread
  MainActivity / TextureView / overlay / document picker

Camera2 HandlerThread
  preview + ImageReader(maxImages=2)
  acquireLatestImage → FrameAnalyzer

IMU HandlerThread
  bounded orientation and linear-acceleration rings

SlamEngine synchronized authority
  detect → match → estimate → keyframe proposal → guarded map commit

Export executor
  map codec → evidence entries → SHA-256 manifest → .ugtsscan
```

Every acquired `Image` has one owner and is closed in `FrameAnalyzer.finally`. Camera backpressure is bounded by `ImageReader` with two images and `acquireLatestImage()`, so old frames are dropped instead of building an unbounded queue.

## Camera path

The app selects a back camera, requests one preview stream and one `YUV_420_888` analysis stream, and uses continuous-video autofocus with automatic exposure and white balance. The Y plane is rotated into display orientation and downsampled to a maximum long edge of 640 pixels before feature work.

## Core pipeline

```text
GrayFrame
  ↓ deterministic FAST-9 / BRIEF
Feature proposals
  ↓ LSH candidates + ratio + mutual-best guards
Descriptor matches
  ↓ IMU rotation compensation
Epipolar translation direction + inlier quality
  ↓ keyframe interval / translation / rotation / parallax policy
Keyframe proposal
  ↓ positive depth + parallax + ray gap + reprojection guards
Sparse points
  ↓ adjacent-keyframe photometric plane sweep
Semi-dense proposals
  ↓ confidence-weighted quantized voxel fusion
Bounded VoxelMap + ledger events
```

## Memory policy

- The camera queue is bounded.
- The active voxel map is bounded and prunes low-score cells after overshoot.
- The number of keyframe records is bounded.
- Only the active adjacent keyframe retains its grayscale image and descriptor list; older keyframes retain pose, timestamp, camera metadata, and a compact signature.
- Overlay trajectory storage is bounded and deterministically decimated.
- Compact exports omit keyframe images by default.

## Loop closure boundary

A 64-bit keyframe signature can identify a loop-closure **candidate**. This release records the proposal with status `deferred` because a visual-signature match alone is not sufficient to rewrite map geometry. A future implementation should add robust geometric verification and bundle/pose-graph optimization before commit.

## Authority and replay

The core logs ordered events such as session start, tracking initialization, keyframe commit, deferred loop closure, scale anchor, pause/resume, checkpoint, and finish. A committed event has a monotonic sequence. The compact scan stores the ledger as NDJSON and hashes it in the container manifest.
