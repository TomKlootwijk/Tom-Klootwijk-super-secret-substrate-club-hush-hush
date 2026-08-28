# Manifest scope

`SHA256SUMS.txt` hashes every distributed file except the checksum file itself. The final outer ZIP hash is reported beside the download deliverable because a ZIP cannot contain a stable hash of itself.

No private signing key, keystore, SDK credential, raw prior package or user font is distributed. The APK is test-signed; production rebuilds must use an operator-controlled key.
