# UGTOMS Chrono-Geometry Codec 0.1

Status: implementation target. This contract does not promote unsupported
monocular geometry and does not inherit authority from a visually plausible
render.

## 1. Purpose

`UGTC4D` is a custom, profile-specific UGTOMS codec for literal RGB
observations, exact source chronology, projective or bounded geometric support,
static and independently moving charts, and 3D-plus-time lineage. Its default
extension is `.ugtc4d`; its eight-byte magic is `UGTC4D1\0`.

The final stream MUST decode without H.264, HEVC, AV1, JPEG, PNG, WebP,
DEFLATE, or another image/video codec. A conventional decoder may ingest an
MP4 fixture during authoring, but those source bytes are provenance only and
are not the playback payload of `UGTC4D`.

The codec has two simultaneous obligations:

1. reproduce the accepted decoded RGB observations and integer PTS exactly for
   the declared decode profile; and
2. store only spatial support that is traceable to observations and passes the
   declared geometric gates.

The first obligation does not prove the second. Exact pixels are not exact
depth.

## 2. Non-negotiable authority rules

- The coded input hash, decode implementation/profile, decoded-frame hashes,
  integer PTS and exposure-time bounds remain explicit.
- Every pixel has a typed observation address. Omission never means empty,
  disappeared, retracted, or occluded.
- The polar transform is a reversible byte-ordering and prediction domain. It
  is not a camera calibration and does not confer depth.
- Geometry may be `PROJECTIVE_SUPPORT`, `BOUNDED_SUPPORT`,
  `METRIC_SUPPORT`, `PROPOSAL_ONLY`, or `UNBOUNDED_UNKNOWN`.
- Projective support is valid only up to a projective gauge. Relative Euclidean
  support is valid only inside its recorded intrinsics/pose/scale branch.
  Metric support requires accepted calibration and a measured scale anchor.
- A support element cites all contributing pixel footprints, source times,
  operators, residuals, gauge, bounds and verifier receipt.
- Static background and independently moving charts are separate. Residual
  motion is not automatically a person or an object.
- A face, edge, voxel cell or splat MUST NOT connect different source-time
  slices. Temporal continuity is a lineage record, not geometry.
- Unseen backs, silhouette interiors, occluded regions and failed tracks remain
  `UNKNOWN`. Watertight closure is an authored/downstream proxy only.
- A learned mask, feature, depth, pose, normal, body or shape output may seed a
  proposal but cannot promote geometry. Agreement between models consuming the
  same RGB is not independent physical evidence.
- Derived raster, mesh, voxel, collision and route-planning layers cannot write
  canonical observations or geometry.

## 3. Mathematical operator chain

An implementation MUST bind every operator to a versioned registry entry that
states its equation/source, coordinate convention, input domain, deterministic
ordering, thresholds, uncertainty, failure state and implementation digest.
The required non-generative baseline is:

1. immutable source/hash and exact decoded PTS ingest;
2. pixel centers and, when calibration is bounded, row/exposure-aware ray
   tubes;
3. deterministic corner/descriptor candidates and forward-backward tracks;
4. competing homography and fundamental-matrix hypotheses;
5. symmetric-transfer and Sampson residuals;
6. rank-two fundamental projection and degeneracy checks;
7. canonical projective cameras and homogeneous triangulation;
8. for every bounded intrinsics branch, essential-manifold projection,
   relative-pose decomposition, cheirality, parallax and reprojection checks;
9. robust same-chart refinement with gauge and conditioning explicit;
10. deterministic static/background and residual multibody chart branches;
11. visibility states `VISIBLE`, `OCCLUDED`, `OUT_OF_VIEW` and `UNKNOWN`;
12. same-time support commit, temporal lineage, novelty/checkpoint fold and
    downstream materialization.

OpenCV routines are permitted as implementations of declared operators, not as
unexamined authority. Randomized robust estimators MUST use a recorded seed,
canonical input order and complete inlier/residual receipt. Low parallax, pure
rotation, rank failure, poor spatial coverage, dynamic leakage, ambiguous
association or ill-conditioning fails closed.

For uncalibrated pairs, a canonical projective reconstruction may use

```text
P0 = [I | 0]
P1 = [[e1]_x F | e1]
x1^T F x0 = 0
```

