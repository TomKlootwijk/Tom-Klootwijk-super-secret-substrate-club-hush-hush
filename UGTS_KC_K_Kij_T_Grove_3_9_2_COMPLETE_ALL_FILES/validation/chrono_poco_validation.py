"""Fail-closed physical validation for the UGTOMS chrono-video POCO build.

The harness deliberately separates static APK evidence from physical-device
evidence.  A missing/unauthorized phone produces a structured BLOCKED report;
it can never be mistaken for a device pass.  A physical PASS requires an
installed-APK byte match, the positive native ONCE completion receipt, zero
late half-open boundaries, a live process, a foreground activity, usable frame
cadence, a screenshot, memory/thermal samples, and an empty post-launch crash
buffer.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time
from typing import Any, Sequence
import zipfile


REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ugts_kc3.androidbuild import (  # noqa: E402
    _cpu_tick_delta,
    _parse_battery,
    _parse_cpu_ticks,
    _parse_meminfo,
    _parse_thermal,
    parse_gpu_timer_log,
    parse_surfaceflinger_latency,
)


SCHEMA = "ugtoms-chrono-poco-physical-validation-1"
EXPECTED_APPLICATION_ID = "org.ugts.games.chrono_video_observation_inspector.pocox7pro"
EXPECTED_ACTIVITY = "org.ugts.runtime.UgtsNativeActivity"
EXPECTED_MODE = "AUTHORITATIVE_SOURCE_LUT"
EXPECTED_MARKET_NAME = "POCO X7 Pro"
# These two identifiers were read from the attached target itself.  Requiring
# them as a pair avoids treating an arbitrary "rodin" string or model token as
# proof of target identity when a market-name property is absent.
EXPECTED_TARGET_MODEL = "2412DPC0AG"
EXPECTED_TARGET_DEVICE = "rodin"
DEFAULT_APK = (
    REPO_ROOT.parent
    / "UGTOMS_CHRONO_VIDEO_SAMPLE_0_2_SOURCE_LUT_FINAL"
    / "android_poco_physical_receipt"
    / "app"
    / "build"
    / "outputs"
    / "apk"
    / "pocoX7Pro"
    / "debug"
    / "app-pocoX7Pro-debug.apk"
)

_HEX_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_APPLICATION_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
_DEVICE_LINE = re.compile(r"^(?P<serial>\S+)\s+(?P<state>\S+)(?P<tail>.*)$")
_GETPROP_LINE = re.compile(r"^\[(?P<key>[^]]+)\]: \[(?P<value>.*)\]$")
_REMOTE_HASH = re.compile(r"(?im)^\s*([0-9a-f]{64})\s+\S+\s*$")
_LOGCAT_EPOCH = re.compile(r"^\s*(?P<epoch>\d{9,}(?:\.\d+)?)\s+")
_COMPLETION_RECEIPT = re.compile(
    r"chrono once completion receipt\s+"
    r"mode=(?P<mode>\S+)\s+"
    r"entries=(?P<entries>\d+)\s+"
    r"published_ordinal=(?P<published>\d+)\s+"
    r"staged=(?P<staged>\d+)\s+"
    r"late_boundaries=(?P<late>\d+)\s+"
    r"selector_boundaries_met=(?P<selector>true|false)\s+"
    r"catchup_drops=(?P<drops>\d+)\s+"
    r"photon_time_claim=(?P<photon>true|false)\s+"
    r"color_byte_authoritative=(?P<color>true|false)"
)
_INITIALIZATION_FAILURE = re.compile(
    r"chrono initialization failed closed\s+"
    r"mode=(?P<mode>\S+)\s+reason=(?P<reason>.*?);\s+"
    r"preview_promotion=false"
)
_RUNTIME_FAILURE = re.compile(
    r"chrono runtime failed closed\s+"
    r"mode=(?P<mode>\S+)\s+reason=(?P<reason>.*?)\s+"
    r"preview_promotion=false"
)


class ValidationFailure(RuntimeError):
    """A requested physical validation gate failed."""

    def __init__(
        self, code: str, message: str, *, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class ValidationBlocked(RuntimeError):
    """External phone state prevents validation from starting."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CommandResult:
    arguments: tuple[str, ...]
    returncode: int
    stdout: bytes

    @property
    def text(self) -> str:
        return self.stdout.decode("utf-8", "replace")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", value.upper())


def nearest_rank(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))
    return ordered[index]


def run_command(
    arguments: Sequence[str | Path],
    *,
    timeout: float = 30.0,
    check: bool = True,
) -> CommandResult:
    command = tuple(str(argument) for argument in arguments)
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    result = CommandResult(command, completed.returncode, completed.stdout)
    if check and result.returncode != 0:
        message = result.text.strip() or f"command exited {result.returncode}"
        raise ValidationFailure("COMMAND_FAILED", message)
    return result


