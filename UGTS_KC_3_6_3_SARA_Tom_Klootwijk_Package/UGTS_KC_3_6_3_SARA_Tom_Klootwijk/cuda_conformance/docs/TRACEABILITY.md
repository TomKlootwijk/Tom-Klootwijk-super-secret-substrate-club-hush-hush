# Literal SARA 3.6.3 traceability

| SARA 3.6.3 operator | Literal Python source | CUDA/portable implementation | Fixed verification |
|---|---|---|---|
| `sara363.seed.pbkdf2` | `mnemonic_to_seed` | `pbkdf2_hmac_sha512_2048` | Published BIP39 vector with passphrase `TREZOR` |
| `sara363.bip32.master` | `master_node_from_seed` | `bip32_master` | BIP32 vector-1 node `m` |
| `sara363.bip32.edge.hardened` | `ckd_private`, index at least `0x80000000` | `bip32_ckd_private` hardened branch | `m/0'` and `.../2'` |
| `sara363.bip32.edge.normal` | `ckd_private`, index below `0x80000000` | `bip32_ckd_private` normal branch | Three normal edges in vector 1 |
| secp256k1 public projection | `compressed_public_key` | `secp256k1_compressed` | Compressed public key at all six nodes |
| forbidden search | audit boundary and security policy | absent by construction | CLI surface inspection and fixed constants |

The CUDA SHA-512, HMAC, PBKDF2, 256-bit modular arithmetic, Jacobian curve operations, master derivation, and CKD routines are compiled for both host and device. Correctness is not established from host/device agreement alone: both outputs are separately compared to values decoded from the official BIP32 xprv/xpub vector and the published BIP39 seed. The additional Python script then checks those same fixtures through the unchanged literal SARA source.

The earlier CUDA work contributed the proven Windows build approach, native `sm_120` targeting, CUDA error handling, CUDA-event timing, and device metadata reporting. No orbital/SGP4 computation is reused or claimed here.
