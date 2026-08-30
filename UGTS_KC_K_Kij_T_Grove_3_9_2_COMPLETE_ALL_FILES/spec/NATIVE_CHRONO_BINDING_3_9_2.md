# KCCH392 native chrono node-binding pack — format 1

`KCCH392` is an optional sparse sidecar for `KC3D392`. It does not alter the
established scene-node ABI. Each record is keyed by the canonical node index
of an ordinary editable `Node3DRecord`; there is no bootstrap, global recorder,
or hidden full-screen owner.

The sidecar is a runtime binding, not a camera payload. The 64-bit root seed
regenerates the declared GSP4 traversal/program state. Arbitrary observed camera
samples remain exact novelty evidence in a recorded or referenced `UGYUVS1`
seed stream. A seed never authorizes generation of missing camera values.

## Header

All fields are little-endian. The 64-byte header is:

```text
8s  magic                 "KCCH392\0"
u32 endian                0x01020304
u16 version               1
u16 header_bytes          64
u32 record_count          1..64
u32 record_bytes          176
u32 string_table_bytes
u32 flags                 0
u8  content_sha256[32]
```

`content_sha256` covers the complete file with header bytes 32 through 63
replaced by zero. An unused project omits the optional asset rather than
writing an empty pack.

## Record

The fixed 176-byte record layout is
`<I8B2I4H2Q4d32sQ32sIHHIHHIHHI>`:

```text
u32 node_index
u8  mode                  RECORDER=1, PLAYER=2
u8  pixel_profile         UGCODE24_420_CAMERA_EXACT=1
u8  storage_policy        APP_PRIVATE_GSP4_SEED=1, PACKAGED_GSP4_SEED=2
u8  authority             CAMERA2_DENSE_YUV420=1
u8  novelty_policy        EXACT_RESIDUAL_REQUIRED=1
u8  geometry_status       UNKNOWN=1
u8  autostart             strict boolean 0 or 1; authored on the owner node
u8  reserved              0
u32 width
u32 height
u16 fps_min
u16 fps_max               equal to fps_min in format 1
u16 queue_slots           3..16
u16 uglut2_resolution     power of two, 16..4096
u64 root_seed
u64 recipe_seed           fixed profile constant 1
f64 uglut2_r0
f64 uglut2_rho_min
f64 uglut2_rho_max
f64 uglut2_core_radius
u8  uglut2_sha256[32]
u64 source_asset_bytes    zero unless PLAYER uses packaged storage
u8  source_asset_sha256[32]  zero unless PLAYER uses packaged storage
string_ref camera_id
string_ref stream_name    recorder output or app-private player input
string_ref packaged_asset_path
u32 reserved_tail         0
```

Each `string_ref` is `(u32 offset, u16 byte_length, u16 reserved_zero)` into
the trailing UTF-8 table. Empty strings use `(0,0,0)`. The second reference is
the recorder output basename or app-private player input basename, according
to mode. The table deduplicates equal strings in first-use order. Re-encoding
the decoded records must reproduce the complete file byte for byte.

Records are strictly increasing by `node_index`. Format 1 permits at most one
`RECORDER`, because Camera2 ownership is exclusive. A recorder requires a
portable Camera2 ID and an app-private final `.ugsp4c` output basename (capture
uses `.ugsp4c.partial`) and cannot name a packaged source. A player requires a
hash- and size-bound packaged `UGYUVS1` GSP4 seed stream and cannot own Camera2
or an output name.
An app-private player instead uses storage code 1 and must name the exact output
of the pack's unique recorder. This permits two ordinary nodes—one writer and
one player—to share the just-recorded `.ugsp4c` without a packaged fixture.

## Literal UGLUT2 dependency

For each distinct binding profile, Android export generates the canonical
literal UGLUT2 byte preimage once at
`chrono/uglut2/<lowercase-sha256>.uglut2`. The binding record carries the same
digest and exact binary64 profile. The native writer derives this canonical
path from the digest and verifies the bytes before use. The 16-sample phone
profile is exactly 144 bytes. No picture-sized table and no per-frame UGLUT2 is
permitted.

## Editable metadata

The ordinary node metadata key is `chrono_substrate_binding` with schema
`ugts-kc-chrono-substrate-binding-3.9.2`. The Python project validator rejects
unknown/missing fields, dynamic or colliding owner nodes, nonzero velocities,
non-boolean autostart, recipe-seed drift, UGLUT2 preimage/hash disagreement, non-exact
novelty policy, or premature geometry promotion.

Android export validates all bindings before mutating an output directory,
writes `app/src/main/assets/chrono_bindings.kcch`, copies only explicitly
declared GSP4 player assets, verifies each copied byte count, magic and SHA-256,
and writes the pack/source receipts to `build-report.json`. A recorder binding
packages no MP4, legacy playback asset, or other source evidence.
