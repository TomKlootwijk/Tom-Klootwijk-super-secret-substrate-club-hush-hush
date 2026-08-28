# SARA 3.6.3 fixed-vector CUDA conformance benchmark

This is a correctness-first CUDA translation of the literal SARA 3.6.3 seed and HD-node operators. It has one deliberately narrow job: evaluate immutable public test vectors, prove byte-for-byte agreement, and measure the GPU implementation on the local RTX 5070 Ti Laptop GPU.

It is not a wallet-recovery or cracking tool. The executable accepts batch size, run count, GPU device, and metrics-output options only. It has no input for a mnemonic, passphrase, address, target, wordlist, candidate source, derivation path, or search condition.

## What is covered

- BIP39 seed derivation: PBKDF2-HMAC-SHA512, 2,048 rounds, 64-byte output.
- BIP32 master-node generation with HMAC-SHA512 key `Bitcoin seed`.
- BIP32 private CKD for hardened and normal edges.
- secp256k1 scalar multiplication and compressed public-key projection, required for normal CKD.
- The complete official BIP32 vector-1 path: `m/0'/1/2'/2/1000000000`.
- CPU expected-output checks, GPU expected-output checks, batch-wide checks, repeatability, CUDA-event timing, and JSON metrics.
- An independent cross-check through the unmodified `src/ugts36/sara363.py` implementation.

Published fixtures:

- [BIP39 specification and vectors](https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki)
- [Trezor BIP39 vectors](https://github.com/trezor/python-mnemonic/blob/master/vectors.json)
- [BIP32 test vector 1](https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki#test-vectors)

## Build and run on this laptop

From PowerShell:

```powershell
& .\scripts\build_windows.ps1
```

The script pins the same known-good Windows path used by the earlier CUDA work: Visual Studio 2022, CUDA 12.8, and native plus virtual `sm_120` code. It uses a short external build directory because MSBuild file tracking fails when its generated paths exceed Windows path limits.

The executable's only options are:

```text
--bip39-batch N --bip32-batch N --runs N --device N --json PATH --no-json --quick
```

## Exact scope limits

- The fixed BIP39 fixture is ASCII and already NFKD-stable. The GPU kernel consumes those frozen normalized bytes; it does not implement general Unicode NFKD.
- It verifies seed derivation, not mnemonic word-list lookup or checksum reconstruction.
- It compares raw private scalar, chain code, and compressed public key at every BIP32 node. It does not implement Base58Check xprv/xpub serialization.
- It does not implement BIP44/BIP49/BIP84 address projection, address discovery, blockchain lookup, signing, or transaction construction.
- It does not enumerate anything and cannot compare derived data to a supplied target.
- It is a simple one-thread-per-vector implementation. SHA-512 schedules and curve temporaries consume substantial registers/local memory, so it is a conformance baseline rather than a tuned production GPU library.

See `docs/TRACEABILITY.md` for the SARA-to-CUDA operator map and `docs/SAFETY_SCOPE.md` for the misuse-boundary audit.
