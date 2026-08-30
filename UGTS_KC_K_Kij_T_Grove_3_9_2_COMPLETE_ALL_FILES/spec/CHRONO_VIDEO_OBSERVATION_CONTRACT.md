# UGTOMS Chrono Video Observation Contract 0.1 (Proposal)

## Scope and authority

This profile converts an ordinary RGB video into a chrono-spatial observation
ledger, a deterministic log-polar sampling cache, and guarded motion/static
proposals. It does **not** complete hidden surfaces, predict depth, infer a
human body, or certify metric 3D from monocular pixels.

The original media bytes and SHA-256 are the photon authority. The source
presentation timestamp (PTS) is the effective-time coordinate. Immutable
decode/accept order is the knowledge coordinate. A polar raster, mesh, voxel,
render, residual, mask, feature, or track is a derivative or proposal unless a
separate physical-evidence verifier promotes it.

`UGLUT2` is unchanged. It remains the shared binary16 kinematics/render LUT.
Video sampling uses the separate `UGCVLUT1` cache because RGB pixel addresses
are not kinematic radius/direction/heading semantics.

## Exact chrono address

For video time base `n/d`, integer PTS `p`, and immutable commit sequence `q`,
the observation address is

```text
effective time = p * n / d seconds
knowledge time = q
address        = (source_sha256, stream_index, p, q, pixel footprint)
```

No floating frame-rate clock may replace the integer PTS address. Display time
on desktop or Android is downstream; a 60 or 120 Hz render loop selects a
source slice by exact rational comparison.

Every source pixel belongs to exactly one half-open coverage tile. Its canonical
scene class starts as `UNKNOWN`. "Not proposed as moving" is not static. The
only accepted geometry status for an uncalibrated MP4 is
`UNBOUNDED_UNKNOWN`.

## Source-pixel log-polar chart

For pixel center `(u,v)`, chart center `(cx,cy)`, reference radius `r0`, and
core radius `rc`:

```text
dx    = u - cx
dy    = v - cy
r     = sqrt(dx*dx + dy*dy)
theta = atan2(dy, dx) mod 2*pi
rho   = log(r / r0), when r >= rc
core  = true, when r < rc
```

The core branch is explicit because `log(0)` is undefined. This chart is a
pixel-address transform, not a camera ray. A physical ray requires bounded
intrinsics, distortion, exposure/rolling-shutter time, and camera pose.

## `UGCVLUT1` derived GPU cache

All integers are little-endian. The fixed header contains:

| Field | Type |
|---|---|
| magic | 8 bytes, `UGCVLUT1` |
| major, minor | `uint16`, currently `1,0` |
| source width, height | `uint32` |
| theta bins, rho bins | `uint32` |
| `cx,cy,r0,rc,rho_min,rho_max` | six IEEE binary64 values |
| payload SHA-256 | 32 bytes |

The payload is a rho-major `RGBA16UI` texture. Each texel is:

```text
R = x0
G = y0
B = fx_q8 | (fy_q8 << 8)
A = valid (0 or 1)
```

The polar sample location is

```text
rho(i)   = rho_min + i/(rho_bins-1) * (rho_max-rho_min)
r(i)     = r0 * exp(rho(i))
theta(j) = 2*pi*j/theta_bins
x        = cx + r(i)*cos(theta(j))
y        = cy + r(i)*sin(theta(j))
```

`x*256` and `y*256` are rounded to the nearest non-negative integer when the
cache is built. A texel is valid only when `x0+1 < source_width` and
`y0+1 < source_height`, so its complete four-neighbour footprint exists;
border clamping is not part of this profile. Sampling is explicit integer Q8
bilinear interpolation:

```text
w00 = (256-fx)*(256-fy)
w10 = fx*(256-fy)
w01 = (256-fx)*fy
w11 = fx*fy
out = (p00*w00 + p10*w10 + p01*w01 + p11*w11 + 32768) >> 16
```

The same arithmetic is used by the NumPy oracle and CUDA backend. Hardware
texture filtering is not the conformance oracle. The payload hash verifies
bytes; it does not make polar resampling invertible. Exact source recovery is
by source reference and SHA-256.

## `UGCVPTS1` finite runtime chronology

Android playback consumes a fixed binary ordinal-to-source-PTS cache rather
than parsing JSON or deriving time from decoded-frame count. All integers are
little-endian. The header is exactly 208 bytes:

