from __future__ import annotations

import math
import unittest

import numpy as np

from ugts_spatial.geocell import (
    decode_morton_cell,
    encode_morton_cell,
    haversine_m,
    local_enu_m,
    make_spatial_index,
    morton_grid_disk,
)


class GeoCellTests(unittest.TestCase):
    def test_morton_roundtrip_and_neighbors(self) -> None:
        latitude, longitude = 52.5185, 5.4714
        cell = encode_morton_cell(latitude, longitude, 13)
        decoded_lat, decoded_lon, resolution = decode_morton_cell(cell)
        self.assertEqual(resolution, 13)
        self.assertLess(haversine_m(latitude, longitude, decoded_lat, decoded_lon), 6000.0)
        neighbors = morton_grid_disk(cell, 1)
        self.assertIn(cell, neighbors)
        self.assertEqual(len(neighbors), len(set(neighbors)))
        self.assertGreaterEqual(len(neighbors), 4)

    def test_local_enu_has_expected_axes(self) -> None:
        origin_lat, origin_lon = 52.5, 5.5
        result = local_enu_m(
            np.asarray([origin_lat, origin_lat + 0.001]),
            np.asarray([origin_lon + 0.001, origin_lon]),
            origin_lat,
            origin_lon,
            np.asarray([2.0, 5.0]),
            2.0,
        )
        self.assertGreater(result[0, 0], 0.0)
        self.assertAlmostEqual(result[0, 1], 0.0, delta=1.0)
        self.assertGreater(result[1, 1], 0.0)
        self.assertAlmostEqual(result[1, 0], 0.0, delta=1.0)
        self.assertAlmostEqual(result[1, 2], 3.0, places=5)

    def test_spatial_index_broad_phase(self) -> None:
        index = make_spatial_index("morton", 12)
        cell = index.cell(52.5, 5.5)
        ring = index.ring_for_radius(cell, 52.5, 10_000.0)
        self.assertGreaterEqual(ring, 1)
        self.assertIn(cell, index.neighbors(cell, ring))
        lat, lon = index.center(cell)
        self.assertTrue(math.isfinite(lat) and math.isfinite(lon))


if __name__ == "__main__":
    unittest.main()
