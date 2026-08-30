# UGTOMS GSP4 Seed Camera Storage Profile 0.1

Status: implementation profile, not a standards claim.

This profile is the authoritative target for the POCO X7 Pro work. It is a
camera-to-seed-program-to-camera-samples path. It does not wrap MP4, H.26x,
AV1, MediaCodec output, a picture-sized LUT, or a generative model.

## 1. Required execution chain

```text
Camera2 AImage YUV_420_888
  -> dense canonical Y, U and V evidence planes
  -> UGCODE24-420 logical codewords
  -> seed + literal UGLUT2 regenerated log-polar addresses
  -> GSP4 support / compatibility / finite guard
  -> exact residual novelty events and negative memory
  -> hash-linked append-only seed storage program
  -> inverse substrate execution
  -> byte-identical dense Y, U and V planes plus sensor timestamps
```

The final display conversion is downstream. It is not the stored lossless
authority.

## 2. Camera authority

The accepted observation is the normalized crop of an `AIMAGE_FORMAT_YUV_420_888`
`AImage`. The recorder copies an image before releasing it and evaluates each
source plane with the plane's declared row and pixel strides.

For an even crop with dimensions `W x H`:

```text
Y[y,x] = plane0[y * row_stride0 + x * pixel_stride0]
U[v,u] = plane1[v * row_stride1 + u * pixel_stride1]
V[v,u] = plane2[v * row_stride2 + u * pixel_stride2]

0 <= x < W, 0 <= y < H
0 <= u < W/2, 0 <= v < H/2
```

Profile 0.1 rejects an odd crop origin, odd width, odd height, missing plane,
out-of-bounds stride, duplicate/non-monotonic accepted sensor timestamp, or an
unsupported bit depth. Orientation, crop, lens facing, sensor orientation,
exposure, sensitivity, focal/focus data, intrinsics and distortion are metadata;
the stored plane order remains the sensor buffer's canonical top-left raster.

The pre-substrate frame digest is:

```text
SHA256(
  LE64(sensor_timestamp_ns) ||
  LE32(W) || LE32(H) ||
  Y_dense || U_dense || V_dense
)
```

## 3. Exact codeword packing

Every luma address has one logical three-lane codeword:

```text
UGCODE24-420(x,y) = [
  Y[y,x],
  U[floor(y/2), floor(x/2)],
  V[floor(y/2), floor(x/2)]
]
```

This is a bijection between an even-sized dense YUV420 frame and the constrained
codeword raster. The inverse writes every Y lane and takes U/V only from the
canonical chroma owner `(x even, y even)`. A decoder regenerating the expanded
codeword view must reject disagreement among the four codewords sharing one
chroma owner.

The physical novelty stream does not repeat chroma. At generated address `(x,y)`
it admits these lanes only:

```text
Y                          always
U and V                    only when (x & 1)==0 and (y & 1)==0
```

Thus one 2x2 group has four Y samples plus one U and one V sample: exactly the
six authoritative YUV420 bytes before prediction/novelty removal.

## 4. Seed-executed log-polar address program

The address sequence is not serialized. The player regenerates it using the
Grove UGLUT2 binary16 lanes and the UGTS SplitMix64 lineage:

```text
session_seed = combine_seed(root_seed, fixed_recipe_seed)
a_i = UGTRV1(UGLUT2_profile, session_seed, i), 0 <= i < W*H
```

`UGTRV1` uses exact doubled pixel centers; binary16 radius samples converted to
Q16; binary16 direction samples converted to Q30; exact radial midpoint and
cross-wedge classification; packed rho/theta keys; SplitMix64 lineage; and a
canonical final Cartesian-address tie break. Every address must occur exactly
once. The program stores the root seed, profile/version identifiers and
collision-resistant dependency digests, never a `W*H` permutation.

The fixed POCO profile carries the canonical UGLUT2 bytes in the application and
stores their SHA-256 in a recording. An optional self-contained profile may embed
one shared UGLUT2 record once per file. It may never embed one table per frame.

## 5. Applied GSP4 state and novelty

GSP4's retained execution order is normative here:

```text
finite generated state
  -> radial/angular address support
  -> lane/profile compatibility
  -> finite bounds/timestamp guard
  -> verified exact difference
  -> route and seed-derived lineage
  -> append-only novelty chain
```

For every generated address, the seed and address derive the persistent entity
ID and `lineage_seed`; those values are not stored per sample. The luma/chroma
ownership rule is the compatibility mask. Buffer extents, plane availability,
monotonic sensor time, predictor dependency and modulo arithmetic are finite
guards. A sample may enter the novelty stream only after every gate passes.

For an accepted lane value `v` and a deterministic predictor value `p`:

```text
delta_u8 = (v - p) mod 256
delta_s8 = delta_u8                 when delta_u8 < 128
           delta_u8 - 256           otherwise
v         = (p + delta_s8) mod 256
```

`delta_s8 == 0` is negative memory: the generated state already reproduces the
observation, so no novelty event is emitted for that lane. A nonzero delta is an
irreducible exact observation and must remain in the file. Absence of a lane is
never interpreted as empty space, disappearance, an occlusion, or hidden-scene
knowledge.

The initial frame must be independently replayable. Without a declared external
initial state, its unpredicted information is novelty even if it is visually
simple. Later frames may use exact previous-state and spatial predictors. No
learned feature, depth, mask, pose, body or image generator may replace a delta.

## 6. Bounded program search

The real-time writer and the after-the-fact minimizer may search only bijective,
integer-exact programs. The required baseline candidates are:

1. generated-address spatial MED;
2. previous accepted value at the same persistent address;
3. temporal value plus spatial MED of exact modular differences;
4. raw exact lane value.

Each independently decodable block serializes the byte-smallest exact candidate
under a declared search budget and canonical tie order. Sparse address gaps,
zero-run coding, modulo-256 Rice and static byte-rANS are permitted only when the
inverse and the candidate selector are independently reproducible. RTX search may
try additional seeds, block sizes and exact predictor programs, then write the
smallest complete file measured. It must report `smallest among tested programs`,
never a global or information-theoretic minimum.

## 7. Streaming and crash behavior

The phone writes an append-only `.partial` stream. A committed frame record binds:

- ordinal and exact sensor timestamp;
- capture metadata record or metadata digest;
- predictor/program identifiers and dependency ordinal;
- root seed, UGLUT2 and traversal-program dependencies;
- logical codeword/sample counts;
- pre-substrate dense-plane digest;
- novelty payload digest;
- previous record hash and self hash.

A bounded capture callback only copies into a preallocated slot and releases the
`AImage`. Encoding and storage run outside that callback. Queue pressure has two
legal outcomes: losslessly spool the canonical dense planes, or stop recording
with an explicit failure record. Silent frame dropping, timestamp substitution,
and overwriting an uncommitted slot are invalid.

Finalization appends a terminal record and atomically promotes the `.partial`
file. A completed extension must fail closed if the terminal count/hash or any
frame chain is invalid. Recovery may expose only the longest fully committed
prefix and must label it recovered/incomplete.

## 8. Playback

Playback performs, in order:

1. strict header/profile/dependency validation;
2. UGLUT2 and traversal regeneration;
3. novelty block decode;
4. inverse exact predictor execution;
5. `UGCODE24-420` inverse into dense Y, U and V;
6. pre-substrate digest and timestamp verification;
7. publication on the recorded half-open sensor-time interval;
8. downstream three-texture YUV display conversion on the bound scene node.

The first seven steps are the evidence path. Color matrix, range conversion,
rotation, scaling, material and rasterization in step eight are presentation.

## 9. Editable Grove ownership

Recorder or player ownership belongs to one ordinary editable scene node through
the `KCCH392` sparse sidecar. Required configuration includes:

```text
mode                       RECORDER or PLAYER
camera_id                  queried/selected Camera2 device
width,height,fps           bounded requested profile
pixel_profile              UGCODE24_420_CAMERA_EXACT
root_seed_u64              stored traversal root
recipe_seed_u64            fixed/profile-bound seed
uglut2_profile/hash        exact substrate dependency
storage/source policy      app file or selected descriptor
novelty_policy             EXACT_RESIDUAL_REQUIRED
authority                  CAMERA2_DENSE_YUV420
geometry_status            UNKNOWN by default
autostart                  editable, false by default
```

There is no hidden bootstrap, global fullscreen camera owner, or hard-coded
recording payload.

## 10. Physical acceptance gates

The POCO path is accepted only after a built APK proves all of the following:

- no packaged MP4 and no MediaCodec dependency in the seed-capture flavor;
- Camera2 reports and selects the actual 1280x720 YUV/30 fps configuration;
- accepted image count equals recorded ordinal count with monotonic unique sensor
  timestamps and zero silent drops;
- at least ten seconds of static/color/checkerboard and ten seconds of textured
  motion are recorded;
- on-device replay reproduces every dense Y/U/V byte and timestamp;
- a pulled file independently reproduces the same result in host C++ and Python;
- the file contains no per-pixel permutation, only seed/profile state and exact
  novelty;
- queue high-water, spool bytes, write throughput, encode rate, memory, thermals
  and battery are measured for one minute and ten minutes;
- a kill-during-capture test recovers a valid committed prefix or fails closed;
- unsupported 3D/4D remains `UNKNOWN` and does not affect lossless replay.