where `e1` is the right epipole. Homogeneous `X=(X,Y,Z,W)` is stored only as
`PROJECTIVE_SUPPORT`; it is not interpreted as Euclidean XYZ or SI geometry.

For a bounded calibration branch `K`, the retained Euclidean operator uses

```text
E = K1^T F K0
x ~= pi(P X)
```

with the essential singular-value constraint, the four `(R,t)` pose branches,
positive-depth selection, triangulation and explicit reprojection/parallax/
condition guards. Translation remains gauge-normalized until a measured anchor
is accepted.

## 4. Literal substrate polar domain

The codec embeds the exact `UGLUT2` bytes generated from one declared
`LogPolarProfile`. It does not substitute `UGCVLUT1`, which is a non-invertible
display resampling cache.

For source pixel center `(u,v)` and chart center `(cx,cy)`:

```text
dx    = u - cx
dy    = v - cy
r     = sqrt(dx*dx + dy*dy)
core  = r < core_radius
rho   = log(r/r0)             when not core
theta = atan2(dy,dx) mod 2*pi when not core
```

The existing substrate encodings are retained: a 20-bit closed log-radius code,
an 18-bit periodic angle code and the exact binary16 `UGLUT2` radius/direction
table. Pixel ordinals are sorted canonically by core status, LUT ring, LUT
sector, rho code, theta code, row and column. The resulting Cartesian-to-polar
and polar-to-Cartesian permutation is stored and hash-bound so the decoder does
not depend on cross-platform transcendental rounding. The permutation MUST be
a bijection over every source pixel.

This makes polar ordering an exact transform. No bilinear resampling, border
clamping, duplicate source pixel or uncovered pixel is allowed in the lossless
profile.

## 5. Custom prediction and coding

The 0.1 lossless profile uses only codec-native primitives:

- reversible integer RGB or YCoCg-R lanes;
- polar-order spatial prediction;
- exact temporal prediction from a bounded prior frame/checkpoint;
- optional geometry-warp predictors whose parameters and residuals are stored;
- modulo-byte residuals;
- canonical zero-run, repeated-byte-run and literal-run tokens;
- fixed little-endian integers and canonical unsigned/signed varints;
- per-frame and per-section SHA-256 plus a whole-file digest.

Predictable byte values may be omitted only under the decoder's exact value
delta rule. That is not a semantic retraction. Observation/geometry novelty is
stored separately and omission there means only "no new committed fact".

Every frame records its ordinal, exact source PTS, checkpoint ancestry,
predictor, logical byte count, payload byte count, decoded RGB digest and
payload digest. Checkpoint spacing is bounded so random seek never requires an
unbounded replay.

Lossy profiles, if added, require a named error metric and cannot replace the
lossless evidence profile.

## 6. Container layout

The file begins with a fixed 256-byte little-endian header followed by aligned
sections and a canonical fixed-record directory. The header binds dimensions,
RGB layout, frame count, exact time base, first/end PTS, chart profile,
checkpoint limit, source-coded-byte digest, decoded-stream digest, directory
location and whole-file digest. The digest field is zeroed when recomputing the
whole-file digest.

Required section kinds are:

| Kind | Meaning |
|---|---|
| `MANIFEST` | Canonical profile, authority classes, units/gauge, bounds, dependency and implementation receipts. |
| `OPERATOR` | Provenance-bound mathematical operator registry and parameters. |
| `UGLUT2` | Exact substrate binary16 log-radius/direction LUT. |
| `POLARPIX` | Bijection, chart/code inspection values and LUT dependency hash. |
| `FRAME` | Codec-native polar-ordered RGB checkpoints and novelty residuals. |
| `OBSERVE` | All-pixel source/PTS/exposure/coverage addresses and accepted decoded hashes. |
| `HYPOTHES` | Camera, calibration, gauge, static/dynamic, object/chart, timing, visibility and deformation branches. |
| `GEOMETRY` | Projective, bounded-relative or metric same-time support plus source footprints and verifier receipts. |
| `NOVELTY` | Bitemporal accepted state changes only; no implicit deletion. |
| `CHECKPNT` | Bounded canonical replay states and pre/post hashes. |
| `SCENE3D` | Editable Grove scene binding and downstream materializer declarations. |
| `METROLOG` | Optional calibration, scale/control points, sensor poses, uncertainty and signatures. |

