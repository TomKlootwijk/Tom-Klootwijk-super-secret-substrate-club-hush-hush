# Changelog

## 3.9.4.1

- Repaired build handoff and archive portability.
- Added a source-auditable, checksum-verifying Gradle 8.13 bootstrap.
- Replaced CameraX/AndroidX capture with platform Camera2.
- Replaced FileProvider sharing with Android document-provider export.
- Removed generated caches/build trees and nested upstream packages.
- Added factory-intrinsic mapping with explicit estimate/fallback labels.
- Bounded historical keyframe image/descriptor retention.
- Bounded and decimated overlay trajectory history.
- Expanded deterministic host tests and local bootstrap integration test.
- Added archive/path/manifest/source-policy validation and honest build boundary.

## 3.9.4

Initial Atlas Pocket SLAM Android handoff; superseded because the distributed ZIP lacked a working wrapper and contained portability/build-handoff defects.
