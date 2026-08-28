# UGTS-KC 3.6.3 SARA security boundary

SARA is a deterministic-wallet **standards-conformance and public-structure** profile. It is not a wallet attack, recovery, signing or transaction system.

## Allowed reference uses

- Official BIP39/BIP32/BIP84/Bech32/Bech32m public vectors.
- Validation of a mnemonic or seed already controlled by the operator.
- Public address, script and watch-only consistency checks.
- Regtest, signet and testnet experiments.
- Checksum, schema, derivation and search-space metrics.

## Rejected capabilities

- Third-party mainnet key search or address-targeted preimage search.
- Mnemonic enumeration, permutation search or passphrase spraying.
- Private-key scanning, transaction signing, PSBT mutation or broadcasting.
- Balance targeting, funds transfer or any claim of spend authority.

## Secret handling

Entropy, word indices, mnemonic text, passphrases, seeds, private scalars, chain codes, xprvs and WIFs are transient. They are prohibited from definitions, traces, certificates and package data. The public reference certificate omits secret-equivalent word indices and secret-derived fingerprints.

The dependency-free elliptic-curve implementation exists only as a transparent public-vector oracle. It is not production wallet software.