Unknown mandatory section kinds fail closed. Optional sections are explicitly
flagged and remain hash-bound. Directory records are sorted by kind and logical
record start, contain logical/stored sizes, record ranges, SHA-256 and a
domain-separated 128-bit substrate semantic address, and may not overlap.

## 7. Geometry and digital-twin promotion

Each support record contains:

- stable chart/support identifier and content address;
- effective source-time interval and knowledge sequence;
- static/object/part owner branch;
- coordinate frame, unit and gauge state;
- homogeneous projective coordinates or bounded/metric XYZ;
- depth/pose/calibration intervals or covariance where applicable;
- all supporting pixel footprints and independent observation groups;
- visibility state, color/material observation and source hashes;
- reprojection, Sampson, ray-gap, parallax, rank/condition and support-coverage
  receipts;
- pre/post state digests and the operator-registry digest.

Manufacturing, collision, routing or scientific consumers MUST use only support
whose unit/gauge, calibration, uncertainty and intended error contract satisfy
their own acceptance profile. `UNKNOWN` is not free space. Free-space records
require calibrated rays, visibility, a certified nearer surface/depth interval
and explicit uncertainty. A monocular relative/projective fixture therefore
cannot certify manufacturing dimensions or collision-free routes.

## 8. Human specialization

When a target is human, a human chart may add visible 2D joints/parts,
same-time articulated transform hypotheses, joint limits, association branches
and an authored proxy binding. A learned or parametric hidden body is always
`PROXY_ONLY`. Cloth, hair, skin sliding, loose garments and occlusion split or
discontinue charts when rigid/material correspondence fails. No anatomical,
biometric, force, gait-identity or medical claim follows from this profile.

## 9. Engine and cross-platform execution

The editable Grove scene owns one ordinary observation root plus explicit
static/object/chart entities only after promotion. No bootstrap or hidden
code-only scene owns the evidence. The codec reader is a bounded deployment
system; renderer, physics, logic graphs and materializers remain downstream.

RTX authoring may use CUDA for polar gather/scatter, reversible color transform,
prediction, residual/novelty masks and geometric batch operators. A CPU oracle
MUST match all integer codec stages byte-for-byte. Floating geometric results
carry tolerances/bounds and deterministic receipts rather than an unsupported
cross-device bit-identity claim.

POCO execution uses the same `.ugtc4d` bytes, section verifier and predictor
semantics. GLES may use the hash-bound inverse permutation/LUT to materialize a
Cartesian raster, but display conversion and photon timing are downstream.
Physical evidence must hash the installed APK and codec, verify decoded frame
digests before display, prove the actual LUT path, and record timing, memory,
thermal state and fallback.

## 10. Verification and kill conditions

The verifier MUST reject truncated/overlapping sections, noncanonical order,
digest mismatch, malformed varints/tokens, noncanonical tokenization, replay
overflow, invalid permutation, uncovered/duplicate pixels, PTS gaps or reorder
without a declared packet chronology, decoded-frame mismatch, missing operator
preimage, rank/cheirality/parallax/reprojection failure, cross-time geometry,
implicit metric units, geometry without source footprints, or a state change
without a valid receipt.

Required comparison axes are decoded equality/error, bytes, encode/decode time,
random seek, peak CPU/GPU memory, energy/thermals, geometry support count and
coverage, residual distributions, editability and uncertainty. The profile is
narrowed or rejected when the polar/custom coding path is larger or slower
without a measured substrate benefit, geometry does not contract, novelty
density approaches the source/cache size, or a conventional representation is
simpler and equally authoritative.

## 11. Supplied-video expected authority

For `sam_2353410928515192.mp4`, the coded source hash, 229 exact PTS values and
accepted decoded RGB profile can be bound and encoded. Classical multiview
operators may produce static-background and independent-motion projective or
relative branches with source-linked residuals. The file exposes no trusted
intrinsics, distortion, shutter model, metric scale or measured depth, so
metric scene/person geometry and certified free space remain
`UNBOUNDED_UNKNOWN` unless additional evidence is supplied.

That refusal is part of the literal result, not a codec failure.
