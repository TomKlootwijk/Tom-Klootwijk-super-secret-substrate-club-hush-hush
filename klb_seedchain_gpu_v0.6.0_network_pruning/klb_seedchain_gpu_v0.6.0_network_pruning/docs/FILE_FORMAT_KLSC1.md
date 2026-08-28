# KLSC1 binary format (`KLSC3701`)

## Scope

KLSC1 stores a fixed-correspondence point sequence as:

- one embedded KLB37 base bitstream;
- one fixed-size predictor/grammar node per frame;
- sorted sparse novelty snapshots and deltas;
- an ordered parent/self integrity chain.

All multi-byte values are little-endian. The current implementation rejects big-endian hosts.

## Canonical file order

```text
offset 0                                      256-byte SeedChainHeaderDisk
header.nodes_offset                           node_count * 96 bytes
header.novelty_offset                         novelty_count * 16 bytes
header.base_words_offset                      base_header.word_count * 4 bytes
EOF
```

No hidden alignment or padding is inserted between regions. The canonical file size is:

```text
256 + node_count*96 + novelty_count*16 + base_word_count*4
```

## 256-byte header

| Offset | Bytes | Field | Meaning |
|---:|---:|---|---|
| 0 | 8 | `magic` | ASCII `KLSC3701` |
| 8 | 4 | `version` | `1` |
| 12 | 4 | `header_bytes` | `256` |
| 16 | 8 | `node_count` | Frames/nodes |
| 24 | 8 | `novelty_count` | Total sparse records |
| 32 | 8 | `nodes_offset` | Canonically `256` |
| 40 | 8 | `novelty_offset` | End of node table |
| 48 | 8 | `base_words_offset` | End of novelty table |
| 56 | 4 | `node_bytes` | `96` |
| 60 | 4 | `novelty_bytes` | `16` |
| 64 | 4 | `checkpoint_stride` | `1..64` |
| 68 | 4 | `flags` | Container feature bits |
| 72 | 4 | `novelty_quantum` | World units per signed residual step |
| 76 | 4 | `frames_per_second` | Time metadata |
| 80 | 4 | `default_guard_epsilon` | Suggested query guard |
| 84 | 4 | reserved float | Must not be interpreted in version 1 |
| 88 | 8 | `chain_hash` | Final node `self_hash` |
| 96 | 8 | `source_sequence_bytes` | Total fitted input bytes, or zero |
| 104 | 128 | `base_header` | Embedded KLB37 header |
| 232 | 24 | reserved | Zero in generated files |

### Header flags

| Bit | Name | Meaning |
|---:|---|---|
| 0 | embedded base | KLB37 word stream is in this file |
| 1 | hash linked | Every node commits to its parent hash |
| 2 | sparse novelty | Novelty is stored as sparse point-index records |
| 3 | node predictor | Frame state contains a deterministic predictor/grammar node |
| 4 | checkpoint snapshots | Checkpoints contain current residual snapshots |

## 96-byte node

| Offset | Bytes | Field | Meaning |
|---:|---:|---|---|
| 0 | 4 | `parent_index` | Previous frame or `0xffffffff` for root |
| 4 | 4 | `frame_index` | Sequential frame number |
| 8 | 4 | `chain_seed` | Deterministic grammar/jitter seed |
| 12 | 4 | `flags` | Node flags |
| 16 | 4 | `time_seconds` | Frame time |
| 20 | 4 | `angle` | Absolute Y-axis rotation |
| 24 | 4 | `angular_velocity` | Diagnostic/predictor derivative |
| 28 | 4 | `angular_acceleration` | Diagnostic/predictor second derivative |
| 32 | 4 | `log2_scale` | Absolute uniform scale in log2 space |
| 36 | 4 | `translate_x` | Absolute translation |
| 40 | 4 | `translate_y` | Absolute translation |
| 44 | 4 | `translate_z` | Absolute translation |
| 48 | 4 | `cone_phase` | Procedural cone/grammar phase |
| 52 | 4 | `branch_amplitude` | Procedural deformation amplitude |
| 56 | 4 | `novelty_begin` | First record in global novelty table |
| 60 | 4 | `novelty_count` | Records belonging to this node |
| 64 | 4 | `checkpoint_index` | Most recent checkpoint frame |
| 68 | 4 | `depth_from_checkpoint` | Parent steps to checkpoint |
| 72 | 8 | `parent_hash` | Base payload hash for root; prior node hash otherwise |
| 80 | 8 | `self_hash` | FNV-1a over node with zeroed self hash plus its novelty records |
| 88 | 8 | reserved | Zero in generated files |

