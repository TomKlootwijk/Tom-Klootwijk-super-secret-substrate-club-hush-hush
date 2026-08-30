from __future__ import annotations

import hashlib
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parent.parent
VALIDATION = ROOT / "validation"
if str(VALIDATION) not in sys.path:
    sys.path.insert(0, str(VALIDATION))

from chrono_poco_validation import (  # noqa: E402
    EXPECTED_ACTIVITY,
    EXPECTED_APPLICATION_ID,
    CommandResult,
    EvidenceDirectory,
    ValidationBlocked,
    ValidationFailure,
    audit_apk,
    choose_device,
    evaluate_chrono_log,
    filter_logcat_since,
    install_and_verify,
    is_poco_x7_pro,
    launch_and_profile,
    parse_adb_devices,
    parse_chrono_startup_failure,
    parse_completion_receipt,
    parse_getprop,
    parse_png_header,
    parse_remote_sha256,
    run_validation,
    surface_layer_candidates,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _completion(entries: int = 229, **overrides: object) -> str:
    values: dict[str, object] = {
        "mode": "AUTHORITATIVE_SOURCE_LUT",
        "entries": entries,
        "published": entries - 1,
        "staged": entries,
        "late": 0,
        "selector": "true",
        "drops": 0,
        "photon": "false",
        "color": "false",
    }
    values.update(overrides)
    return (
        "chrono once completion receipt "
        f"mode={values['mode']} entries={values['entries']} "
        f"published_ordinal={values['published']} staged={values['staged']} "
        f"late_boundaries={values['late']} "
        f"selector_boundaries_met={values['selector']} "
        f"catchup_drops={values['drops']} photon_time_claim={values['photon']} "
        f"color_byte_authoritative={values['color']}"
    )


def _passing_log(entries: int = 229) -> str:
    return "\n".join(
        (
            "I/UGTS-KC392: UGCVLUT1 verified: source=1280x720 polar=1024x512 authority=derived_cache",
            "I/UGTS-KC392: UGCVLUT1 uploaded to GLES3: source=1280x720 polar=1024x512 bytes=4194304 authority=derived_cache",
            "I/UGTS-KC392: chrono owned staging rasters=2 size=1024x512 format=RGBA8 prefetch=exactly_one_verified_ordinal external_filter=NEAREST",
            f"I/UGTS-KC392: chrono decoder initialized mode=AUTHORITATIVE_SOURCE_LUT mime=video/avc media=1280x720 entries={entries} clock=UGCVPTS1_half_open output_gate=one_SurfaceTexture_frame",
            "I/UGTS-KC392: UGTS-KC 3.9.2 profile=poco_x7_pro_12gb grove=x quality=x fps=120 scale=1.00 model=2412DPC0AG gpu=Mali-G720 MC7 ram=12288MB juice=1.00",
            "I/UGTS-KC392: chrono runtime mode=AUTHORITATIVE_SOURCE_LUT playback=ONCE_HOLD_LAST authority=source_observation LUT_reapplication=Q8_EXACT_ADDRESS_MATH orientation=canonical color=device",
            "I/UGTS-KC392: chrono staged frame count=1 media_ordinal=0 source_frame=0 source_pts=0 surface_timestamp_ns=1 mode=AUTHORITATIVE_SOURCE_LUT",
            "I/UGTS-KC392: chrono half-open publish target=0 slot=0 previous_slot=-1",
            "I/UGTS-KC392: chrono exact playback clock anchored after staged ordinal zero",
            f"I/UGTS-KC392: chrono decoder input EOS ordinals={entries}",
            f"I/UGTS-KC392: chrono decoder output EOS validated_frames={entries}",
            _completion(entries),
        )
    )


def _epoch_passing_log(entries: int = 229) -> str:
    return "\n".join(
        f"1693398601.000 123 124 I UGTS-KC392: {line.split(': ', 1)[-1]}"
        for line in _passing_log(entries).splitlines()
    )


def _png(width: int = 2712, height: int = 1220) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct_pack_u32(13)
        + b"IHDR"
        + struct_pack_u32(width)
        + struct_pack_u32(height)
        + b"\x08\x06\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def _write_fixture_apk(
    root: Path, *, compress_source: bool = False
) -> tuple[Path, Path]:
    project = root / "project"
    output = project / "app/build/outputs/apk/pocoX7Pro/debug"
    output.mkdir(parents=True)
    apk = output / "app-pocoX7Pro-debug.apk"
    inspection = json.dumps(
        {
            "magic": "UGCVPTS1",
            "media_role": "ORIGINAL_SOURCE",
            "raster_mode": "APPLY_UGCVLUT1_Q8",
            "playback_mode": "ONCE_HOLD_LAST",
            "entry_count": 229,
        },
        sort_keys=True,
    ).encode()
    assets = {
        "chrono/source_media.mp4": b"source mp4 bytes",
        "chrono/polar_preview.mp4": b"preview mp4 bytes",
        "chrono/source_timeline.ugcvpts1": b"UGCVPTS1 timeline",
        "chrono/source_timeline_inspection.json": inspection,
        "chrono/polar_lut.ugcv1": b"UGCVLUT1 lut",
        "chrono/manifest.json": b'{"schema":"fixture"}\n',
    }
    ledger = [
        {"path": name, "bytes": len(data), "sha256": _sha(data)}
        for name, data in assets.items()
    ]
    manifest_sha = _sha(assets["chrono/manifest.json"])
    (project / "build-report.json").write_text(
        json.dumps(
            {
                "chrono_runtime_binding": {
                    "present": True,
                    "manifest_sha256": manifest_sha,
                },
                "chrono_video_assets": ledger,
            }
        ),
        "utf-8",
    )
    (output / "output-metadata.json").write_text(
        json.dumps({"applicationId": EXPECTED_APPLICATION_ID}), "utf-8"
    )
    with zipfile.ZipFile(apk, "w") as archive:
        for name, data in assets.items():
            method = zipfile.ZIP_STORED
            if name == "chrono/source_media.mp4" and compress_source:
                method = zipfile.ZIP_DEFLATED
            archive.writestr(f"assets/{name}", data, compress_type=method)
        archive.writestr(
            "lib/arm64-v8a/libugts_kc_native.so",
            b"ELF chrono once completion receipt mode=%s entries=%zu",
            compress_type=zipfile.ZIP_STORED,
        )
    return apk, project / "build-report.json"


