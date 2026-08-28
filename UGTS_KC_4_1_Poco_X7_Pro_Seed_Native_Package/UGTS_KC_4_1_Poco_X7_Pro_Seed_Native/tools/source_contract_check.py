#!/usr/bin/env python3
"""Static release-contract checks for the UGTS-KC 4.1 source package."""
from __future__ import annotations
import csv
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RESULTS: list[dict[str, object]] = []

def record(name: str, passed: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "passed": bool(passed), "detail": detail})

def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def contains(path: str, *needles: str) -> bool:
    try:
        value = text(path)
    except OSError:
        return False
    return all(item in value for item in needles)

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def main() -> int:
    record("version_file", text("VERSION").strip() == "4.1.0", text("VERSION").strip())
    required = [
        "README.md", "NOTICE.md", "android_project/app/build.gradle",
        "android_project/app/src/main/AndroidManifest.xml",
        "android_project/app/src/main/cpp/CMakeLists.txt",
        "spec/KSEED_FORMAT_4_1.md", "spec/UGTS_ANDROID_NATIVE_CONTRACT_4_1.md",
        "docs/CODEX_BUILD_AND_DEPLOY.md", "tools/kseed_inspect.py",
        "examples/demo_session.kseed", "substrate/ugts_kc4/ledger.py",
    ]
    record("required_files", all((ROOT / p).is_file() for p in required), str(len(required)))

    record("agp_pin", contains("android_project/build.gradle", 'version "8.13.2"'), "AGP 8.13.2")
    record("compile_target_sdk", contains("android_project/app/build.gradle", "compileSdk 36", "targetSdk 36", "minSdk 26"))
    record("ndk_cmake_pin", contains("android_project/app/build.gradle", 'ndkVersion "29.0.14206865"', 'version "3.22.1"'))
    record("poco_flavor_arm64", contains("android_project/app/build.gradle", "pocoX7Pro", 'abiFilters "arm64-v8a"', 'applicationIdSuffix ".poco"'))
    record("owner_handoff_debuggable", contains("android_project/app/build.gradle", "signingConfig signingConfigs.debug", "debuggable true"))
    record("native_activity", contains("android_project/app/src/main/AndroidManifest.xml", "android.app.NativeActivity", 'android:hasCode="false"'))
    record("camera_permission", contains("android_project/app/src/main/AndroidManifest.xml", "android.permission.CAMERA"))
    record("no_internet_permission", "android.permission.INTERNET" not in text("android_project/app/src/main/AndroidManifest.xml"))
    record("gles3_required", contains("android_project/app/src/main/AndroidManifest.xml", 'android:glEsVersion="0x00030000"'))

    cmake = text("android_project/app/src/main/cpp/CMakeLists.txt")
    record("native_libraries", all(x in cmake for x in ["camera2ndk", "mediandk", "GLESv3", "z"]), "camera2ndk/mediandk/GLESv3/z")
    record("cpp20", "CMAKE_CXX_STANDARD 20" in cmake and "-fexceptions" in cmake)

    camera = text("android_project/app/src/main/cpp/camera_ndk.cpp")
    record("camera_yuv", "AIMAGE_FORMAT_YUV_420_888" in camera and "AImageReader_acquireLatestImage" in camera)
    record("camera_latest_bounded", "latest_=" in camera and "maxImages" not in camera, "single latest frame state")
    imu = text("android_project/app/src/main/cpp/imu_ndk.cpp")
    record("imu_sensors", all(x in imu for x in ["ASENSOR_TYPE_ACCELEROMETER", "ASENSOR_TYPE_GYROSCOPE", "ASENSOR_TYPE_ROTATION_VECTOR"]))
    engine = text("android_project/app/src/main/cpp/engine.cpp")
    record("proposal_then_commit", "proposals_from_frame" in engine and "ledger_.commit" in engine)
    record("synthetic_tag", "1U<<31U" in engine)
    record("thermal_event", "EventKind::ThermalPolicy" in engine and "pause_capture" in engine)
    record("app_private_sessions", 'sessions_(root_/"sessions")' in text("android_project/app/src/main/cpp/storage_android.cpp"))

    verifier = text("android_project/app/src/main/cpp/core/verifier.cpp")
    gates = ["support_ok", "compatibility_ok", "GuardStatus", "confidence", "numeric_error", "uncertainty", "metric_required"]
    record("verifier_gates", all(x in verifier for x in gates), ",".join(gates))
    ledger = text("android_project/app/src/main/cpp/core/ledger.cpp")
    record("ledger_pre_post_hash", "e.pre_hash=state_hash_" in ledger and "e.post_hash=s.finish()" in ledger)
    spatial = text("android_project/app/src/main/cpp/core/spatial_keys.cpp")
    record("spatial_key_profiles", "pack_voxel_key" in spatial and "pack_ray_key" in spatial)
    seed = text("android_project/app/src/main/cpp/core/seed.cpp")
    record("seeded_identifiers", "splitmix64" in seed and "stable_id" in seed)

    codec = text("android_project/app/src/main/cpp/core/kseed_codec.cpp")
    record("kseed_magic", '"KSEED41"' in codec and "HB=128" in codec and "CB=64" in codec)
    record("kseed_integrity", all(x in codec for x in ["crc32(raw)", "crc32(stored)", "Sha256", "chain_="]))
    record("kseed_conditional_zlib", "compress2" in codec and "o.size()+16>=raw.size()" in codec)
    record("kseed_final_size", "predicted=bytes_written_+CB+stored.size()" in codec)
    profile = json.loads(text("android_project/app/src/main/assets/capture_profile_poco_x7_pro.json"))
    record("profile_no_raw_frames", profile["storage"]["raw_frame_retention"] is False)
    record("profile_no_ray_tracing", profile["presentation"]["ray_tracing"] is False)
    record("profile_authority", "only verified ledger commits" in profile["authority"])
    shader = text("android_project/app/src/main/assets/shaders/bayer.frag")
    record("bayer_8x8_shader", "const int B[64]" in shader and "gl_FragCoord" in shader)

    host = text("validation/host_validation_final.txt") if (ROOT / "validation/host_validation_final.txt").exists() else ""
    record("host_tests_23", "TOTAL PASS: 23" in host or "TOTAL PASS: 23/23" in host)
    mock = text("validation/android_cpp_mock_syntax_final.txt") if (ROOT / "validation/android_cpp_mock_syntax_final.txt").exists() else ""
    record("android_mock_syntax_9", "TOTAL PASS: 9/9" in mock)
    inspect_path = ROOT / "validation/kseed_inspect_demo.json"
    try:
        inspected = json.loads(inspect_path.read_text())
        integrity_record = inspected.get("integrity", {})
        integrity = bool(integrity_record.get("complete") and integrity_record.get("header_crc_ok") and integrity_record.get("chunk_crc_ok") and integrity_record.get("chain_ok"))
        record("independent_kseed_integrity", integrity, str(inspected.get("file_bytes")))
        summary_record = next((c.get("summary") for c in inspected.get("chunks", []) if c.get("type") == 4), {})
        record("demo_exact_size", summary_record.get("stored_bytes") == inspected.get("file_bytes"))
    except Exception as exc:
        record("independent_kseed_integrity", False, str(exc))
        record("demo_exact_size", False, str(exc))

    summary = json.loads(text("examples/demo_session_summary.json"))
    record("demo_scope_boundary", "not a phone benchmark" in summary.get("scope", ""))
    record("demo_expected_counts", summary.get("frames_seen") == 300 and summary.get("keyframes_stored") == 63 and summary.get("events_committed") == 592)

    with (ROOT / "spec/mechanisms_M510_M569.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ids = [row["id"] for row in rows]
    record("mechanisms_contiguous", ids == [f"M{i}" for i in range(510, 570)], f"{len(ids)} rows")

    ref_dir = ROOT / "upstream/android_3_9_2_reference/UGTSKCKKijTGrove"
    source_lines = []
    for path in sorted(p for p in ref_dir.rglob("*") if p.is_file()):
        rel = "./" + path.relative_to(ref_dir).as_posix()
        source_lines.append(f"{sha256_file(path)}  {rel}\n")
    expected_manifest = (ROOT / "upstream/android_3_9_2_reference/SHA256_SOURCE_FILES.txt").read_text()
    record("upstream_source_manifest", "".join(source_lines) == expected_manifest, f"{len(source_lines)} files")
    manifest_hash = hashlib.sha256(expected_manifest.encode()).hexdigest()
    declared = text("upstream/android_3_9_2_reference/SOURCE_TREE_HASH.txt").split()[0]
    record("upstream_source_tree_hash", manifest_hash == declared, declared)

    stale_names = {"build", ".gradle", ".cxx", "__pycache__"}
    stale = [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_dir() and p.name in stale_names]
    record("no_stale_build_caches", not stale, ",".join(stale[:8]))

    docs = ["README.md", "docs/CODEX_BUILD_AND_DEPLOY.md", "docs/SEED_STORAGE_BOUNDARY.md", "docs/SECURITY_PRIVACY.md", "docs/RELEASE_STATUS.md"]
    boundary_terms = ["apk", "not a phone benchmark", "seed", "debug"]
    corpus = "\n".join(text(p) for p in docs)
    record("honest_release_boundaries", all(term.lower() in corpus.lower() for term in boundary_terms))

    passed = sum(1 for r in RESULTS if r["passed"])
    report = {
        "schema": "ugts-kc-source-contract-results-4.1",
        "root": ROOT.name,
        "passed": passed,
        "total": len(RESULTS),
        "all_passed": passed == len(RESULTS),
        "checks": RESULTS,
    }
    out = ROOT / "validation/source_contract_results.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": passed, "total": len(RESULTS), "all_passed": report["all_passed"]}))
    if passed != len(RESULTS):
        for item in RESULTS:
            if not item["passed"]:
                print(f"FAIL: {item['name']}: {item['detail']}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
