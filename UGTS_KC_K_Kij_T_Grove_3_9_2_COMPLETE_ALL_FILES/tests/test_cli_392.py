import contextlib
import io
import unittest

from ugts_kc3.cli import _parser


class Cli392Tests(unittest.TestCase):
    def test_simulation_steps_must_be_positive(self):
        parser = _parser()
        for command in ("simulate", "simulate-3d"):
            for count in ("0", "-2"):
                with self.subTest(command=command, count=count):
                    with contextlib.redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit):
                            parser.parse_args([command, "project.json", "--steps", count])

    def test_positive_simulation_steps_are_preserved(self):
        self.assertEqual(
            _parser().parse_args(["simulate", "project.json", "--steps", "7"]).steps,
            7,
        )

    def test_new_mobile_project_defaults_to_the_unattributed_lesson(self):
        parsed = _parser().parse_args(["new-3d", "my-game"])
        self.assertEqual(parsed.template, "first-steps")
        self.assertEqual(parsed.author, "")

    def test_chrono_video_defaults_to_bounded_cuda_auto_profile(self):
        parsed = _parser().parse_args(
            ["compile-chrono-video", "source.mp4", "chrono-output"]
        )
        self.assertEqual(parsed.backend, "auto")
        self.assertEqual(parsed.theta_bins, 1024)
        self.assertEqual(parsed.rho_bins, 512)
        self.assertEqual(parsed.sample_stride, 4)
        self.assertEqual(parsed.max_vram_mib, 1536)
        self.assertEqual(parsed.target_kind, "scene")

    def test_chrono_bundle_verification_checks_source_by_default(self):
        parsed = _parser().parse_args(["verify-chrono-video", "bundle"])
        self.assertFalse(parsed.no_source_bytes)


if __name__ == "__main__":
    unittest.main()
