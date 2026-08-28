# Validation Evidence

- `host_validation_final.txt` - CMake configure/build plus 23 portable core checks and deterministic demo generation.
- `kseed_inspect_demo.json` - independent Python verification of the demonstration KSEED header, CRCs, zlib payloads, record framing, SHA-256 chain and final summary.
- `android_cpp_mock_syntax_final.txt` - syntax-only C++20 checks for nine Android-specific translation units against a local mock NDK surface. This is not an NDK link/build.
- `source_contract_results.json` - 43 static package/authority/privacy/toolchain checks.
- `python_compileall_4_1.txt` - retained UGTS-KC 4.0 namespace and Python tools compile.
- `shell_syntax_4_1.txt` - shell entry points pass `bash -n`.
- `pdf_build_4_1.txt`, `pdf_inspect_4_1.json`, `pdf_preflight_4_1.json`, `pdf_render_4_1.txt` - report creation and render evidence.

Not present: Android SDK/NDK assemble output, APK, AAB, device install evidence, physical camera output, phone performance, thermal trace, battery trace or SLAM accuracy result.
