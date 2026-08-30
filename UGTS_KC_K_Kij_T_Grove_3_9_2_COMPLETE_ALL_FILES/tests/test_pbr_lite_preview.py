from __future__ import annotations

import math
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ugts_kc3.editor.scene_view import SceneViewport, _PerspectiveProjector
from ugts_kc3.materials import PBRMaterial, shade_pbr_lite
from ugts_kc3.mobile3d import Material3DRecord, Mesh3DRecord, Node3DRecord
from ugts_kc3.templates3d import blank_mobile3d_project


class PBRLiteTests(unittest.TestCase):
    def test_aligned_numeric_contract(self) -> None:
        material = PBRMaterial(
            "numeric",
            (0.8, 0.25, 0.1, 1.0),
            metallic=0.25,
            roughness=0.4,
            emissive=(0.01, 0.02, 0.03),
        )

        shaded = shade_pbr_lite(
            material,
            (0.0, 0.0, 2.0),
            (0.0, 0.0, -3.0),
            (0.0, 0.0, 4.0),
            (1.0, 0.8, 0.6),
            1.5,
            0.2,
        )

        expected = (1.2895, 0.37205, 0.156675)
        for actual, wanted in zip(shaded, expected):
            self.assertAlmostEqual(actual, wanted, places=12)

    def test_roughness_metallic_and_emission_change_finite_output(self) -> None:
        args = (
            (0.0, 0.0, 1.0),
            (0.2, -0.1, -1.0),
            (0.8, 0.2, 1.0),
            (0.9, 0.8, 0.7),
            1.1,
            0.1,
        )
        rough = tuple(
            shade_pbr_lite(
                PBRMaterial("rough", (0.4, 0.2, 0.1, 1.0), 0.2, value),
                *args,
            )
            for value in (0.0, 1.0)
        )
        metal = tuple(
            shade_pbr_lite(
                PBRMaterial("metal", (0.4, 0.2, 0.1, 1.0), value, 0.35),
                *args,
            )
            for value in (0.0, 1.0)
        )
        baseline = shade_pbr_lite(
            PBRMaterial("dark", (0.4, 0.2, 0.1, 1.0), 0.2, 0.35),
            *args,
        )
        emission = (0.04, 0.03, 0.02)
        glowing = shade_pbr_lite(
            PBRMaterial(
                "glowing",
                (0.4, 0.2, 0.1, 1.0),
                0.2,
                0.35,
                emission,
            ),
            *args,
        )

        expected_rough = (
            (0.34806444370115736, 0.16992834434579449, 0.08767284485382884),
            (0.36131991218144266, 0.16359396911162127, 0.07420387157912452),
        )
        expected_metal = (
            (0.3740400910036986, 0.18379762147029474, 0.0957749715055726),
            (0.3895731189769504, 0.1734174094536325, 0.07610826362765379),
        )
        for actual_colors, expected_colors in (
            (rough, expected_rough),
            (metal, expected_metal),
        ):
            for actual_color, expected_color in zip(actual_colors, expected_colors):
                for actual, expected in zip(actual_color, expected_color):
                    self.assertAlmostEqual(actual, expected, places=12)
        for actual, unlit, added in zip(glowing, baseline, emission):
            self.assertAlmostEqual(actual - unlit, added, places=12)
        self.assertTrue(
            all(
                math.isfinite(value)
                for color in (*rough, *metal, baseline, glowing)
                for value in color
            )
        )

    def test_antiparallel_light_and_view_use_a_zero_half_vector(self) -> None:
        material = PBRMaterial(
            "backlit",
            (0.8, 0.4, 0.2, 1.0),
            metallic=0.25,
            roughness=0.5,
            emissive=(0.01, 0.02, 0.03),
        )

        shaded = shade_pbr_lite(
            material,
            (0.0, 0.0, 1.0),
            (0.0, 0.0, 1.0),
            (0.0, 0.0, 1.0),
            ambient=0.2,
        )

        expected = (0.13, 0.08, 0.06)
        for actual, wanted in zip(shaded, expected):
            self.assertAlmostEqual(actual, wanted, places=12)
            self.assertTrue(math.isfinite(actual))


class DesktopPBRLitePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_face_preview_uses_saved_material_and_center_to_camera_view(self) -> None:
        project = blank_mobile3d_project()
        material = Material3DRecord(
            "test_material",
            (0.2, 0.3, 0.4, 0.7),
            metallic=0.65,
            roughness=0.15,
            emissive=(0.01, 0.02, 0.03),
            double_sided=True,
        )
        mesh = Mesh3DRecord(
            "test_triangle",
            ((-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (0.0, 1.0, 0.0)),
            ((0, 1, 2),),
        )
        node = Node3DRecord("test_node", mesh.id, material.id)
        project.materials = {material.id: material}
        project.meshes = {mesh.id: mesh}
        project.nodes = (node,)
        viewport = SceneViewport()
        projector = _PerspectiveProjector(project, 1280.0, 720.0)

        with patch(
            "ugts_kc3.editor.scene_view.shade_pbr_lite",
            return_value=(0.2, 0.3, 0.4),
        ) as shader:
            faces = viewport._project_node_faces(project, node, projector, None)

        self.assertEqual(len(faces), 1)
        shader.assert_called_once()
        material_arg, normal, light, view, light_color, intensity, ambient = (
            shader.call_args.args
        )
        self.assertEqual(material_arg, material.to_pbr())
        self.assertEqual(normal, (0.0, 0.0, 1.0))
        self.assertEqual(light, project.light.direction)
        self.assertEqual(light_color, project.light.color)
        self.assertEqual(intensity, project.light.intensity)
        self.assertEqual(ambient, project.light.ambient)
        expected_view = (8.0, 16.0 / 3.0, 10.0)
        for actual, expected in zip(view, expected_view):
            self.assertAlmostEqual(actual, expected, places=12)
        color = faces[0][2]
        self.assertAlmostEqual(color.redF(), 0.2, places=3)
        self.assertAlmostEqual(color.greenF(), 0.3, places=3)
        self.assertAlmostEqual(color.blueF(), 0.4, places=3)
        self.assertAlmostEqual(color.alphaF(), 0.7, places=3)
        viewport.close()


if __name__ == "__main__":
    unittest.main()
