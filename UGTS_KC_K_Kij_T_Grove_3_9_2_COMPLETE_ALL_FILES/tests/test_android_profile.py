from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidbuild import (  # noqa: E402
    AndroidDevice,
    _cpu_tick_delta,
    _parse_cpu_ticks,
    parse_gpu_timer_log,
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
        system_cpu_samples = iter((
            "cpu 1000 0 0 7000 0 0 0 0\n"
            + "\n".join(f"cpu{index} 1 0 0 9" for index in range(8)),
            "cpu 1100 0 0 7700 0 0 0 0\n"
            + "\n".join(f"cpu{index} 1 0 0 9" for index in range(8)),
        ))
        process_cpu_samples = iter((
            "123 (UGTS game) " + " ".join(("S", *("0" for _ in range(10)), "70", "30")),
            "123 (UGTS game) " + " ".join(("S", *("0" for _ in range(10)), "85", "35")),
        ))

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
            if arguments[-2:] == ("cat", "/proc/stat"):
                return next(system_cpu_samples)
            if arguments[-2:] == ("cat", "/proc/123/stat"):
                return next(process_cpu_samples)
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
                if "UGTS-KC392:I" in arguments:
                    self.assertIn("--pid=123", arguments)
                    return (
                        "I/UGTS-KC392: gpu timer supported=true bits=64 "
                        "scope=renderer_start samples=599 "
                        "total_ms=1272.8750 "
                        "mean_ms=2.1250 max_ms=4.5000 last_ms=2.0000 "
                        "disjoint=1 pending=2\n"
                    )
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
        self.assertEqual(result.cpu_logical_cores, 8)
        self.assertEqual(result.cpu_total_capacity_pct_mean, 2.5)
        self.assertEqual(result.cpu_one_core_pct_mean, 20.0)
        self.assertTrue(result.gpu_timer_supported)
        self.assertEqual(result.gpu_timer_counter_bits, 64)
        self.assertEqual(result.gpu_timer_samples_since_renderer_start, 599)
        self.assertEqual(result.gpu_render_ms_total_since_renderer_start, 1272.875)
        self.assertEqual(result.gpu_render_ms_mean_since_renderer_start, 2.125)
        self.assertEqual(result.gpu_render_ms_max_since_renderer_start, 4.5)
        self.assertEqual(result.gpu_timer_disjoint_intervals_since_renderer_start, 1)
        self.assertEqual(result.crash_buffer_lines, 0)
        self.assertEqual(result.to_dict()["schema"], "ugts-kc-android-profile-3")
        flattened = " ".join(" ".join(call) for call in calls)
        self.assertNotIn(" input ", f" {flattened} ")
        self.assertNotIn(" settings ", f" {flattened} ")
        self.assertNotIn(" am start ", f" {flattened} ")

    def test_cpu_ticks_handle_process_names_and_report_both_scales(self) -> None:
        system = "\n".join((
            "cpu 100 20 30 650 0 0 0 0",
            "cpu0 25 5 7 163",
            "cpu1 25 5 8 162",
            "cpu2 25 5 7 163",
            "cpu3 25 5 8 162",
        ))
        process = "77 (name with ) parenthesis) " + " ".join(
            ("S", *("0" for _ in range(10)), "12", "8")
        )
        before = _parse_cpu_ticks(system, process)
        self.assertEqual(before, (800, 20, 4))
        self.assertEqual(_cpu_tick_delta(before, (1000, 30, 4)), (5.0, 20.0))
        self.assertIsNone(_parse_cpu_ticks("garbage", process))

    def test_gpu_timer_parser_reports_measurement_support_or_absence(self) -> None:
        measured = parse_gpu_timer_log(
            "old\n"
            "gpu timer supported=true bits=48 scope=renderer_start samples=120 "
            "total_ms=390.0000 "
            "mean_ms=3.2500 max_ms=8.0000 last_ms=2.7500 disjoint=0 pending=3\n"
        )
        self.assertEqual(
            measured,
            {
                "supported": True,
                "counter_bits": 48,
                "samples_since_renderer_start": 120,
                "total_ms_since_renderer_start": 390.0,
                "mean_ms": 3.25,
                "max_ms": 8.0,
                "last_ms": 2.75,
                "disjoint_intervals_since_renderer_start": 0,
                "pending_queries": 3,
            },
        )
        self.assertEqual(
            parse_gpu_timer_log("gpu timer supported=false nonblocking=true"),
            {"supported": False},
        )
        self.assertIsNone(parse_gpu_timer_log("ordinary game log"))
        self.assertEqual(
            parse_gpu_timer_log(
                "gpu timer supported=true bits=48 scope=renderer_start samples=12 "
                "total_ms=30.0000 "
                "mean_ms=2.5000 max_ms=4.0000 last_ms=2.0000 disjoint=0 pending=2\n"
                "gpu timer supported=false bits=0 reason=runtime_error"
            ),
            {"supported": False, "counter_bits": 0},
        )
        self.assertEqual(
            parse_gpu_timer_log(
                "gpu timer supported=true bits=48 scope=renderer_start samples=0 "
                "total_ms=0.0000 "
                "mean_ms=0.0000 max_ms=0.0000 last_ms=0.0000 disjoint=0 pending=1"
            ),
            {"supported": True, "counter_bits": 48},
        )

    def test_profile_bounds_and_missing_process_fail_before_sampling(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 5 and 900"):
            profile_android_app(_APPLICATION_ID, seconds=4)
        with self.assertRaisesRegex(ValueError, "sample interval"):
            profile_android_app(_APPLICATION_ID, seconds=5, sample_seconds=6)
        with self.assertRaisesRegex(ValueError, "invalid Android application"):
            profile_android_app("bad;package", seconds=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
