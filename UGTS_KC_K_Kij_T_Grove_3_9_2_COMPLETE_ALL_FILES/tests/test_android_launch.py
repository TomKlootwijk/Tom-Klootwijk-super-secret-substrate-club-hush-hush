from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidbuild import (
    AndroidDevice,
    AndroidToolchain,
    build_apk,
    launch_android_app,
)


class AndroidLaunchTests(unittest.TestCase):
    @staticmethod
    def _project_with_apk(root: Path, apk_name: str = "app-pocoX7Pro-debug.apk") -> tuple[Path, Path]:
        (root / "settings.gradle").write_text("rootProject.name='test'\n", "utf-8")
        output = root / "app/build/outputs/apk/pocoX7Pro/debug"
        output.mkdir(parents=True)
        apk = output / apk_name
        apk.write_bytes(b"APK")
        return output, apk

    def test_build_result_uses_gradle_application_id_and_named_apk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            output, apk = self._project_with_apk(project)
            (output / "unrelated-debug.apk").write_bytes(b"OTHER")
            (output / "output-metadata.json").write_text(
                json.dumps({
                    "applicationId": "org.ugts.games.child.pocox7pro",
                    "elements": [{"outputFile": apk.name}],
                }),
                "utf-8",
            )
            toolchain = AndroidToolchain(project, project / "adb", ("gradle",))
            with (
                patch(
                    "ugts_kc3.androidbuild.AndroidToolchain.discover",
                    return_value=toolchain,
                ),
                patch("ugts_kc3.androidbuild._run", return_value="BUILD SUCCESSFUL"),
            ):
                result = build_apk(project)
            self.assertEqual(result.application_id, "org.ugts.games.child.pocox7pro")
            self.assertEqual(result.apk, apk)

    def test_build_fails_closed_when_metadata_names_no_produced_apk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            output, _apk = self._project_with_apk(project, "actual.apk")
            (output / "zzz-stale.apk").write_bytes(b"STALE")
            (output / "output-metadata.json").write_text(
                json.dumps({
                    "applicationId": "org.ugts.games.child.pocox7pro",
                    "elements": [{"outputFile": "missing.apk"}],
                }),
                "utf-8",
            )
            toolchain = AndroidToolchain(project, project / "adb", ("gradle",))
            with (
                patch(
                    "ugts_kc3.androidbuild.AndroidToolchain.discover",
                    return_value=toolchain,
                ),
                patch("ugts_kc3.androidbuild._run", return_value="BUILD SUCCESSFUL"),
            ):
                with self.assertRaisesRegex(RuntimeError, "does not match the APK"):
                    build_apk(project)

    def test_build_only_keeps_legacy_tree_without_output_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            _output, apk = self._project_with_apk(project)
            toolchain = AndroidToolchain(project, project / "adb", ("gradle",))
            with (
                patch(
                    "ugts_kc3.androidbuild.AndroidToolchain.discover",
                    return_value=toolchain,
                ),
                patch("ugts_kc3.androidbuild._run", return_value="BUILD SUCCESSFUL"),
            ):
                result = build_apk(project)
            self.assertEqual(result.apk, apk)
            self.assertEqual(result.application_id, "")

    def test_launch_pins_serial_and_opens_native_activity(self) -> None:
        phone = AndroidDevice("poco-1", "device", "POCO X7 Pro")
        sdk = Path("C:/Android/Sdk")
        adb = sdk / "platform-tools/adb.exe"
        with (
            patch("ugts_kc3.androidbuild._find_sdk_root", return_value=sdk),
            patch("ugts_kc3.androidbuild._find_adb", return_value=adb),
            patch("ugts_kc3.androidbuild.list_android_devices", return_value=(phone,)),
            patch(
                "ugts_kc3.androidbuild._run",
                return_value="Starting: Intent\nStatus: ok\nActivity: NativeActivity\n",
            ) as run,
        ):
            result = launch_android_app(
                "org.ugts.games.child.pocox7pro", serial="poco-1"
            )
        self.assertEqual(
            run.call_args.args[0],
            [
                str(adb), "-s", "poco-1", "shell", "am", "start", "-W", "-S",
                "--user", "current", "-n",
                "org.ugts.games.child.pocox7pro/android.app.NativeActivity",
            ],
        )
        self.assertEqual(result.serial, "poco-1")

    def test_launch_rejects_android_error_even_when_adb_exits_zero(self) -> None:
        phone = AndroidDevice("poco-1", "device", "POCO X7 Pro")
        sdk = Path("C:/Android/Sdk")
        with (
            patch("ugts_kc3.androidbuild._find_sdk_root", return_value=sdk),
            patch("ugts_kc3.androidbuild._find_adb", return_value=sdk / "adb.exe"),
            patch("ugts_kc3.androidbuild.list_android_devices", return_value=(phone,)),
            patch(
                "ugts_kc3.androidbuild._run",
                return_value="Error: Activity class does not exist.\n",
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "did not confirm that it opened"):
                launch_android_app("org.ugts.games.child", serial="poco-1")

    def test_launch_rejects_hostile_application_id_before_adb(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid Android application id"):
            launch_android_app("org.ugts.child; rm -rf /")


if __name__ == "__main__":
    unittest.main(verbosity=2)
