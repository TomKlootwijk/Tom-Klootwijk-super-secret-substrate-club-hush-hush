# KC3D391 Native Scene Pack — Format 1

All fields are little-endian. The file begins with `KC3D391\0`, endian marker `0x01020304`,
format version `1`, then mesh/material/node/quality/target counts.

The fixed header contains background, camera, light and world settings, followed by the 64-byte
ASCII SHA-256 project hash and length-prefixed UTF-8 project strings. Variable sections contain:

1. ordered quality tiers;
2. Android target profiles and capability hints;
3. meshes as interleaved float32 position/normal vertices plus uint32 indices;
4. materials;
5. nodes with transform, velocity, collider, gameplay tag mask and references.

Strings use a uint16 byte length. The Python inspector and the host C++ parser reject truncation,
invalid references, out-of-range indices, unsupported format versions and trailing bytes.