| Field | Type |
|---|---|
| magic | 8 bytes, `UGCVPTS1` |
| major, minor | `uint16`, currently `1,0` |
| header bytes, entry bytes | `uint32`, exactly `208,32` |
| flags | `uint32` |
| entry count | `uint32` |
| media width, media height | two `uint32` |
| source frame count, reserved zero | two `uint32` |
| first source PTS, exclusive end PTS | two `int64` |
| time-base numerator, denominator | two positive `uint64`, each at most `INT64_MAX` |
| source, profile, media SHA-256 | three 32-byte digests |
| content SHA-256 | 32-byte digest |
| reserved zero | `uint32` |

The content digest covers the entire file with its own header field replaced by
32 zero bytes. Each 32-byte entry is:

```text
uint32 media_index
uint32 source_frame_index
int64  source_pts
int64  display_until_source_pts
uint32 entry_flags       // zero in 1.0
uint32 reserved          // zero
```

Media indices are dense from zero. Source-frame indices and PTS values increase
strictly. Intervals are positive, contiguous, and half open. Entry zero binds
source frame zero; the final entry binds the final source frame. These guards
make gaps, overlaps, a missing tail, duplicate PTS, and decoder-ordinal drift
explicit failures.

Header flag bits are:

| Bit | Meaning |
|---:|---|
| `1` | byte-identical original source media |
| `2` | derived log-polar preview media |
| `4` | apply `UGCVLUT1` Q8 sampling downstream |
| `8` | media pixels are already log-polar; do not apply the LUT again |
| `16` | explicitly declared loop |

Original media requires bits `1|4`; a preview requires bits `2|8`. The compiler
does not set the loop bit. Both generated chronologies are finite
`ONCE_HOLD_LAST` intervals. Circularity belongs to bounded joint hypotheses; it
is not silently projected onto the recorded source chronology.

`preview_timeline.ugcvpts1` binds every encoded preview ordinal to its selected
exact source PTS. `source_timeline.ugcvpts1` is emitted only with
`--embed-source-for-phone`; it contains every source frame and binds
`source_media.mp4`, whose bytes and SHA-256 must equal the input MP4 exactly.
Version 1 source-mode playback also requires non-negative PTS exactly
representable in MediaCodec microseconds and a no-B-frame source stream,
because extractor ordinal is bound directly to presentation ordinal. A source
with B-frames needs a future packet/decode-order sidecar rather than an
unrecorded reorder assumption.
The JSON preview timeline is an inspectable sidecar, not the native runtime
authority.

The H.264 preview is a diagnostic fallback encoded as Baseline, yuv420p, with
no B-frames and explicit BT.709 limited-range VUI tags. It is lossy and already
log-polar. A phone decoder's YUV-to-RGB conversion remains a display
materialization, not a claim of byte-identical RGB recovery.

## Proposal diagnostics and negative memory

The first implementation tracks visible corners, proposes a frame-to-frame
homography, and evaluates the compensated raster residual per coverage tile.
Every result is tagged `PROPOSAL_ONLY`. A homography may fit a plane, camera
rotation, or a subset of a scene; it cannot certify static 3D or isolate every
moving object.

The novelty ledger records only proposal-label changes. Omission means no
stored proposal novelty. It never means deletion, empty space, disappearance,
occlusion, or retraction. A future authoritative retraction requires a distinct
event backed by calibrated visibility and a certified nearer occluder/free
region.

## Bounded 3D promotion

A pixel footprint becomes a bounded physical ray tube only when calibration,
timing, pose, and depth intervals are finite. Cross-time support may contract a
joint hypothesis over camera, static/dynamic class, object identity, gauge,
object/chart motion, visibility, and deformation. Promotion requires surviving
branches to agree and pass cheirality, parallax, reprojection, conditioning,
independence, rigidity/seam, and occlusion guards. Otherwise the state remains
`BOUNDED_SUPPORT` or `UNKNOWN`.

Meshes, voxels, surfels, and rasterization are same-source-time materializations.
No face, cell, or connected sheet may bridge different source times. Hidden
closure and authored human rigs are `PROXY_ONLY`.

## Execution profiles

`profile.json` carries the exact canonical JSON object whose compact,
key-sorted UTF-8 bytes are hashed as `profile_sha256`. The same semantic digest
is copied into `manifest.json`, both `UGCVPTS1` caches, and the reconstruction
receipt. The ordinary formatted `profile.json` file has its own independent
byte count and SHA-256 in the manifest asset ledger. Verification therefore
recomputes the semantic profile digest from an available preimage instead of
trusting a digest string copied between files.

