# Migration from 3.9 to 3.9.1

No 3.9 2D project migration is required. The 2D schema remains
`ugts-kc-game-project-3.9`, and the existing `new`, `validate`, `simulate`, `build-web` and
`export-svg` commands remain available.

To add 3D/mobile delivery, create a separate `ugts-kc-mobile-3d-project-3.9.1` file and use the new
`*-3d` and `build-android` commands. Do not relabel a 2D project as a 3D project: the schemas,
asset records and runtimes are intentionally distinct.

Python distribution name changes from `ugts-kc-elizabeth` to `ugts-kc-signature`; imports remain
under `ugts_kc3`, and the console command remains `ugts-kc`.
