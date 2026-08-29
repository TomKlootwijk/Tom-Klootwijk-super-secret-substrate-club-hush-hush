from __future__ import annotations

import random
import unittest

from _bootstrap import ROOT
from ugts5.packing import PackedNode32, PackedNodeFields, ParityError


class PackingTests(unittest.TestCase):
    def test_known_round_trip(self):
        f = PackedNodeFields(3, 1, -17, 201, 0xA5, 2, True)
        word = PackedNode32.pack(f)
        self.assertEqual(PackedNode32.unpack(word), f)

    def test_operator_id_formula(self):
        f = PackedNodeFields(6, 1, 0, 0, 0)
        self.assertEqual(f.operator_id, 13)

    def test_all_family_kappa_slots(self):
        for family in range(8):
            for kappa in (0, 1):
                f = PackedNodeFields(family, kappa, 0, 0, 0)
                self.assertEqual(PackedNode32.unpack(PackedNode32.pack(f)).operator_id, (family << 1) | kappa)

    def test_signed_rho_extremes(self):
        for rho in (-128, -1, 0, 1, 127):
            f = PackedNodeFields(0, 0, rho, 0, 0)
            self.assertEqual(PackedNode32.unpack(PackedNode32.pack(f)).delta_rho, rho)

    def test_theta_extremes(self):
        for theta in (0, 1, 127, 128, 255):
            f = PackedNodeFields(0, 0, 0, theta, 0)
            self.assertEqual(PackedNode32.unpack(PackedNode32.pack(f)).delta_theta, theta)

    def test_active_bit_is_decoded(self):
        on = PackedNode32.unpack(PackedNode32.pack(PackedNodeFields(0, 0, 0, 0, 0, active=True)))
        off = PackedNode32.unpack(PackedNode32.pack(PackedNodeFields(0, 0, 0, 0, 0, active=False)))
        self.assertTrue(on.active)
        self.assertFalse(off.active)

    def test_local_flags(self):
        for flags in range(4):
            f = PackedNodeFields(0, 0, 0, 0, 0, flags)
            self.assertEqual(PackedNode32.unpack(PackedNode32.pack(f)).local_flags, flags)

    def test_grammar_path(self):
        for path in (0, 1, 0x55, 0xAA, 0xFF):
            f = PackedNodeFields(0, 0, 0, 0, path)
            self.assertEqual(PackedNode32.unpack(PackedNode32.pack(f)).grammar_path, path)

    def test_single_bit_corruption_detected(self):
        word = PackedNode32.pack(PackedNodeFields(2, 1, 4, 5, 6))
        for bit in range(32):
            corrupted = PackedNode32.corrupt_bit(word, bit)
            self.assertFalse(PackedNode32.verify_parity(corrupted), f"bit {bit}")

    def test_unpack_rejects_bad_parity(self):
        word = PackedNode32.pack(PackedNodeFields(2, 1, 4, 5, 6))
        with self.assertRaises(ParityError):
            PackedNode32.unpack(word ^ (1 << 5))

    def test_even_bit_corruption_can_escape_parity(self):
        word = PackedNode32.pack(PackedNodeFields(2, 1, 4, 5, 6))
        corrupted = word ^ (1 << 5) ^ (1 << 6)
        self.assertTrue(PackedNode32.verify_parity(corrupted))
        self.assertNotEqual(corrupted, word)

    def test_klein_flip_toggles_only_semantic_fields(self):
        f = PackedNodeFields(4, 0, -2, 17, 99, 3, True)
        g = PackedNode32.unpack(PackedNode32.klein_flip(PackedNode32.pack(f)))
        self.assertEqual(g.family, f.family)
        self.assertEqual(g.kappa, 1)
        self.assertEqual(g.delta_rho, f.delta_rho)
        self.assertEqual(g.delta_theta, (-f.delta_theta) & 0xFF)
        self.assertEqual(g.grammar_path, f.grammar_path)
        self.assertEqual(g.local_flags, f.local_flags)
        self.assertEqual(g.active, f.active)

    def test_klein_flip_is_involution(self):
        rng = random.Random(5)
        for _ in range(200):
            f = PackedNodeFields(rng.randrange(8), rng.randrange(2), rng.randrange(-128, 128), rng.randrange(256), rng.randrange(256), rng.randrange(4), bool(rng.randrange(2)))
            word = PackedNode32.pack(f)
            self.assertEqual(PackedNode32.klein_flip(PackedNode32.klein_flip(word)), word)

    def test_range_checks(self):
        for args in [
            (8, 0, 0, 0, 0),
            (0, 2, 0, 0, 0),
            (0, 0, -129, 0, 0),
            (0, 0, 128, 0, 0),
            (0, 0, 0, 256, 0),
            (0, 0, 0, 0, 256),
        ]:
            with self.assertRaises(ValueError):
                PackedNodeFields(*args)


if __name__ == "__main__":
    unittest.main()
