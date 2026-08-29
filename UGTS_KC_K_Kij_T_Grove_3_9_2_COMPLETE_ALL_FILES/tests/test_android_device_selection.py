from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidbuild import AndroidDevice, select_android_device


class AndroidDeviceSelectionTests(unittest.TestCase):
    def test_selects_the_only_authorized_device(self) -> None:
        phone = AndroidDevice("poco-1", "device", "POCO X7 Pro")
        self.assertIs(select_android_device((phone,)), phone)
        self.assertIs(select_android_device((phone,), serial="poco-1"), phone)

    def test_no_device_message_explains_setup(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "No Android device.*USB debugging"):
            select_android_device(())

    def test_unauthorized_message_explains_phone_prompt(self) -> None:
        phone = AndroidDevice("poco-1", "unauthorized", "POCO X7 Pro")
        with self.assertRaisesRegex(RuntimeError, "authorization.*Unlock.*Allow USB debugging"):
            select_android_device((phone,))
        with self.assertRaisesRegex(RuntimeError, "waiting for USB-debugging authorization"):
            select_android_device((phone,), serial="poco-1")

    def test_multiple_devices_are_not_chosen_implicitly(self) -> None:
        devices = (
            AndroidDevice("poco-1", "device", "POCO X7 Pro"),
            AndroidDevice("tablet-1", "device", "Tablet"),
        )
        with self.assertRaisesRegex(RuntimeError, "More than one authorized Android device"):
            select_android_device(devices)

    def test_offline_and_missing_serial_are_distinct(self) -> None:
        offline = AndroidDevice("poco-1", "offline", "POCO X7 Pro")
        with self.assertRaisesRegex(RuntimeError, "No connected Android device is ready"):
            select_android_device((offline,))
        with self.assertRaisesRegex(RuntimeError, "is not connected"):
            select_android_device((offline,), serial="missing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
