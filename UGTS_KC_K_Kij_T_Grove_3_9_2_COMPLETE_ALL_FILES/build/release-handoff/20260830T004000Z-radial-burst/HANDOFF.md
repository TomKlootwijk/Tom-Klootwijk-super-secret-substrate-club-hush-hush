# UGTS Radial Burst handoff

This folder contains the current Burst-integrated editor/runtime package and a
ready-to-open 128-copy **LUT + Bayer Subtle** project/APK pair.

## GUI build and deploy

1. Double-click `RUN_UGTS_STUDIO.cmd` in the repository root.
2. Open `Radial-Burst-128-LUT-Bayer-Subtle.project.json` from this folder.
3. In **Output & Builds**, select **Poco X7 Pro APK (Debug)**.
4. Connect and authorize exactly one USB-debugging phone.
5. Click the blue **Deploy to Phone** toolbar button, or press
   `Ctrl+Shift+D`. The editor preflights ADB, builds, installs, and opens the
   project on that same device serial.
6. Leave the game visible and press `Ctrl+Shift+P` for the bounded 30-second
   **Check Phone** profile.

The included APK is an already-built debug artifact with the actual
flavor-suffixed application ID
`org.ugts.games.packed_polar_recipe_lab_3d.pocox7pro`. It is suitable for local device
testing, not store distribution or production signing.

## Frozen artifacts

| File | Bytes | SHA-256 |
|---|---:|---|
| `UGTS-Radial-Burst-128-LUT-Bayer-Subtle-Poco-debug.apk` | 1,804,562 | `47052901ae85619246f53f6fb8582ae78a288ebb7705312544f7b5d67b2ed3ae` |
| `Radial-Burst-128-LUT-Bayer-Subtle.project.json` | 21,283 | `94c2d0764dee3beb12070dd9c598993635af62bdd9723ba71584db72da1f6529` |
| `ugts_kc_signature-3.9.2-py3-none-any.whl` | 570,134 | `57ed5f2dc65bd02cead994efab0a6036be112ce3b84cf7470ab329f31d20b59b` |
| `ugts_kc_signature-3.9.2.tar.gz` | 676,049 | `c8851bdfb9dc97e0c18ce6c50427365fd5b3598e006969be7a416a0c472847cf` |

The APK came from the preserved 18/18 build-only matrix at
`build/poco-polar-render-benchmarks/20260830T000848Z-seed-5eed3920c0dec0de`.
It has not yet been run on the POCO/Mali device; no FPS, GPU-time, temperature,
power, or visual-parity claim is attached to it.
