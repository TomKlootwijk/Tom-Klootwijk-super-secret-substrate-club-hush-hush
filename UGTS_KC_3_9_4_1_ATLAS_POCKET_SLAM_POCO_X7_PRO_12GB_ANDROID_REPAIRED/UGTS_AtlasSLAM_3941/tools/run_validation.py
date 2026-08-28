#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATION = ROOT / "validation"
VALIDATION.mkdir(exist_ok=True)


def run(name: str, command: list[str]) -> dict:
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )
    return {
        "name": name,
        "command": command,
        "returncode": result.returncode,
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "stdout": result.stdout,
        "stderr": result.stderr,
        "status": "PASS" if result.returncode == 0 else "FAIL",
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def syntax_check_python() -> dict:
    errors = []
    count = 0
    for path in sorted((ROOT / "tools").glob("*.py")):
        count += 1
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except SyntaxError as error:
            errors.append(f"{path.name}:{error.lineno}:{error.msg}")
    return {
        "name": "python_source_syntax",
        "count": count,
        "errors": errors,
        "status": "PASS" if not errors else "FAIL",
    }


def json_check() -> dict:
    errors = []
    count = 0
    for path in sorted(ROOT.rglob("*.json")):
        if "validation/release_validation.json" in path.as_posix():
            continue
        count += 1
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:
            errors.append(f"{path.relative_to(ROOT)}: {error}")
    return {
        "name": "json_parse",
        "count": count,
        "errors": errors,
        "status": "PASS" if not errors else "FAIL",
    }


def android_sdk_status() -> dict:
    candidates = []
    for key in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        if os.environ.get(key):
            candidates.append(Path(os.environ[key]))
    local = ROOT / "local.properties"
    if local.exists():
        for line in local.read_text(errors="ignore").splitlines():
            if line.startswith("sdk.dir="):
                candidates.append(Path(line.split("=", 1)[1].replace("\\:", ":")))
    for candidate in candidates:
        android_jar = candidate / "platforms/android-36/android.jar"
        if android_jar.is_file():
            return {
                "available": True,
                "sdk_root": str(candidate),
                "android_36_jar": str(android_jar),
            }
    return {
        "available": False,
        "reason": "No Android SDK Platform 36 was available in the packaging environment",
    }


commands = [
    run("core_host_tests", [str(ROOT / "tools/run_host_tests.sh")]),
    run("android_shell_stub_compile", ["python3", str(ROOT / "tools/compile_android_stubs.py")]),
    run("gradle_bootstrap_self_test", [str(ROOT / "gradlew"), "--bootstrap-self-test"]),
    run("gradle_bootstrap_local_integration", [str(ROOT / "tools/test_bootstrap_local.sh")]),
    run("android_source_policy", ["python3", str(ROOT / "tools/verify_android_source.py")]),
    run(
        "sample_scan_verification",
        [
            "python3",
            str(ROOT / "tools/ugts_scan_tool.py"),
            str(ROOT / "samples/synthetic_codec_sample.ugtsscan"),
            "--summary-only",
        ],
    ),
]
extra = [syntax_check_python(), json_check()]
all_results = commands + extra
status = "PASS" if all(item["status"] == "PASS" for item in all_results) else "FAIL"
wrapper = ROOT / "gradle/wrapper/gradle-wrapper.jar"
sample = ROOT / "samples/synthetic_codec_sample.ugtsscan"
report = {
    "schema": "ugts.android-validation/3.9.4.1",
    "release": "3.9.4.1",
    "status": status,
    "environment": {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "java": subprocess.run(
            ["java", "-version"], text=True, capture_output=True, check=False
        ).stderr.splitlines()[0],
        "android_sdk": android_sdk_status(),
    },
    "android_build": {
        "attempted": False,
        "apk_in_release": False,
        "reason": "Android SDK Platform 36 was unavailable; no unbuilt APK is presented as validated output",
        "build_command": "./tools/build_android.sh",
    },
    "physical_device_validation": {
        "attempted": False,
        "target": "POCO X7 Pro 12 GB RAM edition",
        "reason": "No physical target device was attached to the packaging environment",
    },
    "artifacts": {
        "gradle_bootstrap_jar_sha256": sha256(wrapper),
        "gradle_bootstrap_jar_bytes": wrapper.stat().st_size,
        "sample_scan_sha256": sha256(sample),
        "sample_scan_bytes": sample.stat().st_size,
    },
    "checks": all_results,
}
(VALIDATION / "release_validation.json").write_text(
    json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
summary = [
    "UGTS-KC 3.9.4.1 validation",
    f"Overall: {status}",
    "",
]
for item in all_results:
    summary.append(f"{item['status']:4}  {item['name']}")
summary.extend(
    [
        "",
        "Android APK build: NOT ATTEMPTED (SDK Platform 36 unavailable)",
        "Physical POCO validation: NOT ATTEMPTED",
        "These two boundaries are explicit and are not counted as failed host checks.",
    ]
)
(VALIDATION / "VALIDATION_SUMMARY.txt").write_text("\n".join(summary) + "\n")
print("\n".join(summary))
raise SystemExit(0 if status == "PASS" else 1)
