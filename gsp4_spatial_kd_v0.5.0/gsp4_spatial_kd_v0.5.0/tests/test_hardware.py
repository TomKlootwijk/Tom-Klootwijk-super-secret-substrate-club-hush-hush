from __future__ import annotations

import unittest

from ugts_spatial.hardware import hardware_report


class HardwareReportTests(unittest.TestCase):
    def test_report_is_explicit_about_runtime(self) -> None:
        report = hardware_report()
        self.assertEqual(report["format"], "UGTS-SPATIAL-HARDWARE-1")
        self.assertIn("cuda_available", report)
        self.assertIn("devices", report)
        self.assertIn("sm120_present", report["acceptance"])


if __name__ == "__main__":
    unittest.main()
