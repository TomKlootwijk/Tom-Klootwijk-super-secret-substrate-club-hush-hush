# UGTOMS Chrono-Geometry Codec 0.1 (corrected literal profile)

Status: implementation-backed codec contract. The chrono-raster primitives are
implemented, but native mobile playback and committed reconstruction from the
supplied monocular video are not. This contract deliberately refuses to
promote plausible pixels or learned estimates into observed geometry.

## 1. Purpose and lossless authority

`UGTC4D` is a custom, profile-specific UGTOMS container for literal RGB
observations, exact source chronology and source-linked geometric evidence.
Its default extension is `.ugtc4d`; its eight-byte magic is `UGTC4D1\0`.

The lossless authority is the declared decoded stream, not the original
compressed bitstream and not the unknowable camera irradiance. For the current
profile that stream consists of:

- dense frame ordinals;
- each frame's accepted Cartesian `RGB24` bytes at the declared dimensions;
- integer PTS, end-exclusive source interval and rational time base; and
- the decode-profile and coded-source provenance recorded by the manifest.

Strict decoding MUST reproduce those RGB bytes and temporal values exactly.
This is decoded-observation losslessness. It does not promise byte-for-byte
reproduction of the source MP4 container, H.264 NAL units, metadata, discarded
decoder states, sensor samples or photons. The coded-source SHA-256 remains a
provenance anchor.

The final stream MUST decode without H.264, HEVC, AV1, JPEG, PNG, WebP,
DEFLATE, ZIP, Matroska, ISO BMFF or another image/video/container codec. A
conventional decoder may ingest an MP4 fixture during authoring, but the
conventional source payload MUST NOT be embedded as the playback payload of
`UGTC4D`.

Exact pixels and valid 3D are independent obligations. A pixel-exact file may
correctly contain no promoted geometry.

## 2. Non-negotiable authority rules

- Every decoded pixel, whether assigned to a static or moving chart, is an
  observation. Background evidence is not discarded merely because the target
  is a person.
- `STATIC`, `INDEPENDENT_MOTION` and `UNRESOLVED` are tested hypotheses, not
  labels inferred from appearance. A residual is not automatically a person,
  object or deformation.
- Geometry may be `PROJECTIVE_SUPPORT`, `BOUNDED_SUPPORT`, `METRIC_SUPPORT`,
  `PROPOSAL_ONLY` or `UNBOUNDED_UNKNOWN`.
- Projective support is valid only up to a projective gauge. Relative Euclidean
  support is valid only within its recorded intrinsics/pose/scale branch.
  Metric support requires accepted calibration and a measured scale anchor.
- A support element cites its contributing pixel footprints, source times,
  operators, residuals, gauge, bounds and verifier receipt.
- A face, edge, voxel cell or splat MUST NOT connect different source-time
  slices. Temporal continuity is lineage between separately observed states;
  it is not a cross-time sheet or volume.
- Unseen backs, silhouette interiors, occluded regions, textureless regions and
  failed tracks remain `UNKNOWN`. `UNKNOWN` is not empty or free space.
- Learned masks, features, depth, pose, normals, body models or shape estimates
  may propose a branch only. They cannot promote geometry, even when multiple
  learned systems agree on the same RGB input.
- Raster, mesh, voxel, splat, collision and route-planning products are
  downstream materializations and cannot write canonical evidence.
- Compression omission is not semantic deletion. Codec prediction, geometric
  novelty and bitemporal retraction have separate typed meanings.

## 3. Classical geometric operator chain

Every geometric operator MUST have a versioned registry entry stating its
equation or source, coordinate convention, input domain, deterministic order,
thresholds, uncertainty, failure state and implementation digest. The
non-generative baseline is:

