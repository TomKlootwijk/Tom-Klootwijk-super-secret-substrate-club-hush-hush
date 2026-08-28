# Notice and security boundary

UGTS-KC 3.6.3 SARA is a standards-conformance and defensive-audit reference package. It is not production wallet software and does not provide a wallet-cracking, seed-recovery or funds-access capability.

The package intentionally excludes:

- candidate or mnemonic enumeration;
- passphrase spraying;
- private-key range scanning;
- address-targeted preimage search;
- transaction signing, PSBT mutation, broadcast or funds transfer;
- live blockchain, wallet or balance network calls.

The included BIP39 English wordlist and public BIP test vectors are third-party standards fixtures. Real mnemonic, passphrase, seed, private-key and chain-code material must never be inserted into source control, reports, traces, screenshots, issue trackers or public substrate definitions.

The personal role and identifiers printed in the report were supplied by the requester and were not independently verified.