### Node flags

| Bit | Meaning |
|---:|---|
| 0 | Checkpoint node; novelty records are a snapshot |
| 1 | Node has one or more novelty records |
| 2 | Predictor was fitted from an external frame sequence; procedural deformation is disabled |

## 16-byte novelty record

| Offset | Bytes | Field | Meaning |
|---:|---:|---|---|
| 0 | 4 | `point_index` | Stable logical point index |
| 4 | 2 | `dx` | Signed x residual units |
| 6 | 2 | `dy` | Signed y residual units |
| 8 | 2 | `dz` | Signed z residual units |
| 10 | 2 | `flags` | Snapshot or delta |
| 12 | 4 | `event_seed` | Deterministic event metadata/check value |

World residual is:

```text
(dx, dy, dz) * header.novelty_quantum
```

Within each node’s novelty range, records are strictly sorted by `point_index` and no point may occur twice.

### Novelty flags

| Bit | Meaning |
|---:|---|
| 0 | Checkpoint snapshot value |
| 1 | Non-checkpoint delta value |

## Embedded KLB37 base

The header embeds a complete 128-byte `FileHeaderDisk`, but only the KLB payload words are stored after the novelty table. The base record layout is:

```text
rho      11 bits
azimuth  12 bits
elevation 10 bits
symbol    3 bits
parity    1 bit
----------------
          37 bits
```

Records are concatenated without byte or word alignment. The base header declares record count, padding, word count, center, radius scale, log parameter, flags, error, and payload hash.

For fitted sequences, base logical point order is preserved. Generated/static KLB sources may be Morton sorted when correspondence is not required.

## Integrity chain

Root:

```text
node[0].parent_hash = base_header.payload_hash
```

Subsequent nodes:

```text
node[i].parent_hash = node[i-1].self_hash
```

Self hash:

```text
FNV1a64(node bytes with self_hash = 0 || node novelty bytes)
```

Header terminal hash:

```text
header.chain_hash = node[last].self_hash
```

FNV-1a is not collision-resistant and is not a signature. Use a cryptographic manifest or signature outside KLSC1 when adversarial tampering or legal provenance is in scope.

## Random-access reconstruction pseudocode

```text
function reconstruct(frame, point):
    code = read_base_37bit(point)
    p, base_meta = decode_log_spherical(code)

    node = nodes[frame]
    symbol, route = fixed_parity_grammar(code, node.seed, point)
    orientation, topology_phase = klein_route(code, node, symbol, route)

    if node is generated:
        p = procedural_cone_deform(p, node, symbol, route, orientation, topology_phase)

    p = similarity_y(p, node.angle, exp2(node.log2_scale), node.translation)

    residual = 0
    current = frame
    repeat at most checkpoint_stride times:
        residual += binary_search_novelty(nodes[current], point)
        if current is checkpoint: break
        current = nodes[current].parent_index

    return p + residual
```

## Validation rules

A conforming version-1 reader should reject a file when:

- magic/version/record sizes differ;
- offsets do not equal the canonical packed layout;
- counts exceed implementation limits;
- base record layout is unsupported;
- base payload hash fails;
- frame indices or parent links are not sequential;
- checkpoint metadata is inconsistent;
- novelty ranges are out of bounds or not strictly sorted;
- snapshot/delta flags disagree with node type;
- any parent/self hash fails;
- terminal hash differs from the last node hash;
- actual file size differs from canonical size.

## Versioning rule

Readers must not infer meaning from reserved bytes. Any incompatible layout or semantic change requires a new version or magic value.
