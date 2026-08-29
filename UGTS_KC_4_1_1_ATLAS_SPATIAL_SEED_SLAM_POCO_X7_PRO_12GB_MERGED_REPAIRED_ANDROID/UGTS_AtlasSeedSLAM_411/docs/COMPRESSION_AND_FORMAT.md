# KSEED 4.1 compression and integrity

KSEED stores a session seed plus measured evidence deltas. It is not seed-only reconstruction.

- Header: 128 bytes; CRC32 covers bytes 0-123.
- Chunk header: 64 bytes; first 32 bytes carry framing/length/CRC/schema fields and the final 32 bytes carry the SHA-256 chain value.
- Chain: `H_i = SHA256(H_(i-1) || header_first_32 || stored_payload)`, starting from `SHA256("KSEED41-CHAIN")`.
- Records use delta frame/timestamp values, int16 inertial/orientation values, base-128 varints and sorted Morton voxel-key deltas.
- Each payload is zlib-compressed at level 1 only when `compressed_size + 16 < raw_size`.
- The final 60-byte summary includes counts, raw input bytes, exact total stored bytes and chunk count.

The checked-in release fixture captures 1,843,200 synthetic luma bytes and stores 11,425 KSEED bytes, a nominal 161.33x raw-input-to-evidence ratio. This is not equal-information image compression, not a phone benchmark and not a guarantee for real scenes.
