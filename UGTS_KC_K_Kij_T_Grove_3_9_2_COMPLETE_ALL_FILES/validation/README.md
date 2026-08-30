# KC Elizabeth 3.9 validation evidence

This directory contains reproducible release evidence for the 3.9 upgrade. The principal records are:

- `test_results_3_9.txt` and `test_summary_3_9.json`: full 225-test run.
- `schema_validation_3_9.json` and `project_validation_3_9.json`: JSON Schema, semantic project, deterministic round-trip and headless checks.
- `catalog_validation_3_9.json`: mechanism continuity through M389.
- `browser_build_validation_3_9.json` and `javascript_syntax_3_9.txt`: offline build inspection and split-runtime JavaScript syntax check.
- `distribution_validation_3_9.json` and `package_build_3_9.txt`: wheel/source-distribution structure plus fresh-environment install and CLI smoke tests.
- `pdf_preflight_3_9.json`, `pdf_inspect_3_9.json` and `docx_a11y_audit_3_9.*`: report checks.
- `file_manifest_3_9.csv` and `manifest_3_9.sha256`: path, size and SHA-256 coverage for regular package files. The two manifest files exclude themselves to avoid recursive hashes.
- `chrono_video_sample_2026_08_30.json`: exact source/GPU/compiler/bundle/APK hashes and explicit physical-3D/device nonclaims for the scoped chrono-video fixture.
- `chrono_video_rtx_q8_live_2026_08_30.json`: live RTX 5070 Ti first/middle/last-frame Q8 parity receipt with exact output hashes and zero CPU/CUDA byte difference.
- `chrono_desktop_runtime_full_oracle_2026_08_30.json`: all-229-frame Grove Studio source-runtime audit on the RTX 5070 Ti. It binds the exact source/profile/timeline/LUT and implementation hashes, verifies every GPU Q8 raster against the NumPy oracle, enforces the 1,536 MiB workspace cap after every remap, and records CPU-decode/readback/display/Android nonclaims.

The `legacy_3_0/` subdirectory preserves evidence from the supplied archive without presenting it as new 3.9 validation.

## Physical chrono-video POCO gate

`validate_chrono_poco.ps1` is the one-command, fail-closed physical validator for the receipt-bearing chrono APK. The default APK is the `android_poco_physical_receipt` POCO debug build in the parent fixture bundle. For the current immutable build, run:

```powershell
powershell -ExecutionPolicy Bypass -File validation\validate_chrono_poco.ps1 --serial XOVSTSHYNREMZ5D6 --expected-apk-sha256 18b9d2d33826afa0c7436cbfbccfcd45ad0c408c352aa2759a2076b2d48b033b
```

The command installs exactly those local APK bytes, verifies the installed `base.apk` by on-device SHA-256 and/or a byte-for-byte ADB pull, resolves and cold-launches the exact Java activity, and emits a new timestamped directory under `validation/device/chrono_poco/`. It records raw engine and crash logs, device properties, package state, a screenshot, SurfaceFlinger cadence, PSS/RSS, CPU, battery and thermal samples, plus `report.json` and `SHA256SUMS.txt`.

A physical `PASS` requires the native positive `chrono once completion receipt` with all 229 source ordinals staged and published through ordinal 228, zero catch-up drops, zero late half-open boundaries, and `selector_boundaries_met=true`. It also requires the source/LUT runtime, Mali-G720 POCO profile, stable PID/foreground activity, cadence, screenshot, PSS and empty post-launch crash buffer. Absence is not treated as success. A missing or unauthorized phone produces a structured `BLOCKED` report with `verified_physical_device=false`.

If native startup explicitly fails closed, the report uses `CHRONO_INITIALIZATION_FAILED_CLOSED` or `CHRONO_RUNTIME_FAILED_CLOSED` and preserves the exact logged mode and reason in structured failure details. It does not collapse a positive native failure into a generic timeout.

Run the APK/ledger/receipt static audit without issuing any ADB command with:

```powershell
powershell -ExecutionPolicy Bypass -File validation\validate_chrono_poco.ps1 --static-only --expected-apk-sha256 18b9d2d33826afa0c7436cbfbccfcd45ad0c408c352aa2759a2076b2d48b033b
```

The report deliberately retains two physical nonclaims: Android MediaCodec YUV-to-RGB output is not byte-authoritative, and the harness does not claim photon-time equality. Exactness applies to APK/source bytes, native asset bindings, source PTS validation, Q8 LUT addressing, owned staging ordinals and the logical half-open selector receipt.