class ChronoPocoValidationTests(unittest.TestCase):
    def test_positive_completion_receipt_is_required_and_exact(self) -> None:
        log = _passing_log()
        receipt = parse_completion_receipt(log)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(receipt["published_ordinal"], 228)
        self.assertFalse(receipt["photon_time_claim"])
        result = evaluate_chrono_log(log, 229)
        self.assertTrue(result["passed"])
        self.assertTrue(result["completion_receipt_exact"])

        self.assertFalse(
            evaluate_chrono_log(log.replace(_completion(), ""), 229)["passed"]
        )
        self.assertFalse(
            evaluate_chrono_log(
                log.replace(_completion(), _completion(late=1, selector="false")), 229
            )["passed"]
        )
        self.assertFalse(
            evaluate_chrono_log(
                log.replace(_completion(), _completion(photon="true")), 229
            )["passed"]
        )
        self.assertFalse(
            evaluate_chrono_log(
                log + "\nE/UGTS-KC392: chrono runtime failed closed mode=X reason=bad",
                229,
            )["passed"]
        )

    def test_startup_failure_parser_preserves_fail_closed_native_reason(self) -> None:
        log = (
            "1788088769.187 13928 32338 E UGTS-KC392: "
            "chrono initialization failed closed mode=AUTHORITATIVE_SOURCE_LUT "
            "reason=chrono AMediaExtractor rejected the MP4 asset range; "
            "preview_promotion=false\n"
            "1788088769.221 13928 32338 E UGTS-KC392: "
            "chrono_video=FAILED_CLOSED preview_promotion=false\n"
        )
        result = parse_chrono_startup_failure(log)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["fail_closed"])
        self.assertEqual(result["phase"], "initialization")
        self.assertEqual(result["mode"], "AUTHORITATIVE_SOURCE_LUT")
        self.assertEqual(
            result["reason"], "chrono AMediaExtractor rejected the MP4 asset range"
        )
        self.assertFalse(result["preview_promotion"])

    def test_apk_audit_binds_ledger_manifest_abi_and_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            apk, report = _write_fixture_apk(Path(temporary))
            result = audit_apk(
                apk,
                expected_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
                build_report_path=report,
            )
            self.assertTrue(result["passed"])
            self.assertEqual(result["chrono_asset_count"], 6)
            self.assertEqual(result["expected_entries"], 229)
            self.assertEqual(result["activity"], EXPECTED_ACTIVITY)

    def test_apk_audit_rejects_compressed_mediacodec_asset_and_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            apk, report = _write_fixture_apk(Path(temporary), compress_source=True)
            with self.assertRaisesRegex(ValidationFailure, "compressed"):
                audit_apk(apk, build_report_path=report)
            with self.assertRaisesRegex(ValidationFailure, "does not match"):
                audit_apk(apk, expected_sha256="0" * 64, build_report_path=report)

    def test_device_selection_and_identity_are_fail_closed(self) -> None:
        parsed = parse_adb_devices(
            "List of devices attached\n"
            "XOVSTSHYNREMZ5D6 device product:rodin model:2412DPC0AG device:rodin transport_id:4\n"
        )
        selected = choose_device(parsed, None)
        self.assertEqual(selected["serial"], "XOVSTSHYNREMZ5D6")
        props = parse_getprop(
            "[ro.product.model]: [2412DPC0AG]\n"
            "[ro.product.device]: [rodin]\n"
            "[ro.product.cpu.abi]: [arm64-v8a]\n"
        )
        self.assertTrue(is_poco_x7_pro(props))
        self.assertTrue(is_poco_x7_pro({"ro.product.marketname": "POCO X7 Pro"}))
        self.assertFalse(
            is_poco_x7_pro({"ro.product.model": "other", "ro.product.device": "rodin"})
        )
        with self.assertRaisesRegex(ValidationBlocked, "No authorized"):
            choose_device((), None)
        with self.assertRaisesRegex(ValidationBlocked, "authorization"):
            choose_device(({"serial": "x", "state": "unauthorized"},), None)

    def test_parsers_keep_binary_and_time_evidence_strict(self) -> None:
        png = _png()
        self.assertEqual(parse_png_header(png)["width"], 2712)
        with self.assertRaisesRegex(ValidationFailure, "not a PNG"):
            parse_png_header(b"not png")
        self.assertEqual(
            parse_remote_sha256("a" * 64 + "  /data/app/base.apk\n"), "a" * 64
        )
        log = (
            "1693398599.9 1 1 I OLD: old\n"
            "1693398600.0 1 1 I NEW: first\n"
            "1693398601.0 1 1 I NEW: next\n"
        )
        self.assertEqual(filter_logcat_since(log, 1693398600.0).count("NEW"), 2)

    def test_surface_layer_candidates_accept_custom_java_activity(self) -> None:
        listing = "\n".join(
            (
                "unrelated#1",
                f"{EXPECTED_APPLICATION_ID}/{EXPECTED_ACTIVITY}#41",
                f"RequestedLayerState{{ SurfaceView[{EXPECTED_APPLICATION_ID}/{EXPECTED_ACTIVITY}]#42 }}",
            )
        )
        candidates = surface_layer_candidates(listing, EXPECTED_APPLICATION_ID)
        self.assertEqual(len(candidates), 2)
        self.assertIn("SurfaceView", candidates[0])

    def test_evidence_directory_refuses_overwrite_and_hashes_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            evidence = EvidenceDirectory(output)
            evidence.write_text("raw/log.txt", "evidence\n")
            with self.assertRaisesRegex(ValidationFailure, "overwrite"):
                evidence.write_text("raw/log.txt", "replacement\n")
            report = {"schema": "test", "status": "PASS"}
            evidence.finalize(report)
            self.assertTrue((output / "report.json").is_file())
            sums = (output / "SHA256SUMS.txt").read_text("utf-8")
            self.assertIn("report.json", sums)
            self.assertIn("raw/log.txt", sums)

    def test_missing_device_yields_structured_blocked_not_physical_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk, report_path = _write_fixture_apk(root)
            output = root / "blocked_evidence"
            args = argparse.Namespace(
                apk=apk,
                expected_apk_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
                build_report=report_path,
                output=output,
                adb=None,
                serial=None,
                seconds=15.0,
                sample_seconds=3.0,
                startup_timeout=30.0,
                allow_non_poco=False,
                static_only=False,
            )
            with patch(
                "chrono_poco_validation.find_adb",
                side_effect=ValidationBlocked("NO_ADB_DEVICE", "no phone"),
            ):
                exit_code, evidence_path, result = run_validation(args)
            self.assertEqual(exit_code, 2)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertFalse(result["verified_physical_device"])
            self.assertTrue(result["gates"]["static_apk"]["passed"])
            persisted = json.loads((evidence_path / "report.json").read_text("utf-8"))
            self.assertEqual(persisted["blocker"]["code"], "NO_ADB_DEVICE")

    def test_install_path_hash_and_pull_are_bound_to_same_apk(self) -> None:
        class FakeInstallSession:
            serial = "poco-1"

            def run(self, *arguments, timeout=30.0, check=True):
                del timeout, check
                command = tuple(str(value) for value in arguments)
                if command[0] == "install":
                    return CommandResult(
                        command, 0, b"Performing Streamed Install\nSuccess\n"
                    )
                if command[:3] == ("shell", "sha256sum", "/data/app/base.apk"):
                    return CommandResult(
                        command,
                        0,
                        f"{apk_sha}  /data/app/base.apk\n".encode(),
                    )
                if command[0] == "pull":
                    Path(command[2]).write_bytes(apk_bytes)
                    return CommandResult(command, 0, b"1 file pulled\n")
                self.fail(f"unexpected run call: {command!r}")

            def text(self, *arguments, timeout=30.0, check=True):
                del timeout, check
                command = tuple(str(value) for value in arguments)
                if command == ("shell", "pm", "path", EXPECTED_APPLICATION_ID):
                    return "package:/data/app/base.apk\n"
                if command == (
                    "shell",
                    "dumpsys",
                    "package",
                    EXPECTED_APPLICATION_ID,
                ):
                    return f"Package [{EXPECTED_APPLICATION_ID}]\n"
                self.fail(f"unexpected text call: {command!r}")

        apk_bytes = b"exact receipt-bearing apk"
        apk_sha = hashlib.sha256(apk_bytes).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk = root / "app.apk"
            apk.write_bytes(apk_bytes)
            evidence = EvidenceDirectory(root / "evidence")
            result = install_and_verify(
                FakeInstallSession(),
                apk,
                apk_sha,
                evidence,  # type: ignore[arg-type]
            )
            self.assertTrue(result["passed"])
            self.assertEqual(result["device_sha256"], apk_sha)
            self.assertEqual(result["pulled_sha256"], apk_sha)
            self.assertEqual(
                (evidence.path / "installed_base.apk").read_bytes(), apk_bytes
            )

    def test_launch_profile_pipeline_requires_receipts_and_captures_evidence(
        self,
    ) -> None:
        latency = "\n".join(
            (
                "8333333",
                "100000000 100100000 100200000",
                "108333333 108433333 108533333",
                "116666666 116766666 116866666",
                "125000000 125100000 125200000",
            )
        )

        class FakeProfileSession:
            serial = "poco-1"

            def __init__(self) -> None:
                self.calls: list[tuple[str, ...]] = []

            def run(self, *arguments, timeout=30.0, check=True):
                del timeout, check
                command = tuple(str(value) for value in arguments)
                self.calls.append(command)
                if command[:2] == ("exec-out", "screencap"):
                    return CommandResult(command, 0, _png())
                if command[:3] == ("shell", "am", "start"):
                    return CommandResult(
                        command,
                        0,
                        b"Starting: Intent\nStatus: ok\nActivity: activity\n",
                    )
                if command[:3] == ("logcat", "-b", "crash"):
                    return CommandResult(command, 0, b"")
                self.fail(f"unexpected run call: {command!r}")

            def text(self, *arguments, timeout=30.0, check=True):
                del timeout, check
                command = tuple(str(value) for value in arguments)
                self.calls.append(command)
                if command[:4] == (
                    "shell",
                    "cmd",
                    "package",
                    "resolve-activity",
                ):
                    return f"{EXPECTED_APPLICATION_ID}/{EXPECTED_ACTIVITY}\n"
                if command == ("shell", "dumpsys", "power"):
                    return "mWakefulness=Awake\n"
                if command == ("shell", "dumpsys", "window", "policy"):
                    return "interactive=true keyguard=false\n"
                if command == ("shell", "date", "+%s"):
                    return "1693398600\n"
                if command == ("shell", "am", "force-stop", EXPECTED_APPLICATION_ID):
                    return ""
                if command == ("shell", "pidof", EXPECTED_APPLICATION_ID):
                    return "123\n"
                if command[0] == "logcat" and "--pid=123" in command:
                    return _epoch_passing_log() + "\n"
                if command == ("shell", "dumpsys", "activity", "activities"):
                    return (
                        f"mResumedActivity: {EXPECTED_APPLICATION_ID}/"
                        f"{EXPECTED_ACTIVITY}\n"
                    )
                if command == ("shell", "dumpsys", "SurfaceFlinger", "--list"):
                    return f"{EXPECTED_APPLICATION_ID}/{EXPECTED_ACTIVITY}#42\n"
                if command[:4] == (
                    "shell",
                    "dumpsys",
                    "SurfaceFlinger",
                    "--latency",
                ):
                    return latency
                if command == (
                    "shell",
                    "dumpsys",
                    "SurfaceFlinger",
                    "--latency-clear",
                ):
                    return ""
                if command == (
                    "shell",
                    "dumpsys",
                    "meminfo",
                    EXPECTED_APPLICATION_ID,
                ):
                    return "TOTAL PSS: 100000 TOTAL RSS: 150000\n"
                if command == ("shell", "dumpsys", "thermalservice"):
                    return (
                        "Thermal Status: 0\nCurrent temperatures from HAL:\n"
                        "Temperature{mValue=41.0, mType=1, mName=GPU, mStatus=0}\n"
                        "Current cooling devices from HAL:\n"
                    )
                if command == ("shell", "dumpsys", "battery"):
                    return "level: 80\ntemperature: 350\n"
                if command == ("shell", "cat", "/proc/stat"):
                    return "cpu 100 0 0 700 0 0 0 0\ncpu0 10 0 0 90\n"
                if command == ("shell", "cat", "/proc/123/stat"):
                    return "123 (app) " + " ".join(
                        ("S", *("0" for _ in range(10)), "2", "1")
                    )
                self.fail(f"unexpected text call: {command!r}")

        with tempfile.TemporaryDirectory() as temporary:
            evidence = EvidenceDirectory(Path(temporary) / "evidence")
            session = FakeProfileSession()
            with patch("chrono_poco_validation.time.sleep"):
                launch, chrono, profile = launch_and_profile(
                    session,  # type: ignore[arg-type]
                    evidence,
                    expected_entries=229,
                    seconds=10.0,
                    sample_seconds=5.0,
                    startup_timeout=5.0,
                )
            self.assertTrue(launch["passed"])
            self.assertTrue(chrono["passed"])
            self.assertTrue(profile["passed"])
            self.assertEqual(profile["effective_fps"], 120.0)
            self.assertEqual(profile["pss_kib_max"], 100000)
            self.assertTrue((evidence.path / "screenshot.png").is_file())
            self.assertTrue((evidence.path / "engine_log.txt").is_file())
            self.assertTrue((evidence.path / "chrono_log_evaluation.json").is_file())


def struct_pack_u32(value: int) -> bytes:
    return value.to_bytes(4, "big")


if __name__ == "__main__":
    unittest.main(verbosity=2)