1. immutable coded-source/hash and exact decoded RGB/PTS ingest;
2. pixel centers and, when calibration is bounded, exposure-aware ray tubes;
3. deterministic corner/descriptor candidates and forward-backward tracks;
4. competing homography and fundamental-matrix hypotheses;
5. symmetric-transfer and Sampson residuals;
6. rank-two fundamental projection and degeneracy checks;
7. canonical projective cameras and homogeneous triangulation;
8. for every bounded-intrinsics branch, essential-manifold projection,
   relative-pose decomposition, cheirality, parallax and reprojection checks;
9. robust same-chart refinement with gauge and conditioning explicit;
10. competing static/background and residual multibody chart branches;
11. visibility states `VISIBLE`, `OCCLUDED`, `OUT_OF_VIEW` and `UNKNOWN`;
12. same-time support commit, temporal lineage, novelty/checkpoint fold and
    downstream materialization.

OpenCV routines may implement declared classical operators; calling OpenCV is
not itself evidence. Randomized robust estimators MUST use a recorded seed,
canonical input order and complete inlier/residual receipt. Low parallax, pure
rotation, rank failure, poor spatial coverage, dynamic leakage, ambiguous
association or ill-conditioning fails closed.

For uncalibrated pairs, a canonical projective reconstruction may use

```text
P0 = [I | 0]
P1 = [[e1]_x F | e1]
x1^T F x0 = 0
```

where `e1` is the right epipole. Homogeneous `X=(X,Y,Z,W)` remains
`PROJECTIVE_SUPPORT`; it MUST NOT be interpreted as Euclidean XYZ or SI
geometry.

For a bounded calibration branch `K`, the retained Euclidean operator uses

```text
E = K1^T F K0
x ~= pi(P X)
```

with the essential singular-value constraint, the four `(R,t)` branches,
positive-depth selection, triangulation and explicit reprojection, parallax and
conditioning guards. Translation remains gauge-normalized until a measured
anchor is accepted.

## 4. Literal UGLUT2 substrate and new UGTRV1 operator

The stream stores one shared, literal `UGLUT2` generated from its declared
`LogPolarProfile`. `UGLUT2` is the substrate's binary16 radius/direction table;
it is not a picture-sized pixel LUT, a resampled video frame or `UGCVLUT1`.
The shared table is referenced by hash and used for every frame.

The conceptual chart remains

```text
dx    = u - cx
dy    = cy - v
r     = sqrt(dx*dx + dy*dy)
core  = r < core_radius
rho   = log(r/r0)             when not core
theta = atan2(dy,dx) mod 2*pi when not core
```

but a strict decoder does not rerun `log`, `atan2`, normalization or float
nearest-neighbor search for every pixel. It regenerates a canonical full-raster
traversal from the literal `UGLUT2` lanes and `UGTRV1`.

`UGTRV1` is a **new, specialized chrono-codec operator assembled from existing
substrate primitives**. It is not claimed to be an existing capability of
`UGLUT2`. Its fixed 128-byte recipe contains dimensions, root and recipe seeds,
the `UGLUT2` SHA-256 dependency, the operator-meaning hash, a SHA-256 of the
regenerated little-endian `u32` traversal, the center convention, flags and
reserved bytes. No Cartesian-to-polar or polar-to-Cartesian pixel array is
serialized.

The current specialized profile requires:

- canonical center `((width-1)/2, (height-1)/2)` on the half-pixel grid;
- top-left raster coordinates with mathematical positive Y upward;
- a power-of-two `UGLUT2` resolution;
- exact unit `radiusScale == 1`; and
- the first literal UGLUT2 radius equal to the explicit core radius.

For Cartesian address `a = y*width+x`, doubled integer coordinates make the
center exact:

```text
dx2 = 2*x - (width - 1)
dy2 = (height - 1) - 2*y
d2  = dx2*dx2 + dy2*dy2
```

Binary16 radii are decoded exactly to Q16 integers. Radial membership is chosen
by integer squared-midpoint comparisons. Binary16 sine/cosine lanes are
decoded exactly to Q30, and angular wedges are chosen by integer cross-product
comparisons with an exact seam convention. The substrate's 20-bit closed
log-radius and 18-bit periodic-angle domains supply the primary address order.
SplitMix64 lineage, derived from the declared root/recipe seeds and namespace,
sets angular origin/direction and resolves collisions. Canonical Cartesian
address is the final tie-break.

