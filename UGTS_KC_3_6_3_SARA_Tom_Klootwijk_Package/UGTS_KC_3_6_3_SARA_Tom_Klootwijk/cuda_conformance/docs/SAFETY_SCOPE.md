# Safety and misuse-boundary audit

## Included

The package embeds exactly two public fixtures: one BIP39 seed vector and BIP32 test vector 1. Batch execution repeats those identical fixtures to measure throughput. A successful run proves that the implemented transformations reproduce published outputs on this CPU and GPU.

## Deliberately absent

- Runtime mnemonic or passphrase input
- Candidate generation, mutation, enumeration, or dictionaries
- Runtime derivation-path input
- Address or public-key target input
- Equality testing against a user-supplied target
- BIP44/BIP49/BIP84 wallet/address projection
- Blockchain/network access
- Secret persistence or export workflow
- Signing or transaction creation

These omissions are structural, not a warning around dormant functionality: the command-line parser has no such options and the kernels refer only to compile-time fixtures.

## What the benchmark says about misuse feasibility

It demonstrates that the SARA seed and BIP32 transformations can be represented as deterministic GPU kernels and run concurrently. It does not demonstrate wallet recovery, a search loop, address matching, or practical candidate-generation throughput. The reported BIP39 operations per second are therefore a primitive-throughput measurement on one immutable vector, not a credential-search claim.

The main remaining optimization gaps - register pressure, local-memory stack use, SHA-512 scheduling, secp256k1 field arithmetic, occupancy, batching strategy, and independent cryptographic review - are documented because they explain how far the conformance baseline is from a production-quality GPU library. They are not paired with candidate enumeration or target comparison.
