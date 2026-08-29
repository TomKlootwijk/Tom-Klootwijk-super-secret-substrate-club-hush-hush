#!/usr/bin/env python3
"""Static source, privacy, native-boundary and build-handoff checks."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
CORE = ROOT / "core"
SEED_NATIVE = ROOT / "seednative"
errors: list[str] = []
checks: dict[str, object] = {}


def require(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


app_java = sorted((APP / "src/main/java").rglob("*.java"))
core_java = sorted((CORE / "src/main/java").rglob("*.java"))
native_java = sorted((SEED_NATIVE / "src/main/java").rglob("*.java"))
checks.update(
    app_java_files=len(app_java),
    core_java_files=len(core_java),
    native_bridge_java_files=len(native_java),
)
require(len(app_java) >= 9, "expected Android capture, UI, export and synthetic source files")
require(len(core_java) >= 35, "expected expanded platform-independent SLAM/KSEED core")
require(len(native_java) == 1, "expected one narrow JNI bridge")

for file in app_java + core_java + native_java:
    text = file.read_text(encoding="utf-8")
    relative = file.relative_to(ROOT).as_posix()
    for forbidden in ("import androidx.", "import com.google.", "import org.opencv."):
        require(forbidden not in text, f"forbidden dependency import in {relative}: {forbidden}")
    require("java.net." not in text, f"runtime network API in {relative}")
    if "System.loadLibrary" in text:
        require(
            relative.endswith("NativeSeedBridge.java"),
            f"native library load outside narrow bridge: {relative}",
        )

manifest = (APP / "src/main/AndroidManifest.xml").read_text(encoding="utf-8")
for permission in (
    "android.permission.INTERNET",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.RECORD_AUDIO",
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.WRITE_EXTERNAL_STORAGE",
    "android.permission.MANAGE_EXTERNAL_STORAGE",
):
    require(permission not in manifest, f"forbidden/unneeded permission: {permission}")
require("android.permission.CAMERA" in manifest, "camera permission missing")
checks["manifest_permissions"] = re.findall(r'uses-permission android:name="([^"]+)"', manifest)

app_gradle = (APP / "build.gradle").read_text(encoding="utf-8")
dep_block = re.search(r"dependencies\s*\{(?P<body>.*?)\}", app_gradle, re.S)
require(dep_block is not None, "dependencies block missing")
if dep_block:
    dependency_lines = [
        line.strip()
        for line in dep_block.group("body").splitlines()
        if line.strip() and not line.strip().startswith("//")
    ]
    checks["dependency_lines"] = dependency_lines
    require(
        dependency_lines == [
            "implementation project(':core')",
            "implementation project(':seednative')",
        ],
        f"unexpected app dependencies: {dependency_lines}",
    )

settings = (ROOT / "settings.gradle").read_text(encoding="utf-8")
require("':seednative'" in settings, "seednative module not included")
seed_gradle = (SEED_NATIVE / "build.gradle").read_text(encoding="utf-8")
for token in (
    "ndkVersion '29.0.14206865'",
    "abiFilters 'arm64-v8a'",
    "version '3.22.1'",
    "ANDROID_STL=c++_static",
):
    require(token in seed_gradle, f"native toolchain/profile pin missing: {token}")

camera_source = (APP / "src/main/java/org/ugts/atlas/slam/Camera2Controller.java").read_text()
require("android.hardware.camera2" in camera_source, "Camera2 API not used")
require("ImageReader.newInstance" in camera_source, "ImageReader analysis path missing")
require("acquireLatestImage" in camera_source, "latest-frame backpressure policy missing")
require(
    re.search(r"ImageFormat\.YUV_420_888,\s*2\)", camera_source) is not None,
    "ImageReader maxImages=2 bound missing",
)

analyzer_source = (APP / "src/main/java/org/ugts/atlas/slam/FrameAnalyzer.java").read_text()
require("finally" in analyzer_source and "image.close()" in analyzer_source,
        "acquired Image close guarantee missing")
main_source = (APP / "src/main/java/org/ugts/atlas/slam/MainActivity.java").read_text()
for token in (
    "Intent.ACTION_CREATE_DOCUMENT",
    "exportKSeed",
    "beginDemo",
    "NativeSeedBridge.status",
    "SYNTHETIC TAG BIT 31",
):
    require(token in main_source, f"Android handoff mechanism missing: {token}")
require("FileProvider" not in main_source, "FileProvider dependency remained")

engine_source = (CORE / "src/main/java/org/ugts/atlas/slam/core/SlamEngine.java").read_text()
for token in (
    "ProposalVerifier",
    "SpatialProposal.TAG_SYNTHETIC",
    "loop_closure_proposal",
    "requires_geometric_bundle_adjustment",
    "metric_scale_anchor",
    "FrameEvidence.summarize",
    "preStateSha256",
):
    require(token in engine_source or token in (CORE / "src/main/java/org/ugts/atlas/slam/core/LedgerEvent.java").read_text(),
            f"expected SLAM/authority mechanism missing: {token}")

verifier = (CORE / "src/main/java/org/ugts/atlas/slam/core/ProposalVerifier.java").read_text()
for token in (
    "identifier_invalid",
    "outside_support",
    "incompatible",
    "confidence_below_floor",
    "numeric_error_exceeds_margin",
    "uncertainty_exceeds_policy",
    "metric_unavailable",
):
    require(token in verifier, f"4.1 verifier gate missing: {token}")

writer = (CORE / "src/main/java/org/ugts/atlas/slam/core/KSeedWriter.java").read_text()
reader = (CORE / "src/main/java/org/ugts/atlas/slam/core/KSeedReader.java").read_text()
for token in (
    "KSeed41.HEADER_BYTES",
    "KSeed41.CHUNK_HEADER_BYTES",
    "KSeed41.SUMMARY_BYTES",
    "Deflater.BEST_SPEED",
    "candidate.length + 16 < decoded.length",
    "Morton3D.encodeSigned21",
    "KSEED41-CHAIN",
):
    require(token in writer or token in (CORE / "src/main/java/org/ugts/atlas/slam/core/KSeed41.java").read_text(),
            f"KSEED writer mechanism missing: {token}")
for token in ("header CRC mismatch", "SHA-256 chain mismatch", "stored_bytes"):
    require(token in reader, f"KSEED reader integrity check missing: {token}")

jni = (SEED_NATIVE / "src/main/cpp/jni_bridge.cpp").read_text(encoding="utf-8")
native_core = (ROOT / "native/core/seed_core.cpp").read_text(encoding="utf-8")
for token in ("JNIEXPORT", "nativeCrc32", "nativeScheduleBounded"):
    require(token in jni, f"JNI bridge mechanism missing: {token}")
for token in ("schedule_value", "crc32", "self_test"):
    require(token in native_core, f"portable native core mechanism missing: {token}")

profile = json.loads(
    (APP / "src/main/assets/device_profiles/poco_x7_pro_12gb.json").read_text(encoding="utf-8")
)
require(profile["storage"]["format"] == "KSEED 4.1", "device profile KSEED default missing")
require(profile["storage"]["raw_frames_persisted"] is False, "raw-frame default must be false")
require(profile["evidence_boundary"]["synthetic_tag_bit"] == 31, "synthetic tag bit mismatch")

for forbidden_dir in ("build", ".gradle", ".cxx", ".idea", "__pycache__"):
    found = [p for p in ROOT.rglob(forbidden_dir) if p.is_dir()]
    require(not found, f"generated/cache directory included: {found[:3]}")

checks.update(
    network_permission=False,
    external_android_runtime_dependencies=0,
    camera_api="Camera2",
    document_export="ACTION_CREATE_DOCUMENT",
    native_abi="arm64-v8a",
    storage="KSEED 4.1",
    errors=errors,
    status="PASS" if not errors else "FAIL",
)
print(json.dumps(checks, indent=2, sort_keys=True))
sys.exit(0 if not errors else 1)
