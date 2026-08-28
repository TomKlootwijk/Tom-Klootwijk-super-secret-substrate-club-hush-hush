# KC Elizabeth 3.9 validation evidence

This directory contains reproducible release evidence for the 3.9 upgrade. The principal records are:

- `test_results_3_9.txt` and `test_summary_3_9.json`: full 225-test run.
- `schema_validation_3_9.json` and `project_validation_3_9.json`: JSON Schema, semantic project, deterministic round-trip and headless checks.
- `catalog_validation_3_9.json`: mechanism continuity through M389.
- `browser_build_validation_3_9.json` and `javascript_syntax_3_9.txt`: offline build inspection and split-runtime JavaScript syntax check.
- `distribution_validation_3_9.json` and `package_build_3_9.txt`: wheel/source-distribution structure plus fresh-environment install and CLI smoke tests.
- `pdf_preflight_3_9.json`, `pdf_inspect_3_9.json` and `docx_a11y_audit_3_9.*`: report checks.
- `file_manifest_3_9.csv` and `manifest_3_9.sha256`: path, size and SHA-256 coverage for regular package files. The two manifest files exclude themselves to avoid recursive hashes.

The `legacy_3_0/` subdirectory preserves evidence from the supplied archive without presenting it as new 3.9 validation.
