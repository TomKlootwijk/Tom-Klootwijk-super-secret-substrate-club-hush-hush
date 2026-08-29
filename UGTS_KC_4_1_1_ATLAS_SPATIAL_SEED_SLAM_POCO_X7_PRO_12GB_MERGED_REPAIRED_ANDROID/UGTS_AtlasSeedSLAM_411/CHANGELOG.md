# Changelog

## 4.1.1 - Atlas Spatial Seed SLAM Fusion

- Rebased the documented Spatial Seed Native contract onto the repaired 3.9.4.1 Android source tree.
- Added stable 128-bit session seeds and deterministic sample schedules.
- Added the eight-stage proposal verifier and proposal-before-commit keyframe path.
- Added canonical proposal hashes plus pre/post state-chain hashes to ledger events.
- Added frame evidence records and raw-input-byte accounting without raw-frame persistence.
- Added KSEED 4.1 session/chunk framing, CRC32, zlib-if-smaller policy, SHA-256 chain and exact stored-size summary.
- Added true 21-bit signed Morton voxel keys for KSEED voxel deltas.
- Added an independent Python KSEED inspector and optional PLY conversion.
- Added a narrow arm64-v8a native seed/CRC module with portable C++ host tests and Java fallback.
- Added a deterministic synthetic demo marked by UI text and tag bit 31.
- Added optional exact Bayer 8x8 four-level projection.
- Preserved Camera2, IMU, SLAM, known-distance scaling and legacy `.ugtsscan` tooling.
- Updated Gradle project/module structure, source contracts, validation, docs, manifests and checksums.
- No APK or physical-phone benchmark is claimed by this source packaging run.

## 3.9.4.1

Repaired the earlier Android handoff by adding a verified Gradle bootstrap, removing generated caches and long paths, and validating clean extraction and host source behavior.
