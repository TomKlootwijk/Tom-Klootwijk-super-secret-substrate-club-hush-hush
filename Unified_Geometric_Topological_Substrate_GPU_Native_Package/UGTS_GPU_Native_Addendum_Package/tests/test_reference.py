from __future__ import annotations
import json
import math
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reference"))
import ugts_reference as u


def sample_state(**overrides):
    values = dict(
        position=(0.0, 0.0, 0.99), time=2.5,
        axis=(0.0, 0.0, 1.0), radius=1.0,
        cone_cos=0.5, phase=0.25, guard_epsilon=0.02,
        confidence_floor=0.5, sheet=1, orientation=0,
        compatibility_mask=4, lineage_seed=0x12345678,
    )
    values.update(overrides)
    return u.State(**values)


class TestUGTSReference(unittest.TestCase):
    def test_standard_percent(self):
        self.assertEqual(u.glyph_encode_100_percent("standard")["decimal"], 1)

    def test_glyph_encoder_v1(self):
        value = u.glyph_encode_100_percent("glyph-100100-v1")
        self.assertEqual(value["bits"], "100100")
        self.assertEqual(value["decimal"], 36)
        self.assertIn("1 << 5", value["expression"])

    def test_glyph_encoder_v0(self):
        self.assertEqual(u.glyph_encode_100_percent("glyph-100101-v0")["decimal"], 37)

    def test_evaluate_verified(self):
        e = u.evaluate(sample_state(), u.Query(), 7)
        self.assertTrue(e.in_support)
        self.assertTrue(e.compatible)
        self.assertTrue(e.verified)
        self.assertEqual(e.route, 1)

    def test_evaluate_outside_radius(self):
        e = u.evaluate(sample_state(position=(0,0,1.2)), u.Query())
        self.assertFalse(e.in_support)
        self.assertFalse(e.verified)

    def test_evaluate_outside_cone(self):
        e = u.evaluate(sample_state(position=(1,0,0), cone_cos=0.1), u.Query())
        self.assertFalse(e.in_support)

    def test_incompatible_sheet(self):
        e = u.evaluate(sample_state(sheet=2), u.Query(target_sheet=1))
        self.assertFalse(e.compatible)
        self.assertFalse(e.verified)

    def test_incompatible_mask(self):
        e = u.evaluate(sample_state(compatibility_mask=0), u.Query(mode_bit=2))
        self.assertFalse(e.compatible)

    def test_counters(self):
        states = [sample_state(), sample_state(position=(0,0,1.2)), sample_state(sheet=2)]
        events, c = u.evaluate_many(states, u.Query())
        self.assertEqual(len(events), 3)
        self.assertEqual(c["candidates"], 3)
        self.assertEqual(c["verified"], 1)

    def test_g64_roundtrip(self):
        s = sample_state()
        packed = u.pack_g64(s)
        self.assertEqual(len(packed), 64)
        r = u.unpack_g64(packed)
        self.assertEqual(r.sheet, s.sheet)
        self.assertAlmostEqual(r.position[2], s.position[2], places=6)

    def test_g32_roundtrip(self):
        s = sample_state()
        packed = u.pack_g32(s)
        self.assertEqual(len(packed), 32)
        r = u.unpack_g32(packed)
        self.assertEqual(r.sheet, s.sheet)
        self.assertEqual(r.compatibility_mask, s.compatibility_mask)
        self.assertAlmostEqual(r.position[2], s.position[2], places=3)

    def test_event_sizes(self):
        e = u.evaluate(sample_state(), u.Query())
        self.assertEqual(len(u.pack_e32(e)), 32)
        self.assertEqual(len(u.pack_e16(e)), 16)

    def test_mix32_deterministic(self):
        self.assertEqual(u.mix32(123), u.mix32(123))
        self.assertNotEqual(u.mix32(123), u.mix32(124))

    def test_memory_model(self):
        m = u.memory_model(1_048_576, 49_878)
        self.assertEqual(m["G64_E32_dense"], 96 * 1_048_576)
        self.assertEqual(m["G32_E16_dense"], 48 * 1_048_576)
        self.assertEqual(m["one_bit_support_mask"], 131_072)

    def test_pythagorean_threshold(self):
        level, latched, triggered = u.pythagorean_cup_step(0.9, 0.2, 1.0)
        self.assertEqual(level, 0.0)
        self.assertTrue(latched)
        self.assertTrue(triggered)

    def test_log2_fractional_scale(self):
        self.assertAlmostEqual(math.log2(1.5), 0.5849625007211562)

    def test_schema_loads(self):
        schema = json.loads((ROOT / "spec/schema.json").read_text())
        self.assertEqual(schema["properties"]["schema"]["const"], "UGTS-GN-1.1")

    def test_catalog_count(self):
        import csv
        with (ROOT / "spec/knowledge_catalog.csv").open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 211)
        self.assertEqual(rows[0]["mechanism_id"], "M001")
        self.assertEqual(rows[-1]["mechanism_id"], "M211")


if __name__ == "__main__":
    unittest.main()
