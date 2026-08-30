from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.polar_population import (  # noqa: E402
    PolarPopulationError,
    polar_glow_phase12,
    polar_material_bands_sample,
    polar_material_phase12,
)


class PolarMaterialBandsTests(unittest.TestCase):
    def test_shared_phase_keeps_the_frozen_glow_lane_exact(self) -> None:
        vectors = (
            (0, 1236),
            (1, 3119),
            (0x123456789ABCDEF0, 3725),
            (0xFFFFFFFFFFFFFFFF, 278),
        )
        for lineage, expected in vectors:
            with self.subTest(lineage=lineage):
                self.assertEqual(polar_material_phase12(lineage), expected)
                self.assertEqual(polar_glow_phase12(lineage), expected)

    def test_staged_binary32_reference_vector_is_exact(self) -> None:
        sample = polar_material_bands_sample(
            lineage=0x123456789ABCDEF0,
            rho=0.0,
            rho_min=-2.0,
            rho_max=2.0,
            direction=(-1.0, 0.0),
            bands=4,
            strength=0.75,
        )
        self.assertEqual(sample.q, 0.5)
        self.assertEqual(sample.direction_x, -1.0)
        self.assertEqual(sample.direction_y, 0.0)
        self.assertEqual(sample.phase12, 3725)
        self.assertEqual(sample.phase, 0.909423828125)
        self.assertEqual(sample.band, 0.18115234375)
        self.assertEqual(sample.multiplier, 0.7608642578125)

    def test_radius_clamps_and_zero_strength_preserves_authored_base(self) -> None:
        low = polar_material_bands_sample(
            lineage=0,
            rho=-100.0,
            rho_min=-4.0,
            rho_max=4.0,
            direction=(1.0, 0.0),
            bands=32,
            strength=0.0,
        )
        high = polar_material_bands_sample(
            lineage=0,
            rho=100.0,
            rho_min=-4.0,
            rho_max=4.0,
            direction=(0.0, 1.0),
            bands=1,
            strength=1.0,
        )
        self.assertEqual(low.q, 0.0)
        self.assertEqual(low.multiplier, 1.0)
        self.assertEqual(high.q, 1.0)
        self.assertEqual((high.direction_x, high.direction_y), (0.0, 1.0))
        self.assertGreaterEqual(high.multiplier, 0.5)
        self.assertLessEqual(high.multiplier, 1.5)

    def test_invalid_inputs_fail_closed(self) -> None:
        valid = {
            "lineage": 0,
            "rho": 0.0,
            "rho_min": -1.0,
            "rho_max": 1.0,
            "direction": (1.0, 0.0),
            "bands": 4,
            "strength": 0.5,
        }
        mutations = (
            {"lineage": -1},
            {"lineage": 1 << 64},
            {"bands": True},
            {"bands": 0},
            {"bands": 33},
            {"strength": True},
            {"strength": math.nan},
            {"strength": math.inf},
            {"strength": -0.0},
            {"strength": -0.01},
            {"strength": 1.01},
            {"direction": None},
            {"direction": (1.0,)},
            {"direction": (math.nan, 0.0)},
            {"direction": (1.1, 0.0)},
            {"rho_min": 1.0, "rho_max": 1.0},
            {"rho_min": 2.0, "rho_max": 1.0},
            {"rho": math.nan},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                arguments = dict(valid)
                arguments.update(mutation)
                with self.assertRaises(PolarPopulationError):
                    polar_material_bands_sample(**arguments)


if __name__ == "__main__":
    unittest.main(verbosity=2)
