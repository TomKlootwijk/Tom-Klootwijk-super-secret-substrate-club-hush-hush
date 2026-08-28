# Compression and `.ugtsscan` format

## Geometry codec

`map.ugtsbin` uses:

```text
voxel centres
→ integer coordinates at the session voxel size
→ lexicographic coordinate order
→ coordinate deltas
→ signed zigzag transform
→ unsigned variable-length integers
→ intensity + quantized confidence + observation count
→ DEFLATE level 3
```

The header is:

```text
bytes 0..3   ASCII "UG3D"
byte 4       codec version 1
bytes 5..12  big-endian IEEE-754 voxel size
bytes 13..   zlib/DEFLATE payload
```

The packed record is finite and lossy with respect to the original images and sub-voxel point positions. Compression is never treated as equal-information magic: its meaning depends on the declared voxel size, confidence semantics, omitted images, and reconstruction purpose.

## Container entries

```text
map.ugtsbin          quantized geometry
trajectory.csv       accepted keyframe poses
ledger.ndjson        ordered events
capture_policy.json  scale/calibration/privacy state
README.txt           human boundary note
manifest.json        SHA-256 for all preceding entries
```

The ZIP writer uses ordinary DEFLATE and fixed timestamps for deterministic packaging. Keyframe images are omitted by default, which is the largest storage and privacy reduction.

## Desktop inspection

```bash
python tools/ugts_scan_tool.py scan.ugtsscan
python tools/ugts_scan_tool.py scan.ugtsscan --to-ply scan.ply
```

The tool checks each manifest hash before reporting success. PLY is a downstream interchange view and does not replace the voxel/ledger evidence container.

## Integrity boundary

SHA-256 detects accidental or unauthorized byte changes relative to the manifest. It is not a signature, owner identity, notarization, or legal chain of custody. Add an external digital-signature and custody procedure when those properties are required.
