# `UGTS-CPP-PERSISTENT-BOARD-SEGMENT-v1`

This is the normative schema for the experimental native persistent-state
store **stage 1** codec. It stores immutable packed-board records in one
deterministic in-memory segment. It does not store history nodes, persistent
states, transitions, checkpoints, proof values, paging metadata, or a solved
claim. There is no publication or crash-recovery protocol in this stage. The
19×19 root result remains `UNKNOWN`.

All multi-byte integers are unsigned, fixed-width, and little-endian. No C++
object or struct layout is serialized. All byte counts include exactly the
fields stated below.

## Segment envelope

The header consists of these fields in order:

| Field | Encoding | Required value or constraint |
| --- | --- | --- |
| magic | ASCII plus NUL | `UGTS-CPP-PERSISTENT-BOARD-SEGMENT-v1\0` |
| endian | `u8` | `1` (little-endian) |
| segment kind | `u8` | `1` (board records only) |
| flags | `u16` | zero |
| reserved | `u32` | zero |
| header bytes | `u64` | `109`, the exact canonical header width |
| record count | `u64` | positive and at most the configured count limit |
| records offset | `u64` | exactly `header bytes` |
| records bytes | `u64` | exactly `record count * 152` |
| index offset | `u64` | exactly `records offset + records bytes` |
| index bytes | `u64` | exactly `record count * 56` |
| footer offset | `u64` | exactly `index offset + index bytes` |
| segment bytes | `u64` | exactly `footer offset + footer width` and the input length |

Every declared sum and product must fit in `u64`, `size_t`, the actual input,
and the configured segment limit before count-derived allocation.

## Board record

Each record is exactly 152 bytes:

| Field | Encoding | Required value or constraint |
| --- | --- | --- |
| record bytes | `u32` | `152`, including this field |
| record version | `u8` | `1` |
| record kind | `u8` | `1` (packed board) |
| reserved | `u16` | zero |
| record ID | `u64` | positive; IDs are strictly increasing |
| board size | `u8` | 1 through 19 |
| reserved | `u8`, `u16`, `u32` | all zero |
| black bitplane | six `u64` | packed point bits |
| white bitplane | six `u64` | packed point bits |
| board locator | 32 raw bytes | locator described below |

Black and white bitplanes may not overlap. Words beyond
`ceil(size*size/64)` and high bits beyond `size*size` must be zero. These packed
fields, including the board size, are the exact board identity.

This codec is a framing format, not an interning layer. Distinct strictly
ordered IDs may intentionally carry identical exact board payloads, and such
records are preserved independently on decode. ID inequality never proves
board inequality. A future interning or import layer consuming this format must
exact-compare the packed size and both bitplanes, then either canonicalize exact
duplicates to one arena identity or reject them. It must not infer identity or
inequality from IDs or locators alone.

## Board locator

The default locator is SHA-256 over this canonical byte string:

1. the ASCII bytes `UGTS-CPP-PACKED-BOARD-LOCATOR-v1`, with no NUL terminator;
2. board size as `u8`;
3. six black words as `u64` little-endian;
4. six white words as `u64` little-endian.

This is exactly the canonical locator material used by
`PersistentStateArena::InternBoard`; the codec does not define a second board
locator domain.

A caller may inject a deterministic locator function for collision testing or
a future index policy. The decoder recomputes the locator with the same policy.
The locator only selects possible records: digest equality is never board
equality, and unequal exact packed fields remain unequal even under a complete
locator collision.

## Ordered index

There is one 56-byte index entry per board record, in the same strict ID order:

| Field | Encoding | Required value or constraint |
| --- | --- | --- |
| record ID | `u64` | exactly the corresponding record ID |
| record offset | `u64` | exact canonical byte offset of that record |
| record bytes | `u32` | `152` |
| reserved | `u32` | zero |
| board locator | 32 raw bytes | exactly the corresponding verified locator |

The redundancy is intentional: a decoder validates the index against the
records and does not trust offsets or digests as identity.

## Footer

The footer consists of these fields in order:

| Field | Encoding | Required value or constraint |
| --- | --- | --- |
| magic | ASCII plus NUL | `UGTS-CPP-PERSISTENT-BOARD-FOOTER-v1\0` |
| endian | `u8` | `1` |
| flags | `u8` | zero |
| reserved | `u16` | zero |
| footer bytes | `u64` | `96`, the exact canonical footer width |
| body bytes | `u64` | exactly the footer offset |
| segment bytes | `u64` | exactly the envelope segment length |
| body SHA-256 | 32 raw bytes | SHA-256 of every byte preceding the footer |

Truncation, trailing bytes, nonzero reserved fields, noncanonical sizes or
offsets, duplicate or out-of-order IDs, invalid packed boards, locator
mismatches, index mismatches, and footer digest mismatches are rejected.

## Canonical golden vector

A segment containing only record ID `1` with an empty 1×1 board is exactly 413
bytes. Its board locator is
`c85abc8f9a22bd143d8d8648540b42dfc9d6a9b02595b6d35f51e56cf2546da6`, its
body SHA-256 is
`13f77f4dead3f9703f8f8da467f6bf8cccf0407d62cdabfb7afb030bfc45c7ca`, and
its complete-segment SHA-256 is
`4a4c6f3d4c469adcf78265d68f17b2717531054bf3c1120dfd60b40d125fe1b3`.

A second 413-byte segment contains only record ID `7`, size 9, black words
`[1, 64, 0, 0, 0, 0]`, and white words `[2, 2, 0, 0, 0, 0]`. Its locator is
`802ef7acaaeab03894164efc2fb349489f67945be7451a2b47e0fbe0d6f67aaf`, its
body SHA-256 is
`d266cba44a8d6e61b9a29f5d68dabd798556b3a7967066ad6100143861920a31`, and
its complete-segment SHA-256 is
`774737c843d0a372a3f7e94dfd3d6ceac02e1a7d6994aee5179ea9eb6842e929`.

## Bounded stage and exactness limits

The public codec has explicit maximum segment bytes, record bytes, and record
count. The v1 defaults are 64 MiB, 4,096 bytes, and 250,000 board records,
respectively. The same limits apply during encode and decode. A limit failure
rejects the artifact; it cannot become a proof result. The implementation still
materializes the complete encoded segment and decoded record vector in RAM.
There is no file I/O, mmap, paging, cache eviction, atomic publication,
restart, history/state reconstruction, or integration with the proof-number
DAG in this stage.
