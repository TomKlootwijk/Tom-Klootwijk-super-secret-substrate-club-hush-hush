# UGTS-KC 3.6.3 SARA formal definition

## Seed-Address Referential Algebra

Version 3.6.3 maps the public deterministic wallet pipeline into a typed referential substrate while imposing a non-negotiable authorization and secret-handling boundary. It does not implement third-party wallet brute force, candidate enumeration, transaction signing, broadcasting or funds transfer.

### Core state

The abstract cryptographic state is

```text
q_crypto = (profile, ENT, CS, word_cells, mnemonic, seed_transient,
            hd_node_transient, derivation_path, public_key, witness_program,
            script_pubkey, address, authorization, lineage)
```

`word_cells`, the mnemonic, passphrase, `seed_transient`, private scalars and chain codes are never serialized into the public certificate. Secret-equivalent cell indices and mnemonic-, entropy- or seed-derived fingerprints are excluded as well.

### BIP39 cell map

```text
CS = ENT / 32
MS = (ENT + CS) / 11
B = ENT || prefix_CS(SHA256(ENT))
word_cell_i = B[11i : 11(i+1)] in [0,2047]
```

The ordered words form a one-dimensional labeled cell complex. The checksum is a guard relation, not an ownership proof.

### Seed transition

```text
seed = PBKDF2-HMAC-SHA512(
    password=NFKD(mnemonic),
    salt=NFKD('mnemonic' || passphrase),
    iterations=2048,
    bytes=64
)
```

### HD tree

BIP32 nodes carry key material, chain code, depth, parent fingerprint and child number. Normal edges use indices below `2^31`; hardened edges use indices at or above `2^31` and cannot be derived from an extended public parent. The BIP84 public test path is `m/84'/0'/0'/0/0`.

### Address projection

```text
pubkey = compressed(point(private_scalar))
program = RIPEMD160(SHA256(pubkey))
scriptPubKey = 0x0014 || program
address = Bech32(hrp='bc', witness_version=0, program)
```

The user-supplied public fixture decodes to witness version 0, a 20-byte witness program and P2WPKH scriptPubKey. This is a public structural observation; it is not a route to a private key.

### Authorization guard

Permitted scopes are public test vectors, self-owned known-seed validation, public address decoding, watch-only checks, regtest/signet/testnet experiments and search-space estimation. Forbidden scopes include third-party mainnet key search, mnemonic enumeration, passphrase spraying, private-key scanning, transaction signing, broadcast and funds transfer.

### Search metrics

The package computes expected work only; it does not enumerate. For a uniform `b`-bit space at rate `R`, expected work is `2^(b-1)` trials and expected time is `2^(b-1)/R`. A 12-word BIP39 sentence carries 128 bits of entropy; its checksum makes one in sixteen arbitrary 12-word index sequences syntactically valid but does not reduce the valid space below `2^128`.

### UGTS handoff

After public cryptographic certification, authority returns to:

```text
support -> compatibility -> guard -> verified event -> transition -> lineage
```