The result MUST contain every Cartesian address exactly once. The decoder
hashes the regenerated little-endian `u32` sequence and compares it with the
recipe digest before decoding frames. The order and its inverse exist only as
bounded working memory. This makes the transform reversible without storing a
per-pixel mapping in the file.

The recipe saves map bytes, not information-theoretic image entropy. Any size
benefit of this ordering and predictor must be measured rather than assumed.

### 4.1 Seed-only boundary

The two current `uint64` seeds occupy 16 bytes. When `recipe_seed == 1` is a
fixed profile constant, the minimum traversal-seed payload is one 64-bit root:
8 bytes. `UGSEED64` is therefore defined only as an external-profile traversal
input. It is not a self-describing file, collision-resistant content identity,
or standalone observation stream.

A fixed decoder maps each 64-bit seed to at most one deterministic output, so a
seed can recreate only state implied by the fixed program and that seed. Exact
camera values not implied by that state are irreducible novelty/literals. If
those values are baked into the player, fetched from a store, or retained in
memory, the eight-byte seed selects evidence stored elsewhere; it does not
compress that evidence. This is the same seed/grammar versus exogenous-novelty
boundary required by the substrate. Generating a plausible replacement is not
lossless observation replay.

## 5. UGFRM2 prediction and UGRICE1 entropy

Each `FRAME` section contains one codec-native `UGFRM2` record with a fixed
320-byte header and one `UGRICE1` residual stream. `UGFRM2` binds:

- frame ordinal, exact PTS and end-exclusive interval;
- checkpoint/dependency state and predictor identifier;
- logical residual and stored payload sizes;
- shared `UGLUT2` and 128-byte `UGTRV1` recipe digests; and
- Cartesian RGB, traversal-ordered RGB, residual, payload and frame-content
  SHA-256 values.

The implemented reversible predictors are:

1. substrate-neighborhood median/green-difference prediction;
2. bounded previous-frame then substrate-neighborhood prediction;
3. Cartesian JPEG-LS MED with green differences, with residual lanes emitted
   in the seed-regenerated substrate order; and
4. Cartesian JPEG-LS MED with the exact green-luma lift, likewise addressed in
   substrate order.

The fourth is the present default. Its reversible byte-domain lift is

```text
Cr = s8((R-G) mod 256)
Cb = s8((B-G) mod 256)
Y  = (G + floor((Cr+Cb)/4)) mod 256

G  = (Y - floor((Cr+Cb)/4)) mod 256
R  = (G + Cr) mod 256
B  = (G + Cb) mod 256
```

`UGCODE24` names the more general rule that one observed RGB8 sample becomes
one reversible three-lane codeword at address `UGTRV1[i]`; rho, theta and
lineage stay implicit in the regenerated address and do not consume the same
24 color bits. A 29-configuration full-clip audit completed 6,641 exact
frame/config round trips with zero failures. QR-like bit-plane serialization
was exact but substantially larger under `UGRICE1`; rearrangement alone is not
compression.

The smallest measured candidate in that audit is now implemented as predictor
14 and uses lane order `[Y,Cb,Cr]`:

```text
Cr = s8((R-G) mod 256)
Cb = s8((B-G) mod 256)
A  = floor((5*Cr + 2*Cb)/16)
Y  = (G+A) mod 256

G  = (Y-A) mod 256
R  = (G+Cr) mod 256
B  = (G+Cb) mod 256
```

All 16,777,216 RGB24 inputs were exhaustively inverted. The re-authored supplied
clip selected predictor 14 for 227 frames, the prior lift for one frame and the
temporal predictor for frame 114. The resulting file is 122,540,032 bytes with
SHA-256 `f1a87daabab4948cf1ad47bc6660963f10470eed3e88516619b1e2a84564ccd5`.
A fresh process re-decoded the original MP4 and matched all 229 RGB24 hashes and
half-open PTS intervals. This is the smallest authored exact result among the
tested profiles, not a global optimum.

