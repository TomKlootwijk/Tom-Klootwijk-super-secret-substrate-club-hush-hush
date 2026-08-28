# UGTS-KC 3.6.3 - SARA

**Seed-Address Referential Algebra**

Version 3.6.3 maps the deterministic, public standards pipeline used by Bitcoin mnemonic wallets into the UGTS referential substrate:

```text
entropy -> BIP39 checksum -> 11-bit word cells -> mnemonic
        -> PBKDF2 seed (transient) -> BIP32 key tree
        -> BIP84 path -> compressed public key -> HASH160
        -> P2WPKH scriptPubKey -> Bech32 address
```

**Requester-supplied attribution:** Tom Klootwijk, Principal Creative Technologist, 10-07-1990, NL200678942. The role and identifiers are recorded as supplied and were not independently verified.

## 3.6.3 additions

The `sara363.\*` namespace adds **45 atomic operators**, **19 content-addressed definitions** and **20 claims-ledger entries** covering:

1. BIP39 entropy, checksum, 11-bit segmentation and a word-cell complex.
2. Unicode NFKD normalization and the standard PBKDF2-HMAC-SHA512 seed transition.
3. A typed BIP32 tree with distinct normal and hardened edges.
4. The BIP84 P2WPKH derivation path and public test vectors.
5. Compressed secp256k1 public keys, HASH160, witness programs and scriptPubKeys.
6. Bech32 and Bech32m encoding/decoding with version and program-length rules.
7. A public-only certificate that excludes mnemonic, passphrase, seed, private scalar and chain code.
8. An authorization gate that rejects private-key search, third-party secret access and transaction capability.
9. Optimistic keyspace/time estimators that calculate work without enumerating candidates.
10. A canonical handoff to `support -> compatibility -> guard -> verified event -> transition -> lineage`.

## Exact public fixtures

The official BIP84 public test mnemonic derives:

```text
path:       m/84'/0'/0'/0/0
pubkey:     0330d54fd0dd420a6e5f8d3624f5f3482cae350f79d5f0753bf5beef9c2d91af3c
address:    bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu
```

The user-supplied public address decodes as:

```text
HRP:                    bc
checksum family:        Bech32
witness version:        0
witness program bytes:  20
witness program:        f11a35b66716946bc3e0201645c4fbdd72ac56f1
address type:            P2WPKH
scriptPubKey:            0014f11a35b66716946bc3e0201645c4fbdd72ac56f1
```

The package treats any ownership label as external metadata and does not use it as cryptographic or legal proof.

The serialized reference certificate also excludes secret-equivalent word indices and mnemonic-, entropy- and seed-derived fingerprints. Only public route, key, script, address and reason-code data cross the certificate boundary.

## Search-space metrics

For a uniform `b`-bit space at rate `R`, the estimator reports `2^b` candidates, `2^(b-1)` expected guesses and `2^(b-1)/R` expected time. It does not generate candidates.

At an intentionally unrealistic `10^15` trials/second:

```text
12-word valid BIP39 space (128 bits): expected \~5.39e15 years
P2WPKH 160-bit target preimage:       expected \~2.32e25 years
secp256k1 private scalar (256 bits):  expected \~1.83e54 years
```

A 20-bit toy metric is included only to make scale understandable. It is not Bitcoin-compatible and has no wallet-search implementation.

## Quick start

```bash
PYTHONPATH=src python examples/demo\_sara363.py
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Package layout

```text
report/
  UGTS\_KC\_3\_6\_3\_SARA\_Tom\_Klootwijk.pdf
  UGTS\_KC\_3\_6\_3\_SARA\_Tom\_Klootwijk.tex
  figures/
spec/
  SARA\_3\_6\_3\_FORMAL\_DEFINITION.md
  ugts\_kc\_3\_6\_3\_sara.schema.json
  sara\_3\_6\_3\_delta\_operator\_catalog.csv/json
  sara\_3\_6\_3\_claims\_ledger.csv/json
src/ugts36/
  sara363.py
  sara\_runtime.py
  retained 3.6/3.6.1/3.6.2 modules
examples/
  ugts\_kc\_3\_6\_3\_sara\_example.json
  demo\_sara363.py
  public-only certificate and trace
data/
  official BIP39 English wordlist fixture
  public address decode fixture
  reference certificate and search-space metrics
sources/
  standards/source register and distillation note
checksums/
  SHA256SUMS.txt and package manifest
```

## Validation

The complete retained suite contains **195 passing tests**: 42 SARA tests and 153 tests from versions 3.6 through 3.6.2. The final package additionally checks JSON Schema validity, content-address hashes, dependency order, public-address round-trip, secret-free certificate keys, absence of network/signing APIs, the official wordlist digest and PDF preflight.

