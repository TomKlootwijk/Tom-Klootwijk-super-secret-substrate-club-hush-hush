from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidbuild import (
    AndroidDevice,
    parse_surfaceflinger_latency,
    profile_android_app,
)


_APPLICATION_ID = "org.ugts.games.child.pocox7pro"
_LATENCY = "\n".join(
    (
        "8333333",
        "100000000 100100000 100200000",
        "108333333 108433333 108533333",
        "116666666 9223372036854775807 116866666",
        "125000000 125100000 125200000",
    )
)


class AndroidProfileTests(unittest.TestCase):
    def test_latency_parser_ignores_pending_columns_and_keeps_cadence(self) -> None:
        period, intervals = parse_surfaceflinger_latency(_LATENCY)
        self.assertEqual(period, 8_333_333)
        self.assertEqual(len(intervals), 3)
        for interval in intervals:
            self.assertAlmostEqual(interval, 8.333333, places=5)

        with self.assertRaisesRegex(ValueError, "no frame timing"):
            parse_surfaceflinger_latency("")
        with self.assertRaisesRegex(ValueError, "period"):
            parse_surfaceflinger_latency("not-a-period\n1 2 3")

    def test_profile_is_pinned_noninvasive_and_child_readable(self) -> None:
        phone = AndroidDevice("poco-1", "device", "POCO X7 Pro")
        sdk = Path("C:/Android/Sdk")
        adb = sdk / "platform-tools/adb.exe"
        calls: list[tuple[str, ...]] = []

        def fake_adb(_adb: Path, serial: str, *arguments: str, timeout=30.0) -> str:
            self.assertEqual(serial, "poco-1")
            self.assertEqual(_adb, adb)
            self.assertGreater(timeout, 0)
            calls.append(arguments)
            joined = " ".join(arguments)
            if "pidof" in arguments:
                return "123\n"
            if "SurfaceFlinger --list" in joined:
                return (
                    f"RequestedLayerState{{ {_APPLICATION_ID}/android.app.NativeActivity#41 }}\n"
                    f"{_APPLICATION_ID}/android.app.NativeActivity#42\n"
                )
            if "SurfaceFlinger --latency " in joined:
                self.assertTrue(joined.endswith("NativeActivity#42"))
                return _LATENCY
            if "SurfaceFlinger --latency-clear" in joined:
                return ""
            if "dumpsys meminfo" in joined:
                return "TOTAL PSS: 133713 TOTAL RSS: 254002\n"
            if "dumpsys thermalservice" in joined:
                return "\n".join(
                    (
                        "Thermal Status: 0",
                        "Current temperatures from HAL:",
                        "Temperature{mValue=49.5, mType=1, mName=GPU, mStatus=0}",
                        "Current cooling devices from HAL:",
                    )
                )
            if "dumpsys battery" in joined:
                return "level: 81\ntemperature: 360\n"
            if "logcat" in arguments:
                return ""
            self.fail(f"unexpected ADB call: {arguments!r}")

        with (
            patch("ugts_kc3.androidbuild._find_sdk_root", return_value=sdk),
            patch("ugts_kc3.androidbuild._find_adb", return_value=adb),
            patch("ugts_kc3.androidbuild.list_android_devices", return_value=(phone,)),
            patch("ugts_kc3.androidbuild._adb_text", side_effect=fake_adb),
            patch("ugts_kc3.androidbuild.time.sleep") as sleep,
        ):
            result = profile_android_app(
                _APPLICATION_ID,
                serial="poco-1",
                seconds=5,
                sample_seconds=5,
            )

        sleep.assert_called_once_with(5.0)
        self.assertEqual(result.summary, "Smooth 120 Hz baseline")
        self.assertEqual(result.warnings, ())
        self.assertAlmostEqual(result.effective_fps, 120.0, places=1)
        self.assertEqual(result.frame_intervals, 3)
        self.assertEqual((result.pss_kib_min, result.pss_kib_max), (133713, 133713))
        self.assertEqual(result.gpu_c_max, 49.5)
        self.assertEqual(result.battery_level_start, 81)
        self.assertEqual(result.battery_level_end, 81)
        self.assertEqual(result.crash_buffer_lines, 0)
        self.assertEqual(result.to_dict()["schema"], "ugts-kc-android-profile-1")
        flattened = " ".join(" ".join(call) for call in calls)
        self.assertNotIn(" input ", f" {flattened} ")
        self.assertNotIn(" settings ", f" {flattened} ")
        self.assertNotIn(" am start ", f" {flattened} ")

    def test_profile_bounds_and_missing_process_fail_before_sampling(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 5 and 900"):
            profile_android_app(_APPLICATION_ID, seconds=4)
        with self.assertRaisesRegex(ValueError, "sample interval"):
            profile_android_app(_APPLICATION_ID, seconds=5, sample_seconds=6)
        with self.assertRaisesRegex(ValueError, "invalid Android application"):
            profile_android_app("bad;package", seconds=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