def find_adb(explicit: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    discovered = shutil.which("adb")
    if discovered:
        candidates.append(Path(discovered))
    for name in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        value = os.environ.get(name)
        if value:
            candidates.append(Path(value) / "platform-tools" / "adb.exe")
            candidates.append(Path(value) / "platform-tools" / "adb")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(
            Path(local) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
        )
    candidates.extend(
        (
            Path.home()
            / "AppData"
            / "Local"
            / "Android"
            / "Sdk"
            / "platform-tools"
            / "adb.exe",
            Path.home() / "Android" / "Sdk" / "platform-tools" / "adb",
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise ValidationBlocked(
        "ADB_NOT_FOUND",
        "ADB was not found; install Android platform-tools or pass --adb.",
    )


def parse_adb_devices(output: str) -> tuple[dict[str, str], ...]:
    devices: list[dict[str, str]] = []
    for line in str(output).splitlines():
        stripped = line.strip()
        if (
            not stripped
            or stripped.startswith("List of devices")
            or stripped.startswith("*")
        ):
            continue
        match = _DEVICE_LINE.fullmatch(stripped)
        if match is None:
            continue
        attributes = {
            key: value
            for field in match.group("tail").split()
            if ":" in field
            for key, value in (field.split(":", 1),)
        }
        devices.append(
            {
                "serial": match.group("serial"),
                "state": match.group("state"),
                "model": attributes.get("model", "").replace("_", " "),
                "product": attributes.get("product", ""),
                "device": attributes.get("device", ""),
                "transport_id": attributes.get("transport_id", ""),
            }
        )
    return tuple(devices)


def choose_device(
    devices: Sequence[dict[str, str]], serial: str | None
) -> dict[str, str]:
    if serial:
        matches = tuple(device for device in devices if device["serial"] == serial)
        if not matches:
            raise ValidationBlocked(
                "DEVICE_NOT_CONNECTED", f"ADB device is not connected: {serial}"
            )
        selected = matches[0]
        if selected["state"] == "unauthorized":
            raise ValidationBlocked(
                "DEVICE_UNAUTHORIZED",
                "Unlock the phone and accept the USB-debugging authorization prompt.",
            )
        if selected["state"] != "device":
            raise ValidationBlocked(
                "DEVICE_NOT_READY",
                f"ADB device {serial} is in state {selected['state']}.",
            )
        return selected
    ready = tuple(device for device in devices if device["state"] == "device")
    if len(ready) == 1:
        return ready[0]
    if len(ready) > 1:
        raise ValidationBlocked(
            "MULTIPLE_DEVICES",
            "Multiple authorized devices are connected; pass --serial.",
        )
    if any(device["state"] == "unauthorized" for device in devices):
        raise ValidationBlocked(
            "DEVICE_UNAUTHORIZED",
            "Unlock the phone and accept the USB-debugging authorization prompt.",
        )
    raise ValidationBlocked(
        "NO_ADB_DEVICE",
        "No authorized Android device is attached.",
    )


def parse_getprop(output: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in str(output).splitlines():
        match = _GETPROP_LINE.fullmatch(line.strip())
        if match is not None:
            result[match.group("key")] = match.group("value")
    return result


def is_poco_x7_pro(properties: dict[str, str]) -> bool:
    expected = normalized_name(EXPECTED_MARKET_NAME)
    if any(expected in normalized_name(value) for value in properties.values()):
        return True
    model = normalized_name(properties.get("ro.product.model", ""))
    device = normalized_name(properties.get("ro.product.device", ""))
    return model == normalized_name(
        EXPECTED_TARGET_MODEL
    ) and device == normalized_name(EXPECTED_TARGET_DEVICE)


def parse_remote_sha256(output: str) -> str | None:
    match = _REMOTE_HASH.search(str(output))
    return None if match is None else match.group(1).lower()


def filter_logcat_since(output: str, start_epoch: float) -> str:
    retained: list[str] = []
    for line in str(output).splitlines():
        match = _LOGCAT_EPOCH.match(line)
        if match is None:
            continue
        if float(match.group("epoch")) >= start_epoch:
            retained.append(line)
    return "\n".join(retained) + ("\n" if retained else "")


def parse_png_header(data: bytes) -> dict[str, int]:
    if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValidationFailure("SCREENSHOT_NOT_PNG", "ADB screencap was not a PNG.")
    length = struct.unpack(">I", data[8:12])[0]
    if length != 13 or data[12:16] != b"IHDR":
        raise ValidationFailure(
            "SCREENSHOT_BAD_IHDR", "PNG IHDR is missing or malformed."
        )
    width, height = struct.unpack(">II", data[16:24])
    if width < 1 or height < 1:
        raise ValidationFailure("SCREENSHOT_EMPTY", "PNG dimensions are zero.")
    return {"width": width, "height": height, "bytes": len(data)}


def surface_layer_candidates(output: str, application_id: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for line in str(output).splitlines():
        if application_id not in line:
            continue
        candidate = line.strip()
        if candidate.startswith("RequestedLayerState{") and candidate.endswith("}"):
            candidate = candidate[len("RequestedLayerState{") : -1].strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return tuple(reversed(candidates))


def parse_completion_receipt(log_output: str) -> dict[str, Any] | None:
    matches = tuple(_COMPLETION_RECEIPT.finditer(str(log_output)))
    if not matches:
        return None
    values = matches[-1].groupdict()
    return {
        "mode": values["mode"],
        "entries": int(values["entries"]),
        "published_ordinal": int(values["published"]),
        "staged": int(values["staged"]),
        "late_boundaries": int(values["late"]),
        "selector_boundaries_met": values["selector"] == "true",
        "catchup_drops": int(values["drops"]),
        "photon_time_claim": values["photon"] == "true",
        "color_byte_authoritative": values["color"] == "true",
    }


def parse_chrono_startup_failure(log_output: str) -> dict[str, Any] | None:
    text = str(log_output)
    for phase, expression in (
        ("initialization", _INITIALIZATION_FAILURE),
        ("runtime", _RUNTIME_FAILURE),
    ):
        matches = tuple(expression.finditer(text))
        if matches:
            match = matches[-1]
            line = next(
                (
                    candidate.strip()
                    for candidate in text.splitlines()
                    if match.group(0) in candidate
                ),
                match.group(0),
            )
            return {
                "fail_closed": True,
                "phase": phase,
                "mode": match.group("mode"),
                "reason": match.group("reason").strip(),
                "log_line": line,
                "preview_promotion": False,
            }
    if "chrono_video=FAILED_CLOSED" in text:
        line = next(
            line.strip()
            for line in text.splitlines()
            if "chrono_video=FAILED_CLOSED" in line
        )
        return {
            "fail_closed": True,
            "phase": "renderer",
            "mode": "FAILED_CLOSED",
            "reason": "renderer reported FAILED_CLOSED without the preceding native reason",
            "log_line": line,
            "preview_promotion": False,
        }
    return None


def evaluate_chrono_log(log_output: str, expected_entries: int) -> dict[str, Any]:
    text = str(log_output)
    receipt = parse_completion_receipt(text)
    required_patterns = {
        "lut_parsed": r"UGCVLUT1 verified: .*authority=derived_cache",
        "lut_uploaded": r"UGCVLUT1 uploaded to GLES3: .*authority=derived_cache",
        "two_owned_staging_slots": (
            r"chrono owned staging rasters=2 .*prefetch=exactly_one_verified_ordinal"
        ),
        "source_runtime_mode": (
            r"chrono runtime mode=AUTHORITATIVE_SOURCE_LUT .*"
            r"authority=source_observation .*LUT_reapplication=Q8_EXACT_ADDRESS_MATH"
        ),
        "timeline_decoder": (
            rf"chrono decoder initialized mode=AUTHORITATIVE_SOURCE_LUT .*"
            rf"entries={expected_entries}\s+clock=UGCVPTS1_half_open"
        ),
        "poco_mali_runtime": (
            r"(?i)UGTS-KC 3\.9\.2 profile=poco_x7_pro_12gb .*gpu=.*mali-g720"
        ),
        "clock_anchored_after_ordinal_zero": (
            r"chrono exact playback clock anchored after staged ordinal zero"
        ),
        "all_inputs_queued": rf"chrono decoder input EOS ordinals={expected_entries}\b",
        "all_outputs_validated": (
            rf"chrono decoder output EOS (?:validated_frames={expected_entries}\b|"
            rf"accompanied final ordinal={expected_entries - 1}\b)"
        ),
        "staged_source_pts": (
            r"chrono staged frame count=\d+ media_ordinal=\d+ source_frame=\d+ "
            r"source_pts=-?\d+ surface_timestamp_ns=-?\d+ "
            r"mode=AUTHORITATIVE_SOURCE_LUT"
        ),
        "half_open_publish": r"chrono half-open publish target=\d+ slot=[01]",
    }
    checks = {
        name: bool(re.search(pattern, text))
        for name, pattern in required_patterns.items()
    }
    tag_error_lines = tuple(
        line
        for line in text.splitlines()
        if re.search(r"(?:^|\s)E[/ ]UGTS-KC392(?:\(|:|\s)", line)
    )
    explicit_failures = tuple(
        line
        for line in text.splitlines()
        if "chrono initialization failed closed" in line
        or "chrono runtime failed closed" in line
        or "chrono SurfaceTexture callback arrived while a frame was already pending"
        in line
        or "chrono late half-open boundary" in line
    )

    receipt_ok = bool(
        receipt is not None
        and receipt["mode"] == EXPECTED_MODE
        and receipt["entries"] == expected_entries
        and receipt["published_ordinal"] == expected_entries - 1
        and receipt["staged"] == expected_entries
        and receipt["late_boundaries"] == 0
        and receipt["selector_boundaries_met"] is True
        and receipt["catchup_drops"] == 0
        and receipt["photon_time_claim"] is False
        and receipt["color_byte_authoritative"] is False
    )
    return {
        "passed": all(checks.values())
        and receipt_ok
        and not explicit_failures
        and not tag_error_lines,
        "required_log_checks": checks,
        "completion_receipt": receipt,
        "completion_receipt_exact": receipt_ok,
        "explicit_failure_lines": list(explicit_failures),
        "tag_error_lines": list(tag_error_lines),
        "nonclaims": {
            "photon_time": False,
            "color_byte_authoritative": False,
        },
    }


def discover_build_report(apk: Path) -> Path:
    for directory in apk.parents:
        candidate = directory / "build-report.json"
        if candidate.is_file():
            return candidate
    raise ValidationFailure(
        "BUILD_REPORT_MISSING",
        "No build-report.json was found above the APK; asset-ledger verification is unavailable.",
    )


def audit_apk(
    apk: str | Path,
    *,
    expected_sha256: str | None = None,
    build_report_path: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(apk).resolve()
    if not path.is_file():
        raise ValidationFailure("APK_MISSING", f"APK does not exist: {path}")
    actual_sha = sha256_file(path)
    if expected_sha256 is not None:
        expected = expected_sha256.lower()
        if not _HEX_SHA256.fullmatch(expected):
            raise ValidationFailure(
                "EXPECTED_APK_SHA_INVALID",
                "--expected-apk-sha256 must be 64 hexadecimal digits.",
            )
        if actual_sha != expected:
            raise ValidationFailure(
                "APK_HASH_MISMATCH",
                f"APK SHA-256 {actual_sha} does not match expected {expected}.",
            )
    report_path = (
        Path(build_report_path).resolve()
        if build_report_path is not None
        else discover_build_report(path)
    )
    try:
        build_report = json.loads(report_path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValidationFailure("BUILD_REPORT_INVALID", str(error)) from error
    binding = build_report.get("chrono_runtime_binding")
    if not isinstance(binding, dict) or binding.get("present") is not True:
        raise ValidationFailure(
            "CHRONO_BINDING_MISSING",
            "Build report has no active chrono runtime binding.",
        )
    ledger = build_report.get("chrono_video_assets")
    if not isinstance(ledger, list) or not ledger:
        raise ValidationFailure(
            "CHRONO_LEDGER_MISSING", "Chrono asset ledger is absent."
        )

    checked_assets: list[dict[str, Any]] = []
    mismatches: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        for item in ledger:
            relative = item.get("path") if isinstance(item, dict) else None
            if not isinstance(relative, str):
                mismatches.append("ledger entry has no path")
                continue
            archive_path = f"assets/{relative}"
            if archive_path not in names:
                mismatches.append(f"missing {archive_path}")
                continue
            data = archive.read(archive_path)
            actual = sha256_bytes(data)
            expected_asset_sha = str(item.get("sha256", "")).lower()
            expected_bytes = item.get("bytes")
            if actual != expected_asset_sha or len(data) != expected_bytes:
                mismatches.append(f"ledger mismatch {archive_path}")
            checked_assets.append(
                {
                    "path": archive_path,
                    "bytes": len(data),
                    "sha256": actual,
                    "zip_method": archive.getinfo(archive_path).compress_type,
                }
            )
        required = (
            "assets/chrono/source_media.mp4",
            "assets/chrono/source_timeline.ugcvpts1",
            "assets/chrono/source_timeline_inspection.json",
            "assets/chrono/polar_lut.ugcv1",
            "assets/chrono/manifest.json",
        )
        for archive_path in required:
            if archive_path not in names:
                mismatches.append(f"required asset missing {archive_path}")
        for archive_path in (
            "assets/chrono/source_media.mp4",
            "assets/chrono/polar_preview.mp4",
        ):
            if (
                archive_path in names
                and archive.getinfo(archive_path).compress_type != zipfile.ZIP_STORED
            ):
                mismatches.append(f"MediaCodec fd asset is compressed: {archive_path}")
        native_libraries = sorted(
            name for name in names if name.startswith("lib/") and name.endswith(".so")
        )
        if native_libraries != ["lib/arm64-v8a/libugts_kc_native.so"]:
            mismatches.append(f"unexpected native library set: {native_libraries!r}")
        native_receipt_present = False
        if native_libraries == ["lib/arm64-v8a/libugts_kc_native.so"]:
            native_receipt_present = (
                b"chrono once completion receipt mode=%s entries=%zu"
                in archive.read(native_libraries[0])
            )
            if not native_receipt_present:
                mismatches.append(
                    "native library has no positive ONCE completion receipt"
                )
        try:
            inspection = json.loads(
                archive.read("assets/chrono/source_timeline_inspection.json")
            )
        except (KeyError, UnicodeError, json.JSONDecodeError) as error:
            raise ValidationFailure(
                "TIMELINE_INSPECTION_INVALID", str(error)
            ) from error

    expected_timeline = {
        "magic": "UGCVPTS1",
        "media_role": "ORIGINAL_SOURCE",
        "raster_mode": "APPLY_UGCVLUT1_Q8",
        "playback_mode": "ONCE_HOLD_LAST",
    }
    for key, expected_value in expected_timeline.items():
        if inspection.get(key) != expected_value:
            mismatches.append(
                f"source timeline {key}={inspection.get(key)!r}, expected {expected_value!r}"
            )
    entries = inspection.get("entry_count")
    if not isinstance(entries, int) or entries < 1:
        mismatches.append("source timeline entry_count is invalid")
    manifest_items = tuple(
        item for item in checked_assets if item["path"] == "assets/chrono/manifest.json"
    )
    if (
        not manifest_items
        or manifest_items[0]["sha256"]
        != str(binding.get("manifest_sha256", "")).lower()
    ):
        mismatches.append("embedded manifest SHA-256 disagrees with runtime binding")
    if mismatches:
        raise ValidationFailure("APK_STATIC_AUDIT_FAILED", "; ".join(mismatches))

    output_metadata: dict[str, Any] | None = None
    metadata_path = path.parent / "output-metadata.json"
    if metadata_path.is_file():
        try:
            output_metadata = json.loads(metadata_path.read_text("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValidationFailure("OUTPUT_METADATA_INVALID", str(error)) from error
        if output_metadata.get("applicationId") != EXPECTED_APPLICATION_ID:
            raise ValidationFailure(
                "APPLICATION_ID_MISMATCH",
                "Gradle output metadata does not name the expected POCO application id.",
            )

    return {
        "passed": True,
        "apk": str(path),
        "bytes": path.stat().st_size,
        "sha256": actual_sha,
        "expected_sha256": expected_sha256.lower() if expected_sha256 else None,
        "build_report": str(report_path),
        "build_report_sha256": sha256_file(report_path),
        "application_id": EXPECTED_APPLICATION_ID,
        "activity": EXPECTED_ACTIVITY,
        "chrono_asset_count": len(checked_assets),
        "chrono_asset_bytes": sum(item["bytes"] for item in checked_assets),
        "manifest_sha256": binding["manifest_sha256"],
        "source_timeline": inspection,
        "expected_entries": entries,
        "native_libraries": native_libraries,
        "native_completion_receipt_present": native_receipt_present,
        "output_metadata_present": output_metadata is not None,
    }


class AdbSession:
    def __init__(self, adb: Path, serial: str) -> None:
        self.adb = adb
        self.serial = serial

    def run(
        self,
        *arguments: str | Path,
        timeout: float = 30.0,
        check: bool = True,
    ) -> CommandResult:
        return run_command(
            (self.adb, "-s", self.serial, *arguments),
            timeout=timeout,
            check=check,
        )

    def text(
        self,
        *arguments: str | Path,
        timeout: float = 30.0,
        check: bool = True,
    ) -> str:
        return self.run(*arguments, timeout=timeout, check=check).text


class EvidenceDirectory:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        if self.path.exists():
            if not self.path.is_dir() or any(self.path.iterdir()):
                raise ValidationFailure(
                    "OUTPUT_NOT_EMPTY",
                    f"Evidence output must be absent or empty: {self.path}",
                )
        else:
            self.path.mkdir(parents=True)

    def write_bytes(self, relative: str, data: bytes) -> Path:
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise ValidationFailure(
                "EVIDENCE_OVERWRITE", f"Refusing to overwrite {target}"
            )
        target.write_bytes(data)
        return target

    def write_text(self, relative: str, text: str) -> Path:
        return self.write_bytes(relative, text.encode("utf-8"))

    def write_json(self, relative: str, value: Any) -> Path:
        return self.write_text(
            relative, json.dumps(value, indent=2, sort_keys=True) + "\n"
        )

    def artifact_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.path.rglob("*")):
            if not path.is_file() or path.name in {"report.json", "SHA256SUMS.txt"}:
                continue
            records.append(
                {
                    "path": path.relative_to(self.path).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        return records

    def finalize(self, report: dict[str, Any]) -> None:
        report["completed_utc"] = utc_now()
        report["artifacts"] = self.artifact_records()
        self.write_json("report.json", report)
        lines = []
        for path in sorted(self.path.rglob("*")):
            if path.is_file() and path.name != "SHA256SUMS.txt":
                lines.append(
                    f"{sha256_file(path)}  {path.relative_to(self.path).as_posix()}"
                )
        self.write_text("SHA256SUMS.txt", "\n".join(lines) + "\n")


def _parse_package_paths(output: str, application_id: str) -> tuple[str, ...]:
    prefix = "package:"
    paths = tuple(
        line[len(prefix) :].strip()
        for line in str(output).splitlines()
        if line.startswith(prefix)
    )
    if not paths:
        raise ValidationFailure(
            "INSTALLED_PACKAGE_MISSING",
            f"pm path returned no APK for {application_id}.",
        )
    if len(paths) != 1 or not paths[0].endswith("/base.apk"):
        raise ValidationFailure(
            "INSTALLED_PACKAGE_SPLIT",
            f"Expected one base.apk, got {paths!r}.",
        )
    if any("\x00" in path or "\n" in path or "\r" in path for path in paths):
        raise ValidationFailure(
            "INSTALLED_PATH_INVALID", "Installed APK path is malformed."
        )
    return paths


def install_and_verify(
    session: AdbSession,
    apk: Path,
    apk_sha256: str,
    evidence: EvidenceDirectory,
) -> dict[str, Any]:
    install = session.run("install", "-r", "-g", apk, timeout=240.0, check=False)
    evidence.write_bytes("install.txt", install.stdout)
    if install.returncode != 0 or not re.search(r"(?m)^Success\s*$", install.text):
        raise ValidationFailure("INSTALL_FAILED", install.text.strip())

    pm_output = session.text("shell", "pm", "path", EXPECTED_APPLICATION_ID)
    evidence.write_text("pm_paths.txt", pm_output)
    paths = _parse_package_paths(pm_output, EXPECTED_APPLICATION_ID)
    remote = paths[0]
    remote_sha: str | None = None
    hash_method: str | None = None
    hash_outputs: list[str] = []
    for command in (("sha256sum", remote), ("toybox", "sha256sum", remote)):
        result = session.run("shell", *command, check=False)
        hash_outputs.append(result.text)
        candidate = parse_remote_sha256(result.text) if result.returncode == 0 else None
        if candidate:
            remote_sha = candidate
            hash_method = "device_" + "_".join(command[:-1])
            break
    evidence.write_text("installed_sha256_commands.txt", "\n".join(hash_outputs))
    if remote_sha is not None and remote_sha != apk_sha256:
        raise ValidationFailure(
            "INSTALLED_APK_HASH_MISMATCH",
            f"Device base.apk SHA-256 {remote_sha} does not match local {apk_sha256}.",
        )

    pulled = evidence.path / "installed_base.apk"
    pull_result = session.run("pull", remote, pulled, timeout=240.0, check=False)
    evidence.write_bytes("installed_pull.txt", pull_result.stdout)
    pulled_sha: str | None = None
    if pull_result.returncode == 0 and pulled.is_file():
        pulled_sha = sha256_file(pulled)
        if pulled_sha != apk_sha256:
            raise ValidationFailure(
                "PULLED_APK_HASH_MISMATCH",
                f"Pulled base.apk SHA-256 {pulled_sha} does not match local {apk_sha256}.",
            )
        hash_method = (
            "adb_pull_sha256" if hash_method is None else hash_method + "+adb_pull"
        )
    elif remote_sha is None:
        raise ValidationFailure(
            "INSTALLED_APK_UNVERIFIED",
            "Neither on-device sha256sum nor adb pull could verify installed base.apk bytes.",
        )

    package_dump = session.text("shell", "dumpsys", "package", EXPECTED_APPLICATION_ID)
    evidence.write_text("package_dump.txt", package_dump)
    return {
        "passed": True,
        "install_reported_success": True,
        "remote_base_apk": remote,
        "local_sha256": apk_sha256,
        "device_sha256": remote_sha,
        "pulled_sha256": pulled_sha,
        "verification_method": hash_method,
        "pulled": pulled_sha is not None,
    }


def _resolve_activity(session: AdbSession, evidence: EvidenceDirectory) -> str:
    result = session.text(
        "shell",
        "cmd",
        "package",
        "resolve-activity",
        "--brief",
        "--user",
        "current",
        "-a",
        "android.intent.action.MAIN",
        "-c",
        "android.intent.category.LAUNCHER",
        EXPECTED_APPLICATION_ID,
    )
    evidence.write_text("activity_resolve.txt", result)
    expected = f"{EXPECTED_APPLICATION_ID}/{EXPECTED_ACTIVITY}"
    components = tuple(
        line.strip()
        for line in result.splitlines()
        if "/" in line and not line.startswith("priority=")
    )
    if expected not in components:
        raise ValidationFailure(
            "LAUNCH_ACTIVITY_MISMATCH",
            f"Resolved launcher does not include exact component {expected}: {components!r}",
        )
    return expected


def _device_epoch(session: AdbSession) -> float:
    output = session.text("shell", "date", "+%s").strip()
    if not re.fullmatch(r"\d{9,}", output):
        raise ValidationFailure(
            "DEVICE_CLOCK_UNREADABLE", f"Unexpected device date: {output!r}"
        )
    return float(output)


def _wait_for_pid(session: AdbSession, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        output = session.text(
            "shell", "pidof", EXPECTED_APPLICATION_ID, check=False
        ).strip()
        if re.fullmatch(r"\d+", output):
            return int(output)
        time.sleep(0.2)
    raise ValidationFailure(
        "PROCESS_NOT_STARTED", "The launched app never exposed one PID."
    )


def _engine_log(session: AdbSession, pid: int) -> str:
    return session.text(
        "logcat",
        f"--pid={pid}",
        "-d",
        "-v",
        "epoch",
        "-s",
        "UGTS-KC392:V",
        "*:S",
        check=False,
    )


def _discover_surface_layer(
    session: AdbSession,
    evidence: EvidenceDirectory,
) -> tuple[str, int, tuple[float, ...]]:
    listing = session.text("shell", "dumpsys", "SurfaceFlinger", "--list")
    evidence.write_text("surfaceflinger_layers.txt", listing)
    candidates = surface_layer_candidates(listing, EXPECTED_APPLICATION_ID)
    for candidate in candidates:
        latency = session.text(
            "shell",
            "dumpsys",
            "SurfaceFlinger",
            "--latency",
            candidate,
            check=False,
        )
        try:
            period, intervals = parse_surfaceflinger_latency(latency)
        except ValueError:
            continue
        if intervals:
            return candidate, period, intervals
    raise ValidationFailure(
        "SURFACE_LAYER_MISSING",
        f"No active SurfaceFlinger layer was found among {candidates!r}.",
    )


def _snapshot(
    session: AdbSession,
    pid: int,
    index: int,
    previous_cpu: tuple[int, int, int] | None,
    evidence: EvidenceDirectory,
) -> tuple[dict[str, Any], tuple[int, int, int] | None]:
    outputs = {
        "meminfo": session.text(
            "shell", "dumpsys", "meminfo", EXPECTED_APPLICATION_ID, check=False
        ),
        "thermal": session.text("shell", "dumpsys", "thermalservice", check=False),
        "battery": session.text("shell", "dumpsys", "battery", check=False),
        "proc_stat": session.text("shell", "cat", "/proc/stat", check=False),
        "proc_pid_stat": session.text("shell", "cat", f"/proc/{pid}/stat", check=False),
    }
    for name, output in outputs.items():
        evidence.write_text(f"samples/{index:03d}_{name}.txt", output)
    memory = _parse_meminfo(outputs["meminfo"])
    status, gpu = _parse_thermal(outputs["thermal"])
    battery_level, battery_c = _parse_battery(outputs["battery"])
    cpu = _parse_cpu_ticks(outputs["proc_stat"], outputs["proc_pid_stat"])
    cpu_delta = _cpu_tick_delta(previous_cpu, cpu) if previous_cpu and cpu else None
    return (
        {
            "index": index,
            "captured_utc": utc_now(),
            "pss_kib": memory[0] if memory else None,
            "rss_kib": memory[1] if memory else None,
            "thermal_status": status,
            "gpu_c": gpu,
            "battery_level": battery_level,
            "battery_c": battery_c,
            "cpu_total_capacity_pct": cpu_delta[0] if cpu_delta else None,
            "cpu_one_core_pct": cpu_delta[1] if cpu_delta else None,
            "cpu_logical_cores": cpu[2] if cpu else None,
        },
        cpu,
    )


def launch_and_profile(
    session: AdbSession,
    evidence: EvidenceDirectory,
    *,
    expected_entries: int,
    seconds: float,
    sample_seconds: float,
    startup_timeout: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    component = _resolve_activity(session, evidence)
    power = session.text("shell", "dumpsys", "power", check=False)
    window_policy = session.text("shell", "dumpsys", "window", "policy", check=False)
    evidence.write_text("prelaunch_power.txt", power)
    evidence.write_text("prelaunch_window_policy.txt", window_policy)
    launch_epoch = _device_epoch(session)
    session.text("shell", "am", "force-stop", EXPECTED_APPLICATION_ID)
    launch = session.run(
        "shell",
        "am",
        "start",
        "-W",
        "--user",
        "current",
        "-n",
        component,
        timeout=60.0,
        check=False,
    )
    evidence.write_bytes("launch.txt", launch.stdout)
    if launch.returncode != 0 or not re.search(
        r"(?im)^\s*Status:\s*ok\s*$", launch.text
    ):
        raise ValidationFailure("COLD_LAUNCH_FAILED", launch.text.strip())
    pid = _wait_for_pid(session, startup_timeout)

    deadline = time.monotonic() + startup_timeout
    initial_log = ""
    while time.monotonic() < deadline:
        initial_log = _engine_log(session, pid)
        if "chrono decoder initialized mode=AUTHORITATIVE_SOURCE_LUT" in initial_log:
            break
        if parse_chrono_startup_failure(initial_log) is not None:
            break
        time.sleep(0.25)
    if "chrono decoder initialized mode=AUTHORITATIVE_SOURCE_LUT" not in initial_log:
        evidence.write_text("engine_log_startup.txt", initial_log)
        startup_failure = parse_chrono_startup_failure(initial_log)
        if startup_failure is not None:
            evidence.write_json("chrono_startup_failure.json", startup_failure)
            code = (
                "CHRONO_INITIALIZATION_FAILED_CLOSED"
                if startup_failure["phase"] == "initialization"
                else "CHRONO_RUNTIME_FAILED_CLOSED"
            )
            raise ValidationFailure(
                code,
                str(startup_failure["reason"]),
                details=startup_failure,
            )
        raise ValidationFailure(
            "CHRONO_STARTUP_TIMEOUT",
            "Source-mode decoder initialization was not logged before timeout.",
        )

    activities = session.text("shell", "dumpsys", "activity", "activities", check=False)
    evidence.write_text("foreground_activity.txt", activities)
    foreground_lines = tuple(
        line
        for line in activities.splitlines()
        if EXPECTED_APPLICATION_ID in line
        and EXPECTED_ACTIVITY in line
        and re.search(r"(?i)(?:resumedactivity|focusedapp)", line)
    )
    if not foreground_lines:
        raise ValidationFailure(
            "APP_NOT_FOREGROUND",
            "The exact chrono activity is not reported as resumed or focused.",
        )

    time.sleep(0.5)
    layer, initial_period, initial_intervals = _discover_surface_layer(
        session, evidence
    )
    session.text("shell", "dumpsys", "SurfaceFlinger", "--latency-clear", check=False)

    intervals: list[float] = []
    periods: list[int] = []
    snapshots: list[dict[str, Any]] = []
    previous_cpu: tuple[int, int, int] | None = None
    screenshot: dict[str, Any] | None = None
    remaining = seconds
    sample_count = max(1, math.ceil(seconds / sample_seconds))
    for index in range(sample_count + 1):
        snapshot, previous_cpu = _snapshot(session, pid, index, previous_cpu, evidence)
        snapshots.append(snapshot)
        if index == sample_count:
            break
        wait = min(sample_seconds, remaining)
        time.sleep(wait)
        remaining = max(0.0, remaining - wait)
        latency = session.text(
            "shell",
            "dumpsys",
            "SurfaceFlinger",
            "--latency",
            layer,
            check=False,
        )
        evidence.write_text(f"samples/{index + 1:03d}_surface_latency.txt", latency)
        try:
            period, current = parse_surfaceflinger_latency(latency)
        except ValueError:
            period, current = 0, ()
        if period:
            periods.append(period)
            intervals.extend(current)
        session.text(
            "shell", "dumpsys", "SurfaceFlinger", "--latency-clear", check=False
        )
        if screenshot is None and index >= 0:
            capture = session.run("exec-out", "screencap", "-p", timeout=30.0)
            screenshot = parse_png_header(capture.stdout)
            if screenshot["width"] <= screenshot["height"]:
                raise ValidationFailure(
                    "SCREENSHOT_NOT_LANDSCAPE",
                    f"Expected landscape screenshot, got {screenshot['width']}x{screenshot['height']}.",
                )
            evidence.write_bytes("screenshot.png", capture.stdout)

    final_pid = session.text(
        "shell", "pidof", EXPECTED_APPLICATION_ID, check=False
    ).strip()
    if final_pid != str(pid):
        raise ValidationFailure(
            "PROCESS_RESTARTED", f"PID changed from {pid} to {final_pid!r}."
        )
    engine_log = _engine_log(session, pid)
    engine_log = filter_logcat_since(engine_log, launch_epoch - 1.0)
    evidence.write_text("engine_log.txt", engine_log)
    chrono = evaluate_chrono_log(engine_log, expected_entries)
    evidence.write_json("chrono_log_evaluation.json", chrono)
    if not chrono["passed"]:
        raise ValidationFailure(
            "CHRONO_RECEIPT_FAILED",
            "Native chrono log did not prove all exact source/timeline/staging gates.",
            details=chrono,
        )

    crash_result = session.run(
        "logcat", "-b", "crash", "-d", "-v", "epoch", check=False
    )
    if crash_result.returncode != 0:
        evidence.write_bytes("crash_log_command_error.txt", crash_result.stdout)
        raise ValidationFailure(
            "CRASH_BUFFER_UNREADABLE",
            "ADB could not read Android's crash buffer; zero crashes is unproven.",
        )
    crash_all = crash_result.text
    crashes = filter_logcat_since(crash_all, launch_epoch - 1.0)
    evidence.write_text("crash_log_since_launch.txt", crashes)
    if crashes.strip():
        raise ValidationFailure(
            "POST_LAUNCH_CRASH_LOG", "Crash-buffer entries appeared after cold launch."
        )

    if not periods:
        periods.append(initial_period)
        intervals.extend(initial_intervals)
    if not intervals or not periods:
        raise ValidationFailure(
            "FRAME_CADENCE_MISSING", "SurfaceFlinger yielded no usable frame intervals."
        )
    period_ms = sum(periods) / len(periods) / 1_000_000.0
    mean_ms = sum(intervals) / len(intervals)
    target_fps = 1000.0 / period_ms
    effective_fps = 1000.0 / mean_ms
    p95 = nearest_rank(intervals, 0.95)
    cadence_pass = effective_fps >= target_fps * 0.95 and p95 <= period_ms * 1.5
    if not cadence_pass:
        raise ValidationFailure(
            "FRAME_CADENCE_FAILED",
            f"Effective {effective_fps:.2f} FPS / p95 {p95:.3f} ms did not meet {target_fps:.2f} Hz cadence.",
            details={
                "effective_fps": effective_fps,
                "target_refresh_hz": target_fps,
                "frame_ms_p95": p95,
                "display_period_ms": period_ms,
                "frame_intervals": len(intervals),
            },
        )

    def numeric(field: str) -> list[float]:
        return [float(item[field]) for item in snapshots if item[field] is not None]

    pss = numeric("pss_kib")
    rss = numeric("rss_kib")
    thermal = numeric("thermal_status")
    battery_c = numeric("battery_c")
    gpu_c = numeric("gpu_c")
    cpu_capacity = numeric("cpu_total_capacity_pct")
    cpu_core = numeric("cpu_one_core_pct")
    if not pss:
        raise ValidationFailure(
            "PSS_MISSING", "Android exposed no process PSS samples."
        )
    if thermal and max(thermal) >= 3:
        raise ValidationFailure(
            "THERMAL_PRESSURE", f"Android thermal status reached {int(max(thermal))}."
        )
    gpu_timer = parse_gpu_timer_log(engine_log)
    profile = {
        "passed": True,
        "seconds": seconds,
        "sample_seconds": sample_seconds,
        "samples": snapshots,
        "surface_layer": layer,
        "display_period_ms": round(period_ms, 6),
        "target_refresh_hz": round(target_fps, 3),
        "frame_intervals": len(intervals),
        "effective_fps": round(effective_fps, 3),
        "frame_ms_p50": round(nearest_rank(intervals, 0.50), 6),
        "frame_ms_p95": round(p95, 6),
        "frame_ms_p99": round(nearest_rank(intervals, 0.99), 6),
        "intervals_over_1_5_vsync": sum(value > period_ms * 1.5 for value in intervals),
        "pss_kib_min": int(min(pss)),
        "pss_kib_max": int(max(pss)),
        "rss_kib_min": int(min(rss)) if rss else None,
        "rss_kib_max": int(max(rss)) if rss else None,
        "thermal_status_max": int(max(thermal)) if thermal else None,
        "battery_c_min": min(battery_c) if battery_c else None,
        "battery_c_max": max(battery_c) if battery_c else None,
        "gpu_c_min": min(gpu_c) if gpu_c else None,
        "gpu_c_max": max(gpu_c) if gpu_c else None,
        "cpu_total_capacity_pct_mean": (
            round(sum(cpu_capacity) / len(cpu_capacity), 4) if cpu_capacity else None
        ),
        "cpu_one_core_pct_mean": (
            round(sum(cpu_core) / len(cpu_core), 4) if cpu_core else None
        ),
        "gpu_timer": gpu_timer,
        "crash_buffer_lines_since_launch": 0,
    }
    launch_result = {
        "passed": True,
        "cold_launch": True,
        "component": component,
        "pid": pid,
        "pid_stable": True,
        "foreground": True,
        "foreground_receipt_lines": list(foreground_lines),
        "launch_epoch_device": launch_epoch,
        "screenshot": screenshot,
    }
    return launch_result, chrono, profile


def collect_device_properties(
    session: AdbSession,
    evidence: EvidenceDirectory,
    *,
    allow_non_poco: bool,
) -> dict[str, Any]:
    raw = session.text("shell", "getprop")
    evidence.write_text("device_getprop.txt", raw)
    properties = parse_getprop(raw)
    sdk_text = properties.get("ro.build.version.sdk", "")
    abi = properties.get("ro.product.cpu.abi", "")
    if not sdk_text.isdigit() or int(sdk_text) < 26:
        raise ValidationFailure(
            "DEVICE_SDK_UNSUPPORTED",
            f"Android SDK is {sdk_text!r}; API 26+ is required.",
        )
    if abi != "arm64-v8a":
        raise ValidationFailure(
            "DEVICE_ABI_MISMATCH", f"Primary ABI is {abi!r}, expected arm64-v8a."
        )
    target_match = is_poco_x7_pro(properties)
    if not target_match and not allow_non_poco:
        raise ValidationFailure(
            "DEVICE_NOT_POCO_X7_PRO",
            "No Android product property identifies this phone as POCO X7 Pro; use --allow-non-poco only for an intentional comparison device.",
        )
    return {
        "passed": True,
        "serial": session.serial,
        "manufacturer": properties.get("ro.product.manufacturer"),
        "brand": properties.get("ro.product.brand"),
        "model": properties.get("ro.product.model"),
        "device": properties.get("ro.product.device"),
        "market_names": sorted(
            {
                value
                for key, value in properties.items()
                if value and ("market" in key.lower() or "model" in key.lower())
            }
        ),
        "android_sdk": int(sdk_text),
        "android_release": properties.get("ro.build.version.release"),
        "build_fingerprint": properties.get("ro.build.fingerprint"),
        "primary_abi": abi,
        "target_poco_x7_pro": target_match,
        "comparison_device_override": bool(allow_non_poco and not target_match),
    }


def default_output_directory() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return REPO_ROOT / "validation" / "device" / "chrono_poco" / stamp


def validation_report_skeleton(apk: Path) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "RUNNING",
        "verified_physical_device": False,
        "started_utc": utc_now(),
        "inputs": {"apk": str(apk)},
        "target": {
            "market_name": EXPECTED_MARKET_NAME,
            "application_id": EXPECTED_APPLICATION_ID,
            "activity": EXPECTED_ACTIVITY,
            "abi": "arm64-v8a",
            "runtime_mode": EXPECTED_MODE,
        },
        "gates": {},
        "warnings": [],
        "nonclaims": [
            "A PASS does not claim photon-time display equality.",
            "MediaCodec device YUV-to-RGB conversion is not byte-authoritative.",
            "The log-polar raster is deterministic observed-video evidence, not metric 3D or a hidden-surface reconstruction.",
        ],
    }


def run_validation(args: argparse.Namespace) -> tuple[int, Path, dict[str, Any]]:
    apk = Path(args.apk).resolve()
    output = Path(args.output).resolve() if args.output else default_output_directory()
    evidence = EvidenceDirectory(output)
    report = validation_report_skeleton(apk)
    exit_code = 1
    try:
        static = audit_apk(
            apk,
            expected_sha256=args.expected_apk_sha256,
            build_report_path=args.build_report,
        )
        report["gates"]["static_apk"] = static
        evidence.write_json("static_apk_audit.json", static)
        if args.static_only:
            report["status"] = "PASS_STATIC_ONLY"
            report["verified_physical_device"] = False
            exit_code = 0
        else:
            adb = find_adb(args.adb)
            devices_result = run_command((adb, "devices", "-l"), timeout=15.0)
            evidence.write_bytes("adb_devices.txt", devices_result.stdout)
            devices = parse_adb_devices(devices_result.text)
            selected = choose_device(devices, args.serial)
            session = AdbSession(adb, selected["serial"])
            device = collect_device_properties(
                session, evidence, allow_non_poco=args.allow_non_poco
            )
            report["device"] = device
            report["gates"]["device_identity"] = device
            installed = install_and_verify(session, apk, static["sha256"], evidence)
            report["gates"]["installed_apk"] = installed
            launch, chrono, profile = launch_and_profile(
                session,
                evidence,
                expected_entries=static["expected_entries"],
                seconds=args.seconds,
                sample_seconds=args.sample_seconds,
                startup_timeout=args.startup_timeout,
            )
            report["gates"]["cold_launch"] = launch
            report["gates"]["chrono_native_receipts"] = chrono
            report["gates"]["profile"] = profile
            evidence.write_json("profile.json", profile)
            report["status"] = "PASS_PHYSICAL_POCO_X7_PRO"
            report["verified_physical_device"] = True
            exit_code = 0
    except ValidationBlocked as error:
        report["status"] = "BLOCKED"
        report["verified_physical_device"] = False
        report["blocker"] = {"code": error.code, "message": str(error)}
        exit_code = 2
    except ValidationFailure as error:
        report["status"] = "FAIL"
        report["verified_physical_device"] = False
        report["failure"] = {"code": error.code, "message": str(error)}
        if error.details is not None:
            report["failure"]["details"] = error.details
        exit_code = 1
    except (OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        report["status"] = "ERROR"
        report["verified_physical_device"] = False
        report["failure"] = {
            "code": type(error).__name__.upper(),
            "message": str(error),
        }
        exit_code = 1
    finally:
        evidence.finalize(report)
    return exit_code, evidence.path, report


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Install and fail-closed validate the exact UGTOMS chrono APK on a POCO X7 Pro."
        )
    )
    parser.add_argument("--apk", type=Path, default=DEFAULT_APK)
    parser.add_argument("--expected-apk-sha256")
    parser.add_argument("--build-report", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--adb", type=Path)
    parser.add_argument("--serial")
    parser.add_argument("--seconds", type=float, default=15.0)
    parser.add_argument("--sample-seconds", type=float, default=3.0)
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    parser.add_argument("--allow-non-poco", action="store_true")
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="Audit the APK and ledger without issuing any ADB command.",
    )
    return parser


def validate_arguments(args: argparse.Namespace) -> None:
    if args.serial and not re.fullmatch(r"[A-Za-z0-9._:-]+", args.serial):
        raise ValidationFailure(
            "SERIAL_INVALID", "ADB serial contains unsupported characters."
        )
    if not 10.0 <= args.seconds <= 900.0:
        raise ValidationFailure(
            "DURATION_INVALID", "--seconds must be between 10 and 900."
        )
    if not 1.0 <= args.sample_seconds <= args.seconds:
        raise ValidationFailure(
            "SAMPLE_INTERVAL_INVALID",
            "--sample-seconds must be between 1 and --seconds.",
        )
    if not 5.0 <= args.startup_timeout <= 60.0:
        raise ValidationFailure(
            "STARTUP_TIMEOUT_INVALID", "--startup-timeout must be between 5 and 60."
        )
    if args.expected_apk_sha256 and not _HEX_SHA256.fullmatch(args.expected_apk_sha256):
        raise ValidationFailure(
            "EXPECTED_APK_SHA_INVALID",
            "--expected-apk-sha256 must be 64 hexadecimal digits.",
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    try:
        validate_arguments(args)
        exit_code, output, report = run_validation(args)
    except ValidationFailure as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "schema": SCHEMA,
                "status": report["status"],
                "verified_physical_device": report["verified_physical_device"],
                "evidence_directory": str(output),
                "report": str(output / "report.json"),
            },
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
