# KSEED 4.1 reconstructed format contract

This document records the 4.1 report-defined format implemented by 4.1.1. It does not claim byte identity with an unavailable 4.1.0 source archive.

## Session header - 128 bytes, little endian

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 8 | `KSEED41\0` |
| 8 | 2 | major = 4 |
| 10 | 2 | minor = 1 |
| 12 | 2 | header bytes = 128 |
| 14 | 2 | storage mode = 1, evidence deltas |
| 16 | 4 | flags |
| 20 | 16 | session seed |
| 36 | 8 | monotonic start time ns |
| 44 | 4 | analysis width |
| 48 | 4 | analysis height |
| 52 | 4 | requested capture fps |
| 56 | 4 | feature budget |
| 60 | 32 | capture-profile SHA-256 |
| 92 | 32 | calibration-descriptor SHA-256 |
| 124 | 4 | CRC32 of bytes 0-123 |

## Chunk header - 64 bytes

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 2 | chunk type |
| 2 | 2 | flags: bit 0 compressed, bit 15 synthetic fixture |
| 4 | 4 | sequence |
| 8 | 4 | record count |
| 12 | 4 | decoded length |
| 16 | 4 | stored length |
| 20 | 4 | decoded CRC32 |
| 24 | 4 | stored CRC32 |
| 28 | 4 | schema ID |
| 32 | 32 | `SHA256(previous_hash || bytes_0_31 || stored_payload)` |

Initial predecessor: `SHA256("KSEED41-CHAIN")`.

## Chunk types

1. Frame evidence
2. Accepted keyframes
3. Ordered ledger decisions
4. Morton-sorted voxels
5. Calibration/profile record
255. Final summary

## Final summary - 60 bytes

Six uint64 values: frames, keyframes, events, voxels, raw input bytes and exact stored bytes. Three uint32 values: rejected proposals, state flags and chunk count.

Replay/inspection stops at the first magic, framing, sequence, length, CRC, zlib, SHA-chain or summary-size failure.
