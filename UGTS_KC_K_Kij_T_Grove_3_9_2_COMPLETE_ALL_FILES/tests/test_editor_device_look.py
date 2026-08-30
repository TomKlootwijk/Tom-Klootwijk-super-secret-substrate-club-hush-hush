from __future__ import annotations

import os
import re
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGraphicsView, QWidget

from ugts_kc3.editor.device_look import (
    BAYER8,
    DeviceLookOpenGLViewport,
    DeviceLookSupport,
    bayer_reference_fragment_rgb,
    bayer_reference_rgb,
    native_post_shader_source,
    shader_source_for_context,
)
from ugts_kc3.editor.document import EditorDocument
from ugts_kc3.editor.scene_view import SceneViewport
from ugts_kc3.renderpack import RenderSubstrateConfig
from ugts_kc3.templates3d import blank_mobile3d_project


_OFF = RenderSubstrateConfig(
    polar_mode="cpu",
    bayer_mode="off",
    levels=2,
    strength=0.0,
    seed=392,
)
_SUBTLE = RenderSubstrateConfig(
    polar_mode="lut",
    bayer_mode="subtle",
    levels=64,
    strength=0.30,
    seed=392,
)
_RETRO = RenderSubstrateConfig(
    polar_mode="direct",
    bayer_mode="retro",
    levels=4,
    strength=1.0,
    seed=0,
)


class DeviceLookReferenceMathTests(unittest.TestCase):
    def test_off_is_exact_identity_before_clamp(self) -> None:
        source = (-0.25, 0.375, 1.5)
        self.assertEqual(
            bayer_reference_rgb(
                source,
                physical_x=7,
                physical_y_top=7,
                config=_OFF,
            ),
            source,
        )
        self.assertEqual(
            bayer_reference_rgb(
                source,
                physical_x=0,
                physical_y_top=0,
                config=None,
            ),
            source,
        )

    def test_enabled_branch_matches_native_threshold_quantize_and_mix(self) -> None:
        low_threshold = bayer_reference_rgb(
            (0.5, 0.5, 0.5),
            physical_x=0,
            physical_y_top=0,
            config=_RETRO,
        )
        high_threshold = bayer_reference_rgb(
            (0.5, 0.5, 0.5),
            physical_x=7,
            physical_y_top=0,
            config=_RETRO,
        )
        self.assertEqual(low_threshold, (1.0 / 3.0,) * 3)
        self.assertEqual(high_threshold, (2.0 / 3.0,) * 3)

        subtle = bayer_reference_rgb(
            (-1.0, 0.5, 2.0),
            physical_x=0,
            physical_y_top=0,
            config=_SUBTLE,
        )
        expected_middle = 0.5 * 0.7 + (31.0 / 63.0) * 0.3
        self.assertEqual(subtle[0], 0.0)
        self.assertAlmostEqual(subtle[1], expected_middle, places=15)
        self.assertEqual(subtle[2], 1.0)

    def test_fragment_phase_is_top_origin_and_uses_physical_height(self) -> None:
        bottom_origin_row_zero = bayer_reference_fragment_rgb(
            (0.5, 0.5, 0.5),
            fragment_x=0.5,
            fragment_y_bottom=0.5,
            output_height=8,
            config=_RETRO,
        )
        direct_top_row_seven = bayer_reference_rgb(
            (0.5, 0.5, 0.5),
            physical_x=0,
            physical_y_top=7,
            config=_RETRO,
        )
        self.assertEqual(bottom_origin_row_zero, direct_top_row_seven)

        odd_height_bottom = bayer_reference_fragment_rgb(
            (0.5, 0.5, 0.5),
            fragment_x=8.5,
            fragment_y_bottom=0.5,
            output_height=9,
            config=_RETRO,
        )
        direct_top_row_zero = bayer_reference_rgb(
            (0.5, 0.5, 0.5),
            physical_x=0,
            physical_y_top=0,
            config=_RETRO,
        )
        self.assertEqual(odd_height_bottom, direct_top_row_zero)

    def test_recipe_seed_does_not_shift_bayer_phase(self) -> None:
        other_seed = RenderSubstrateConfig(
            polar_mode=_SUBTLE.polar_mode,
            bayer_mode=_SUBTLE.bayer_mode,
            levels=_SUBTLE.levels,
            strength=_SUBTLE.strength,
            seed=0xFFFFFFFFFFFFFFFF,
        )
        sample = (0.23, 0.51, 0.87)
        self.assertEqual(
            bayer_reference_rgb(
                sample,
                physical_x=5,
                physical_y_top=3,
                config=_SUBTLE,
            ),
            bayer_reference_rgb(
                sample,
                physical_x=5,
                physical_y_top=3,
                config=other_seed,
            ),
        )

    def test_oracle_matrix_and_formula_are_locked_to_shared_native_shader(self) -> None:
        fragment = native_post_shader_source("grove_post.frag")
        matrix_block = fragment.split("const int Bayer8[64]=int[64](", 1)[1].split(
            ");", 1
        )[0]
        self.assertEqual(
            tuple(int(value) for value in re.findall(r"\d+", matrix_block)),
            BAYER8,
        )
        compact = re.sub(r"\s+", "", fragment)
        self.assertIn(
            "if(uBayerMode==0){fragColor=vec4(c,1.0);return;}vec3src=clamp(c,0.0,1.0);",
            compact,
        )
        self.assertIn(
            "intyTop=(uOutputHeight-1-int(gl_FragCoord.y))&7;",
            compact,
        )
        self.assertIn("c=mix(src,q,uBayerStrength);", compact)

    def test_desktop_shader_adapter_changes_only_the_dialect_preamble(self) -> None:
        for filename in ("grove_post.vert", "grove_post.frag"):
            native = native_post_shader_source(filename)
            self.assertEqual(
                shader_source_for_context(native, is_gles=True), native
            )
            desktop = shader_source_for_context(native, is_gles=False)
            self.assertTrue(desktop.startswith("#version 330 core\n"))
            native_body = "\n".join(
                line
                for line in native.splitlines()[1:]
                if not line.lstrip().startswith("precision ")
            )
            desktop_body = "\n".join(desktop.splitlines()[1:])
            self.assertEqual(desktop_body, native_body)


class DeviceLookViewportFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _viewport_with_bayer(mode: str) -> SceneViewport:
        project = blank_mobile3d_project()
        project.metadata["substrate_render"] = {
            "polar_mode": "lut",
            "bayer_mode": mode,
            "seed": 392,
        }
        document = EditorDocument()
        document.create(project)
        viewport = SceneViewport()
        viewport.set_document(document)
        return viewport

    def test_unavailable_gl_keeps_scene_selection_and_transform_on_raster(self) -> None:
        viewport = self._viewport_with_bayer("subtle")
        try:
            scene = viewport.scene()
            item_count = len(scene.items())
            viewport.scale(1.25, 1.25)
            transform = viewport.transform()
            with patch(
                "ugts_kc3.editor.scene_view.probe_device_look_gl",
                return_value=DeviceLookSupport(False, "forced headless fallback"),
            ):
                viewport.device_look_toggle.setChecked(True)
                self.app.processEvents()

            self.assertIs(viewport.scene(), scene)
            self.assertEqual(len(viewport.scene().items()), item_count)
            self.assertEqual(viewport.transform(), transform)
            self.assertIsInstance(viewport.viewport(), QWidget)
            self.assertNotIsInstance(
                viewport.viewport(), DeviceLookOpenGLViewport
            )
            self.assertFalse(viewport.device_look_uses_opengl)
            self.assertIn("reference", viewport.device_look_status.lower())
            self.assertIn("raster fallback", viewport.device_look_status.lower())
            self.assertEqual(
                viewport.viewportUpdateMode(),
                QGraphicsView.ViewportUpdateMode.SmartViewportUpdate,
            )
        finally:
            viewport.close()

    def test_off_recipe_never_probes_gl_and_stays_visibly_unchanged(self) -> None:
        viewport = self._viewport_with_bayer("off")
        try:
            with patch(
                "ugts_kc3.editor.scene_view.probe_device_look_gl"
            ) as probe:
                viewport.device_look_toggle.setChecked(True)
                self.app.processEvents()
            probe.assert_not_called()
            self.assertFalse(viewport.device_look_uses_opengl)
            self.assertIn("Bayer Off", viewport.device_look_status)
            self.assertIn("unchanged", viewport.device_look_status)
        finally:
            viewport.close()

    def test_invalid_recipe_reports_raster_fallback_without_crashing(self) -> None:
        project = blank_mobile3d_project()
        project.metadata["substrate_render"] = {"bayer_mode": "custom"}
        document = EditorDocument()
        document.create(project)
        viewport = SceneViewport()
        try:
            viewport.set_document(document)
            viewport.device_look_toggle.setChecked(True)
            self.app.processEvents()
            self.assertFalse(viewport.device_look_uses_opengl)
            self.assertIn("Invalid settings", viewport.device_look_status)
            self.assertIn("raster fallback", viewport.device_look_status)
        finally:
            viewport.close()


if __name__ == "__main__":
    unittest.main()
