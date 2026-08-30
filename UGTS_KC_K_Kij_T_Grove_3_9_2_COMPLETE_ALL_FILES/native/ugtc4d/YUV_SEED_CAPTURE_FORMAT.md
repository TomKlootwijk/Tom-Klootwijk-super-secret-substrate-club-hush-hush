# UGYUVS1 camera seed-storage slice

This is the portable C++17 implementation slice for the frozen
`UGCODE24_420_CAMERA_EXACT` profile in
`spec/UGTOMS_GSP4_SEED_CAMERA_0_1.md`. The completed extension is `.ugsp4c`;
capture uses `.ugsp4c.partial`. The eight-byte file magic is `UGYUVS1\0`.

It stores exact Camera2-normalized dense YUV420P8 evidence and sensor PTS. It
does not contain MP4, H.26x, AV1, MediaCodec output, RGB conversion, inferred
geometry, or a serialized pixel permutation. A seed alone cannot reconstruct
camera novelty; every non-predicted observation remains in the novelty records.

## Evidence and address program

For even `W,H`, every generated luma address `(x,y)` logically expands to:

```text
[Y[y,x], U[floor(y/2),floor(x/2)], V[floor(y/2),floor(x/2)]]
```

Storage admits Y at every generated address and admits U,V only for the
canonical even/even owner. Thus it stores exactly `W*H*3/2` logical lanes before
prediction and novelty omission. The literal UGLUT2 record occurs once per file.
UGTRV1 is regenerated from it, `rootSeed`, `recipeSeed`, and dimensions. No
`W*H` permutation occurs in the file.

The pre-substrate digest is exactly:

```text
SHA256(LE64(sensorTimestampNs) || LE32(W) || LE32(H) || Y || U || V)
```

Every novelty block also binds a digest of regenerated GSP4 lineage pairs for
its luma addresses. The lineage implementation matches the Python oracle's
UGTS SplitMix64 `combine_seed`/`stable_id`, namespace
`0x7f0b2a27a8c27f83`, low-32-bit `lineage_seed`, and:

```text
routed_hash = gsp4_mix32(lineage_seed XOR frameOrdinal)
```

These per-address values are executed and hash-bound, not serialized per
address.

## Exact prediction and negative memory

The current bounded baseline uses predictor program 4 (`RAW_EXACT_LANE`) on a
checkpoint and program 2 (`PREVIOUS_SAME_ADDRESS`) otherwise. Residuals are
unsigned modulo-256 bytes; addition in the reader is their exact inverse. Zero
means the predictor already reproduces the observation and is negative memory,
so no novelty event is stored.

The default block covers 65,536 luma addresses. Each block independently chooses
the byte-smallest representation below; equal payload sizes keep the lower ID:

| ID | Representation | Payload |
|---:|---|---|
| 0 | `ZERO` | none |
| 1 | `DENSE` | every residual byte |
| 2 | `SPARSE_BITMASK` | occupancy bits, then nonzero residual bytes |
| 3 | `SPARSE_GAPS` | canonical ULEB128 zero-gap from the next expected symbol, then nonzero residual bytes |

The fixed 192-byte independently checked block header is common to all four.
Consequently a static 1280x720 temporal frame has 15 ZERO blocks and only 2,880
novelty bytes, rather than a picture-sized occupancy mask.

The required generated-address spatial MED and temporal-plus-spatial-difference
candidate search are not implemented in this slice. Adding them changes the
selected predictor IDs, not the dense evidence authority or inverse arithmetic.

## Binary records

All integers are little-endian. All currently reserved bytes must be zero.
Every content SHA is computed with its own 32-byte field set to zero.

- 512-byte file header: static profile/dependency state in bytes 0..255 and two
  alternating 128-byte durable commit slots at 256 and 384. The literal UGLUT2
  follows once, then zero padding to a 64-byte boundary.
- 384-byte `UGYFRM1\0` frame header: ordinal/dependency, exact sensor PTS,
  optional frame number, payload counts, Y/U/V hashes, full logical residual
  hash, opaque canonical metadata hash, previous-record hash, executable-state
  hash, content hash, pre-substrate digest, and novelty-event count. Novelty
  blocks precede metadata bytes in its payload.
- 192-byte `UGNBLK1\0` block header: luma range, logical/auxiliary/value counts,
  logical/value/content hashes, predictor ID, representation ID, and GSP4
  lineage digest.
- 192-byte `UGYEND1\0` terminal record: final frame count, prefix end, exact last
  PTS, last-frame hash, static/recipe dependencies, and self hash.

Frame and terminal records are append-only. After each durable frame write, the
writer durably advances one alternating commit slot. A partial reader chooses
the highest structurally valid generation and ignores/lists any uncommitted
tail. `recoveredIncomplete=true` is explicit. Finalization appends and flushes
`UGYEND1`, advances a FINAL commit, closes, and performs a same-filesystem rename.
A `.ugsp4c` file fails closed if FINAL is absent or does not cover the exact file
length; strict replay rechecks every chain, dependency, lineage, residual,
metadata, dense-plane, and pre-substrate hash.

## Portable API

The source API is `yuv_seed_capture.hpp/.cpp`:

```text
YuvSeedCaptureWriter::createPartial(path, profile)
writer.append(Yuv420p8FrameView)
writer.finalize(finalPath)
YuvSeedCaptureReader(path).replay(callback)
```

`Plane8View` accepts source row/pixel strides. `canonicalMetadata` is a
platform-authored, versioned byte record stored verbatim and SHA-bound. The
Android adapter owns the schema of those bytes.

