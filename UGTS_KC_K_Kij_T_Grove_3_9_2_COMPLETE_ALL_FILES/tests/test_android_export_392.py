import tempfile
from pathlib import Path
import unittest

from ugts_kc3.androidbuild import supported_variants
from ugts_kc3.androidexport import android_application_id, build_android_project
from ugts_kc3.templates3d import blank_mobile3d_project


class AndroidExport392Tests(unittest.TestCase):
    def test_game_ids_become_distinct_install_safe_application_ids(self):
        self.assertEqual(
            android_application_id("my.first-game"),
            "org.ugts.games.my.first.game",
        )
        self.assertNotEqual(
            android_application_id("my.first-game"),
            android_application_id("my.second-game"),
        )

    def test_export_escapes_title_keeps_evidence_out_of_runtime_and_has_wrapper(self):
        project = blank_mobile3d_project("Stars & <Friends>", "Learner")
        with tempfile.TemporaryDirectory() as tmp:
            result = build_android_project(project, Path(tmp) / "android")
            strings = (
                result.output_dir / "app/src/main/res/values/strings.xml"
            ).read_text(encoding="utf-8")
            self.assertIn("Stars &amp; &lt;Friends&gt;", strings)
            self.assertTrue((result.output_dir / "project.json").is_file())
            self.assertFalse(
                (result.output_dir / "app/src/main/assets/project.json").exists()
            )
            self.assertTrue((result.output_dir / "gradlew.bat").is_file())
            self.assertTrue(
                (result.output_dir / "gradle/wrapper/gradle-wrapper.jar").is_file()
            )
            gradle = (result.output_dir / "app/build.gradle").read_text("utf-8")
            self.assertNotIn("__APPLICATION_ID__", gradle)

    def test_owner_device_variants_are_explicit(self):
        self.assertEqual(
            supported_variants(),
            ("poco-debug", "poco-release", "universal-debug", "universal-release"),
        )


if __name__ == "__main__":
    unittest.main()
