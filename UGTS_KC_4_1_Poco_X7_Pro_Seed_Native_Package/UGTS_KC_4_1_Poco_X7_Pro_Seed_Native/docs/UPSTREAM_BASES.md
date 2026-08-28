# Upstream Bases and Provenance

## UGTS-KC 4.0 Spatial Evidence Ledger

Archive SHA-256:

```text
7ce064e5e4e2bb6b43d86f191db21111aab823771cbc1461413377a3c675d6d8
```

Report SHA-256:

```text
fe4a7dfbedb0163d90d22b4e6c5aef7e042f7342199a64eb3db3d76da1bdb1b4
```

The retained `substrate/ugts_kc4/` namespace and spatial evidence schema are copied from this base. The native records mirror its capture-profile, observation, verification, deterministic commit, route, change, replay and export boundaries.

## UGTS-KC K-Kij-T / Grove 3.9.2

Attached archive SHA-256:

```text
bd7f8aa7e5829f27020a859d9e16a8b2917017c171045fd75a1814a0cb6d4486
```

The source-only retained Android reference is under:

```text
upstream/android_3_9_2_reference/UGTSKCKKijTGrove/
```

Its source-manifest hash is recorded in `upstream/android_3_9_2_reference/SOURCE_TREE_HASH.txt`. Build caches, `.cxx`, Gradle caches and compiled APK/native objects are intentionally omitted from the new package.

The 4.1 active project reuses the proven 3.9.2 NativeActivity lifecycle, EGL/GLES3 presentation pattern, Gradle/CMake/NDK pins, POCO arm64 flavor, high-refresh request, device-hint selection and thermal adaptation structure. It replaces the game scene authority with the 4.0 observation-verifier-ledger authority.
