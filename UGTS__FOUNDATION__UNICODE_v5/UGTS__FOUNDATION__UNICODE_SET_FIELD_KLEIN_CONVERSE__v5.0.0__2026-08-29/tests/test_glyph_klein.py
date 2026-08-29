from __future__ import annotations

import math
import unittest

from _bootstrap import ROOT
from ugts5.glyph_sdf import glyph_sdf, glyph_segments, reflection_residual
from ugts5.klein import CONVERSE, KleinState, apply_klein_converse, reflect_delta_theta8, reflect_theta, reflect_theta8


class GlyphTests(unittest.TestCase):
    def test_all_registered_pair_glyphs_exist(self):
        for literal in CONVERSE:
            self.assertGreater(len(glyph_segments(literal).segments), 0)

    def test_algebra_glyphs_exist(self):
        for literal in ["∪", "∩", "∖", "∁", "∅", "="]:
            self.assertGreater(len(glyph_segments(literal).segments), 0)

    def test_sdf_negative_on_membership_bar(self):
        self.assertLess(glyph_sdf("∈", 0.0, 0.0), 0.0)

    def test_sdf_positive_far_away(self):
        self.assertGreater(glyph_sdf("∈", 4.0, 4.0), 0.0)

    def test_reflection_law_all_pairs(self):
        samples = [(x / 8.0, y / 8.0) for x in range(-8, 9) for y in range(-8, 9)]
        seen = set()
        for direct, converse in CONVERSE.items():
            if direct in seen or converse in seen:
                continue
            seen.update({direct, converse})
            self.assertLess(reflection_residual(direct, converse, samples), 1e-12)

    def test_unknown_glyph_rejects(self):
        with self.assertRaises(KeyError):
            glyph_segments("?")


class KleinTests(unittest.TestCase):
    def test_reflect_theta_examples(self):
        self.assertAlmostEqual(reflect_theta(0.0), math.pi)
        self.assertAlmostEqual(reflect_theta(math.pi / 2), math.pi / 2)

    def test_reflect_theta_is_involution(self):
        for theta in [0.0, 0.3, 1.0, math.pi, 5.9]:
            self.assertAlmostEqual(reflect_theta(reflect_theta(theta)), theta % (2 * math.pi), places=12)

    def test_reflect_theta8_is_involution(self):
        for code in range(256):
            self.assertEqual(reflect_theta8(reflect_theta8(code)), code)

    def test_delta_theta8_negation_is_involution(self):
        for code in range(256):
            self.assertEqual(reflect_delta_theta8(reflect_delta_theta8(code)), code)

    def test_apply_klein_swaps_and_flips(self):
        s = KleinState("∈", "x", "A", 0.25, 0, 1, 3)
        t = apply_klein_converse(s)
        self.assertEqual(t.literal, "∋")
        self.assertEqual((t.left, t.right), ("A", "x"))
        self.assertEqual(t.kappa, 1)
        self.assertEqual(t.orientation, -1)
        self.assertEqual(t.winding, 4)

    def test_local_klein_involution_with_lineage_increment(self):
        s = KleinState("⊆", "A", "B", 0.7, 0, 1, 0)
        t = apply_klein_converse(apply_klein_converse(s))
        self.assertEqual((t.literal, t.left, t.right, t.kappa, t.orientation), (s.literal, s.left, s.right, s.kappa, s.orientation))
        self.assertAlmostEqual(t.theta, s.theta)
        self.assertEqual(t.winding, s.winding + 2)

    def test_unknown_converse_rejects(self):
        with self.assertRaises(KeyError):
            apply_klein_converse(KleinState("∪", "A", "B", 0.0, 0))


if __name__ == "__main__":
    unittest.main()
