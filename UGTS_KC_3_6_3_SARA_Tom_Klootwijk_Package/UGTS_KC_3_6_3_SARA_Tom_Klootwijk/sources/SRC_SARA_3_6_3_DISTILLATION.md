# SARA 3.6.3 standards distillation

## Scope

The requester asked to reuse the seed-phrase/address paradigm inside the substrate and also asked for a brute-force penetration-testing route against a named public mainnet address. The standards integration is admitted; the unauthorized-access component is not. The resulting delta is a public-only, self-owned defensive-audit profile.

## Standards distilled

### BIP39

- Computer-generated entropy length `ENT` is 128, 160, 192, 224 or 256 bits.
- `CS = ENT / 32` checksum bits are copied from the start of SHA-256(entropy).
- `ENT + CS` is segmented into 11-bit indices over a committed 2048-word list.
- The normalized sentence and optional passphrase feed PBKDF2-HMAC-SHA512 with 2048 iterations and a 64-byte output.
- The sentence is an encoding of entropy, not a general-purpose brainwallet sentence.

### BIP32

- The seed creates a master private scalar and 32-byte chain code.
- Extended nodes form a rooted derivation tree.
- Normal child edges are indexed below `2^31`; hardened edges are indexed at or above `2^31` and cannot be derived from an extended public parent.
- Parent fingerprints are short routing hints, not collision-free identity.

### BIP44/BIP84

- The path is typed as purpose / coin / account / change / address index.
- Native P2WPKH accounts use purpose `84'`.
- The package reproduces the public BIP84 vector at `m/84'/0'/0'/0/0`.

### BIP141/BIP173/BIP350

- A witness-v0 20-byte program is P2WPKH and maps to `0x0014{program}`.
- Witness-v0 addresses use Bech32; witness versions 1-16 use Bech32m.
- The address checksum detects transcription errors but is not authentication or proof of ownership.

## UGTS translation

- Entropy plus checksum becomes a finite bit relation.
- Each 11-bit group becomes a labeled cell in a one-dimensional ordered cell complex.
- The checksum is a guard surface.
- The HD wallet becomes a rooted typed tree with normal and hardened edge classes.
- The BIP84 derivation path is a route through that tree.
- The address is a public downstream projection from a script commitment, not an identity or secret.
- The audit gate is a compatibility/policy predicate.
- A certificate becomes a verified event only when scope, checksum, derivation and non-egress rules all hold.

## Public fixture

The requester-supplied address is retained solely as a public decode fixture. The package verifies its Bech32 checksum, witness version, witness program length and scriptPubKey. It does not infer or search for a mnemonic, seed or private key and does not validate any ownership label.

## Rejected escalation

The following are deliberately absent:

- mainnet address-targeted key or preimage search;
- mnemonic or passphrase enumeration;
- private-key scanning;
- signing, PSBT mutation, broadcast or funds transfer;
- live balance or blockchain network access;
- claims that public visibility supplies authorization.
