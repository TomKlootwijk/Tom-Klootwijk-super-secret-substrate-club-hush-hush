#!/usr/bin/env python3
"""Static policy and handoff checks that do not require an Android SDK."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
CORE = ROOT / "core"
errors: list[str] = []
checks: dict[str, object] = {}


def require(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


java_files = sorted((APP / "src/main/java").rglob("*.java"))
core_files = sorted((CORE / "src/main/java").rglob("*.java"))
checks["app_java_files"] = len(java_files)
checks["core_java_files"] = len(core_files)
require(len(java_files) >= 8, "expected native Android source files")
require(len(core_files) >= 20, "expected platform-independent core source files")

for file in java_files + core_files:
    text = file.read_text(encoding="utf-8")
    relative = file.relative_to(ROOT).as_posix()
    for forbidden in ("import androidx.", "import com.google.", "import org.opencv."):
        require(forbidden not in text, f"forbidden dependency import in {relative}: {forbidden}")
    require("System.loadLibrary" not in text, f"unexpected native library load in {relative}")
    require("java.net." not in text, f"runtime network API in {relative}")

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
    require(dependency_lines == ["implementation project(':core')"],
            f"unexpected app dependencies: {dependency_lines}")

camera_source = (APP / "src/main/java/org/ugts/atlas/slam/Camera2Controller.java").read_text()
require("android.hardware.camera2" in camera_source, "Camera2 API not used")
require("ImageReader.newInstance" in camera_source, "ImageReader analysis path missing")
require("acquireLatestImage" in camera_source, "latest-frame backpressure policy missing")
require(re.search(r"ImageFormat\.YUV_420_888,\s*2\)", camera_source) is not None,
        "ImageReader maxImages=2 bound missing")

analyzer_source = (APP / "src/main/java/org/ugts/atlas/slam/FrameAnalyzer.java").read_text()
require("finally" in analyzer_source and "image.close()" in analyzer_source,
        "acquired Image close guarantee missing")

main_source = (APP / "src/main/java/org/ugts/atlas/slam/MainActivity.java").read_text()
require("Intent.ACTION_CREATE_DOCUMENT" in main_source,
        "document-provider export path missing")
require("FileProvider" not in main_source, "FileProvider dependency remained")

engine_source = (CORE / "src/main/java/org/ugts/atlas/slam/core/SlamEngine.java").read_text()
for token in (
    "minimumMatches",
    "loop_closure_proposal",
    "requires_geometric_bundle_adjustment",
    "metric_scale_anchor",
    "keyframe_committed",
):
    require(token in engine_source, f"expected SLAM/ledger guard missing: {token}")

codec_source = (CORE / "src/main/java/org/ugts/atlas/slam/core/UgtsScanCodec.java").read_text()
for token in ("Varint.zigzag", "Deflater(3", "MAGIC"):
    require(token in codec_source, f"codec mechanism missing: {token}")

for forbidden_dir in ("build", ".gradle", ".cxx", ".idea"):
    found = [p for p in ROOT.rglob(forbidden_dir) if p.is_dir()]
    require(not found, f"generated/cache directory included: {found[:3]}")

checks["network_permission"] = False
checks["external_android_runtime_dependencies"] = 0
checks["camera_api"] = "Camera2"
checks["document_export"] = "ACTION_CREATE_DOCUMENT"
checks["errors"] = errors
checks["status"] = "PASS" if not errors else "FAIL"
print(json.dumps(checks, indent=2, sort_keys=True))
sys.exit(0 if not errors else 1)
