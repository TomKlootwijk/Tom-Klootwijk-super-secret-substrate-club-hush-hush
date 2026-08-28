# KSEED 4.1 Binary Format

KSEED is the native compact session container for UGTS-KC 4.1. All multibyte numeric fields are little-endian. Floating-point fields use IEEE-754 binary32. A conforming reader must bounds-check every length and stop on the first integrity or framing error.

## 1. File header - 128 bytes

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 8 | ASCII `KSEED41` followed by zero |
| 8 | 2 | major version = 4 |
| 10 | 2 | minor version = 1 |
| 12 | 2 | header length = 128 |
| 14 | 2 | storage mode |
| 16 | 8 | session seed |
| 24 | 8 | monotonic session start time, ns |
| 32 | 2 | analysis width |
| 34 | 2 | analysis height |
| 36 | 2 | requested capture fps times 100 |
| 38 | 2 | feature budget |
| 40 | 32 | capture profile SHA-256 |
| 72 | 32 | calibration descriptor SHA-256 |
| 104 | 20 | reserved, zero in 4.1 |
| 124 | 4 | CRC32 of bytes 0..123 |

Storage mode 0 is seed plus evidence deltas. Mode 1 additionally permits thumbnail bytes inside frame records.

## 2. Chunk header - 64 bytes

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 4 | ASCII `KCH1` |
| 4 | 2 | chunk type |
| 6 | 2 | flags; bit 0 = zlib compressed |
| 8 | 4 | monotonically increasing chunk sequence |
| 12 | 4 | record count |
| 16 | 4 | decoded payload bytes |
| 20 | 4 | stored payload bytes |
| 24 | 4 | CRC32 of decoded payload |
| 28 | 4 | CRC32 of stored payload |
| 32 | 32 | SHA-256 chain value |

Chunk types: 1 frames, 2 events, 3 checkpoint, 4 final summary.

The first predecessor is:

```text
SHA256("KSEED41-CHAIN")
```

For each chunk:

```text
chain_i = SHA256(chain_(i-1) || chunk_header[0:32] || stored_payload)
```

The resulting 32 bytes are stored at header offset 32.

## 3. Unsigned varint

The format uses base-128 little-endian varints. The low seven bits carry data and bit 7 indicates continuation. Readers must reject an encoding that exceeds 10 bytes or shifts beyond 63 bits.

## 4. Frame record

A frames chunk contains `record_count` records. Each record is framed by a varint byte length, followed by:

| Order | Field |
|---:|---|
| 1 | timestamp delta from previous stored frame, microseconds, varuint |
| 2 | frame index delta, varuint |
| 3 | quaternion x,y,z,w as four signed int16 values scaled by 32767 |
| 4 | acceleration x,y,z as signed int16 values scaled by 2048 |
| 5 | angular velocity x,y,z as signed int16 values scaled by 4096 |
| 6 | mean luma, uint8 |
| 7 | luma deviation, uint8 |
| 8 | 64-bit luma signature |
| 9 | feature count, varuint |
| 10 | feature records |
| 11 | thumbnail byte length, varuint |
| 12 | optional thumbnail bytes |

Features are sorted by 16-bit 2D Morton address. Each feature stores:

```text
morton address delta : varuint
intensity            : uint8
gradient             : uint8
score                 : varuint, bounded to 65535 on decode
```

The ray key is deterministically reconstructed from x, y, frame index and header dimensions; it is not redundantly stored.

## 5. Event record

An events chunk also uses varint record framing. Each event record contains:

```text
sequence              : uint32
proposal byte length   : varuint, exactly 79 in 4.1
canonical proposal     : 79 bytes
pre-state hash         : 32 bytes
post-state hash        : 32 bytes
```

Canonical proposal fields, in order:

```text
proposal_id            uint64
kind                   uint8
timestamp_ns           uint64
stable_id              uint64
spatial_key            uint64
confidence             float32
numeric_error          float32
uncertainty            float32
relation_value         float32
metric_a               float32
metric_b               float32
guard                  uint8
flags                  uint8
  bit 0 support_ok
  bit 1 compatibility_ok
  bit 2 metric_required
  bit 3 metric_ready
tag_mask                uint32
payload[4]              int32 x 4
```

## 6. Summary payload - 60 bytes

```text
session_seed            uint64
start_time_ns           uint64
end_time_ns             uint64
frames_seen             uint32
keyframes_stored        uint32
proposals_seen          uint32
events_committed        uint32
rejected_proposals      uint32
raw_input_bytes         uint64
stored_bytes            uint64
```

A complete file has one final summary chunk. `stored_bytes` must equal the complete file size.

## 7. Compression rule

The writer attempts zlib `Z_BEST_SPEED` only for payloads of at least 64 bytes. Compression is selected only when compressed bytes plus a 16-byte margin are smaller than the raw payload. This avoids expansion and keeps decoding standard-library based.

## 8. Evidence boundary

KSEED seeds reproduce deterministic choices and identities. They do not reproduce unstored real-world imagery. A compliant implementation must not claim that the session seed alone reconstructs the original scene.
