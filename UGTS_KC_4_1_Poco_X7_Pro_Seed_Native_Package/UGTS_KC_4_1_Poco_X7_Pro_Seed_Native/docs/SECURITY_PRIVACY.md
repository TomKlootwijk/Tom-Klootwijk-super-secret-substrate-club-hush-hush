# Security and Privacy Notes

- The application declares camera permission only. It declares no internet permission.
- Session files are created in app-private storage.
- Raw frames are not retained under the default POCO profile.
- KSEED includes content/integrity hashes, but no encryption.
- A 64-bit seed is not a secret and must not be treated as an encryption key.
- The release build in this handoff is debug-key signed and debuggable to permit owner-device ADB work. This is unsuitable for public distribution.
- Production hardening must add private signing, disable debugging, define retention/deletion policy, assess device backup behavior, and evaluate rooted/compromised-device threats.
- Camera evidence can include sensitive spaces and activity even when only descriptors are retained. Obtain consent and follow applicable law and policy.