The profile receipt also records the running UGTS-KC version, the SHA-256 of
the compiler module, Python implementation/version, selected NumPy, PyAV,
OpenCV and (only for the selected CUDA backend) PyTorch/CUDA runtime versions,
plus the first version line returned by the selected FFmpeg and FFprobe
executables. A `null` PyTorch field means it was not selected by the CPU
profile; it does not claim PyTorch was unavailable on the host. These are
provenance observations, not promises that a later verifier is running the
same implementation.

### RTX authoring profile

- PyAV performs the exact-PTS decode and is checked frame-for-frame against
  `ffprobe`.
- PyTorch CUDA applies the integer Q8 LUT in bounded batches.
- A declared workspace limit defaults to 1536 MiB on the 12 GB RTX target.
- The first CUDA result must match the NumPy integer oracle byte-for-byte.
- Hashing, PTS receipts, authority decisions, and promotion gates stay on CPU.

GPU decode may be added as an optimization only when its output frames are
bound unambiguously to the same exact PTS ledger. NVDEC availability alone is
not proof of zero-copy or timestamp parity.

### POCO X7 Pro profile

The phone is a compact evidence viewer and downstream rasterizer, not the first
authoritative monocular compiler. The baseline is ARM64 + GLES 3.0, exact-PTS
selection, a 60 Hz display tier, and bounded streamed assets. The phone's 12 GB
LPDDR is shared system memory, not dedicated VRAM.

The editable Grove scene contains one ordinary `chrono_observation_root` with
no physics writer and a strict sidecar binding. Android packaging may include
the manifest, LUT, ledger, H.264 diagnostic preview, and—only after the explicit
compiler option—the byte-identical source MP4. Runtime selection uses the
`UGCVPTS1` integer intervals; it never substitutes a 60 Hz display counter or
the preview's constant frame rate for source time. Native decoding and GLES
presentation can be host-built and audited, but physical POCO execution and
profiling are still separate evidence gates. Vulkan is not inferred from the
SoC and is not part of this profile.

## Required files

- `manifest.json`: authority, chronology, chart, execution, and asset hashes.
- `profile.json`: canonical profile hash preimage plus recorded implementation
  and selected dependency versions; its full formatted bytes are separately
  hash-bound as a manifest asset.
- `source_receipt.json`: source path/name, size, hash, codec, dimensions, and
  exact time base.
- `observations.jsonl`: every decoded frame and all-pixel `UNKNOWN` coverage.
- `proposals.jsonl`: sampled guarded tile diagnostics.
- `joint_hypotheses.jsonl`: circular camera/class/object/gauge/motion/
  visibility/deformation/timing/depth branches. Missing calibration keeps the
  physical branch `UNBOUNDED_UNKNOWN`.
- `novelty.jsonl`: bitemporal proposal novelty only.
- `polar_lut.ugcv1`: deterministic GPU cache.
- `polar_lut_inspection.json`: strict parsed cache receipt.
- `reconstruction_receipt.json`: parity, backend, evidence, and nonclaims.
- `polar_preview.mp4`: finite H.264 Baseline diagnostic derivative, already
  log-polar and explicitly BT.709 limited range.
- `preview_timeline.json`: inspectable preview-ordinal/source-PTS mapping.
- `preview_timeline.ugcvpts1`: native finite preview timeline bound to source,
  profile, and preview hashes.
- `preview_timeline_inspection.json`: strict parsed preview-cache receipt.
- `source_media.mp4`: optional byte-identical source copy, emitted only by
  `--embed-source-for-phone`.
- `source_timeline.ugcvpts1`: optional all-frame native timeline for the
  embedded source; selects live `UGCVLUT1` application.
- `source_timeline_inspection.json`: strict parsed source-cache receipt.
- `project.json`: editable Grove inspector scene.

Malformed magic, unsupported versions, incorrect payload lengths, payload hash
failure, missing/noncanonical profile preimage, recomputed profile-hash
disagreement, profile/manifest/LUT/execution disagreement, timeline gap/overlap,
cache/media/profile hash disagreement, invalid
bilinear footprint, preview codec/profile/B-frame/color disagreement, embedded
source B-frames or non-microsecond PTS, PTS disagreement, frame-count
disagreement, backend/oracle divergence, source-copy mismatch, or a nonempty
output directory fail closed.

The opt-in phone fixture is compiled explicitly:

```powershell
python -m ugts_kc3 compile-chrono-video input.mp4 bundle `
  --backend cuda --embed-source-for-phone
python -m ugts_kc3 verify-chrono-video bundle
```
