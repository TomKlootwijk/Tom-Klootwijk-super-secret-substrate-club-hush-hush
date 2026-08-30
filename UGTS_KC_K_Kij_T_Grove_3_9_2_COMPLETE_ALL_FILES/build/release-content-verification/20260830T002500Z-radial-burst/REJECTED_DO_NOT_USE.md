# Rejected artifact

Do not distribute the wheel or source archive in this directory. This first
candidate incorrectly included local Android `.gradle`, `.cxx`, and build-cache
files and exists only as regression evidence.

Use `build/release-handoff/20260830T004000Z-radial-burst` instead. The manifest
fix was also re-run against this deliberately cache-populated staging tree; the
separate `20260830T004200Z-manifest-prune-proof` output contains zero forbidden
cache or bytecode paths.