The causal JPEG-LS MED equation is

```text
MED(a,b,c) = max(min(a,b), min(max(a,b), a+b-c))
```

with explicit top-row and left-edge rules. Residual arithmetic is modulo 256
and lanes are serialized channel-planar.

`UGRICE1` is a custom canonical block coder. For each block the encoder chooses
the byte-smallest of raw bytes, signed-modulo-256 zigzag Golomb--Rice with
`k in [0,7]`, or a codec-native static byte-rANS stream with a fixed 12-bit
frequency total. Block headers, frequency tables, padding, hashes and the
raw-fallback rule are canonical. A strict decoder rejects alternate encodings
of the same residual bytes. Small metadata may use the container's custom
zero/repeat/literal run tokens; frame evidence does not.

A non-checkpoint frame may depend only on its declared bounded predecessor.
Checkpoint spacing bounds replay for seek. Predictor omission means “recreate
these exact bytes from the declared dependency,” never “the observation did
not exist.”

## 6. Container layout

The file begins with a fixed 256-byte little-endian header followed by
64-byte-aligned sections and canonical fixed 112-byte directory records. The
header binds dimensions, RGB layout, frame count, exact time base, first/end
PTS, chart profile, checkpoint bound, source digest, decoded-stream digest,
directory and whole-file digest. The whole-file digest field is zeroed in its
own preimage.

Required section kinds are:

| Kind | Meaning |
|---|---|
| `MANIFEST` | Canonical profile, authority classes, bounds, dependencies and implementation receipts. |
| `OPERATOR` | Provenance-bound registry of mathematical operators and parameters. |
| `UGLUT2` | One exact shared substrate binary16 radius/direction table. |
| `TRAVERS` | One 128-byte `UGTRV1` seed/operator recipe, including regenerated-order digest; never a pixel map. |
| `FRAME` | Dense `UGFRM2` records with codec-native `UGRICE1` residual payloads. |
| `OBSERVE` | All-pixel source/PTS/exposure/coverage addresses and decoded-stream authority. |
| `HYPOTHES` | Camera, calibration, gauge, static/dynamic, chart, timing, visibility and deformation branches. |
| `GEOMETRY` | Same-time projective, bounded-relative or metric support with source footprints and receipts; otherwise explicit `UNKNOWN`. |
| `NOVELTY` | Bitemporal accepted-state changes only; no implicit deletion and no role in pixel reconstruction. |
| `CHECKPNT` | Bounded canonical replay states and pre/post hashes. |
| `SCENE3D` | Editable Grove scene binding and downstream materializer declarations. |
| `METROLOG` | Optional calibration, scale/control points, sensor poses, uncertainty and signatures. |

There is intentionally no `POLARPIX` section. Unknown mandatory kinds fail
closed. Optional sections remain hash-bound. Directory records are sorted by
kind and logical record start, include logical/stored sizes, record ranges,
SHA-256 and a domain-separated 128-bit substrate semantic address, and may not
overlap.

## 7. Geometry, time and novelty

Each promoted support record contains a stable chart/support identifier,
effective source-time interval, knowledge sequence, owner branch, coordinate
frame, unit/gauge state, coordinates, uncertainty, all supporting pixel
footprints, independent observation groups, visibility, observed color,
residual/gating receipts, pre/post state digests and operator-registry digest.

Static and dynamic evidence share the same exact observation authority but use
separate competing motion branches. Support is committed only within a single
source-time slice. Cross-time records may say that support at `t_i` is a
bounded lineage candidate for support at `t_j`; they cannot create faces,
cells, splats or material between the two observations.

`NOVELTY` records only accepted changes to evidence/hypothesis state relative
to a declared checkpoint. Absence of a novelty record means “no newly accepted
fact,” not disappearance, negative space or predicted replacement. Retraction
requires an explicit bitemporal record preserving the previous fact and the
new knowledge time.

Manufacturing, collision, routing or scientific consumers MUST use only
support whose gauge, calibration, scale and uncertainty meet their own
acceptance contract. Free-space evidence requires calibrated rays, visibility,
a certified nearer surface/depth interval and uncertainty. A monocular
projective reconstruction cannot certify manufacturing dimensions or a
collision-free route.

## 8. Human specialization

When a target is human, a human chart may add visible 2D joints/parts,
same-time articulated-transform hypotheses, bounded or cyclic joint-angle
branches, association alternatives and an authored proxy binding. A learned or
parametric hidden body remains `PROXY_ONLY`. Cloth, hair, skin sliding, loose
garments and occlusion split or discontinue charts when correspondence fails.
No anatomical, biometric, force, gait-identity or medical claim follows from
this profile.

Body4D, MoGe2, DA3, DINOv3, SAM3 and similar learned systems may be evaluated
as proposal generators. Their outputs MUST remain `PROPOSAL_ONLY` until
independent classical image measurements and the declared geometric gates
support a narrower authority. They are not codec dependencies in this profile.

## 9. Engine and cross-platform execution

The editable Grove scene owns an ordinary observation root plus explicit
static/object/chart entities only after promotion. No bootstrap or hidden
code-only scene owns the evidence. Renderer, physics, logic graphs and
materializers remain downstream.

RTX authoring may accelerate gather/scatter, reversible transforms, prediction,
entropy search and classical geometric batches. The CPU integer oracle MUST
produce byte-identical codec stages. Floating geometric results carry declared
tolerances and receipts instead of an unsupported cross-device bit-identity
claim.

Current implementation gap: `UGTRV1` is regenerated and sorted on CPU, then the
order is uploaded for CUDA gather/prediction. The GPU does not yet regenerate
the traversal from the seed and `UGLUT2` by itself. This is an acceleration
gap, not permission to serialize a pixel map.

Current deployment gap: there is no native Android/POCO decoder for `UGTC4D`,
`UGTRV1`, `UGFRM2` and `UGRICE1` yet. A phone build cannot claim native codec
playback until it verifies the same file, recipe/order digest, frame hashes and
PTS replay on-device. An APK that merely embeds or plays the source MP4 does
not satisfy this profile.

## 10. Verification and kill conditions

The verifier MUST reject truncated or overlapping sections, noncanonical
alignment/order, digest mismatch, malformed entropy, noncanonical block choice,
replay overflow, `UGLUT2`/recipe dependency mismatch, regenerated-order digest
mismatch, uncovered/duplicate pixels, PTS interval failure, decoded-frame
mismatch, conventional media payload masquerading as frame evidence, missing
operator preimage, failed geometric gates, cross-time geometry, implicit metric
units, geometry without source footprints, or state change without receipt.

Required comparison axes are exact decoded equality, bytes, encode/decode time,
random seek, peak CPU/GPU memory, energy/thermals, geometry support and
coverage, residual distributions, editability and uncertainty. The profile
must be narrowed or rejected when its custom ordering/coding path is larger or
slower without a measured substrate benefit, geometry fails to contract,
novelty approaches cache size, or another representation is simpler and
equally authoritative. A result must be described as the smallest **measured
among tested configurations**, never as a global information-theoretic optimum.

## 11. Supplied-video expected authority

For `sam_2353410928515192.mp4`, the coded-source SHA-256, 229 accepted frame
ordinals, exact integer PTS intervals and accepted decoded RGB24 profile can be
bound and encoded. A strict lossless claim requires successful full-stream
decode and equality verification against that declared RGB/PTS authority.

Classical multiview operators may attempt separate static-background and
independent-motion projective or relative branches with source-linked
residuals. The file exposes no trusted intrinsics, distortion, shutter model,
metric scale or measured depth. Until those branches pass their gates and are
written with complete receipts, scene/person depth, hidden surfaces, metric
geometry and certified free space remain `UNBOUNDED_UNKNOWN`.

That refusal is part of the literal result, not a codec failure.
