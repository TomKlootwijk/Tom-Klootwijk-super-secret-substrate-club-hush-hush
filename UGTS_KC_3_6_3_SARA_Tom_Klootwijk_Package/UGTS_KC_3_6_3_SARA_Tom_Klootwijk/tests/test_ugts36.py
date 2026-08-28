from __future__ import annotations

import copy
import json
import math
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from ugts36 import (
    KleinQuotient,
    MobiusQuotient,
    PermutationHinge,
    Runtime,
    Substrate,
    active_bit_positions,
    apply_affine,
    attach_content_hash,
    canonical_json,
    crossing_time_linear,
    definition_hash,
    digit_count,
    generate_lexicon,
    hourglass_route,
    lexeme,
    log_polar,
    polygon_area,
    pulse_match_values,
    radix_digits,
    regular_polygon,
    rotation_about,
    topological_order,
    verify_content_hash,
)
from ugts36.geometry import from_log_polar, implicit_intersection, implicit_subtraction, implicit_union, matmul3, sdf_circle, translation
from ugts36.topology import DefinitionCycleError


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "ugts_kc_3_6_example.json"
SCHEMA = ROOT / "spec" / "ugts_kc_3_6.schema.json"


class CanonicalTests(unittest.TestCase):
    def test_01_canonical_key_order(self) -> None:
        self.assertEqual(canonical_json({"b": 2, "a": 1}), '{"a":1,"b":2}')

    def test_02_hash_is_stable(self) -> None:
        record = {"id": "d:a", "kind": "literal", "domain": "x", "codomain": "y", "evaluation_phase": 0, "dependencies": [], "parameters": {}, "provenance": {"class": "engineering-derived", "note": "", "source_refs": []}}
        self.assertEqual(definition_hash(record), definition_hash(copy.deepcopy(record)))

    def test_03_hash_changes_with_semantics(self) -> None:
        a = {"id": "d:a", "value": 1}
        b = {"id": "d:a", "value": 2}
        self.assertNotEqual(definition_hash(a), definition_hash(b))

    def test_04_attach_and_verify(self) -> None:
        record = attach_content_hash({"id": "d:a", "kind": "literal"})
        self.assertTrue(verify_content_hash(record))
        record["kind"] = "changed"
        self.assertFalse(verify_content_hash(record))


class GeometryTests(unittest.TestCase):
    def test_05_digit_count(self) -> None:
        self.assertEqual(digit_count(0, 2), 1)
        self.assertEqual(digit_count(1, 2), 1)
        self.assertEqual(digit_count(2, 2), 2)
        self.assertEqual(digit_count(9, 10), 1)
        self.assertEqual(digit_count(10, 10), 2)

    def test_06_radix_digits(self) -> None:
        self.assertEqual(radix_digits(19, 2), (1, 0, 0, 1, 1))
        self.assertEqual(radix_digits(99, 10), (9, 9))

    def test_07_active_bits(self) -> None:
        self.assertEqual(active_bit_positions(19), (0, 1, 4))

    def test_08_regular_triangle_has_area(self) -> None:
        points = regular_polygon(3)
        self.assertEqual(len(points), 3)
        self.assertGreater(polygon_area(points), 1.0)

    def test_09_point_and_segment_embeddings(self) -> None:
        self.assertEqual(regular_polygon(1), ((0.0, 0.0),))
        self.assertEqual(len(regular_polygon(2)), 2)
        self.assertEqual(polygon_area(regular_polygon(2)), 0.0)

    def test_10_rotation_preserves_pivot(self) -> None:
        pivot = (2.0, -1.0)
        matrix = rotation_about(math.pi / 3, pivot)
        result = apply_affine(matrix, pivot)
        self.assertAlmostEqual(result[0], pivot[0])
        self.assertAlmostEqual(result[1], pivot[1])

    def test_11_logpolar_roundtrip(self) -> None:
        rho, theta, core = log_polar((3.0, 4.0))
        self.assertFalse(core)
        x, y = from_log_polar(rho, theta)
        self.assertAlmostEqual(x, 3.0)
        self.assertAlmostEqual(y, 4.0)
        self.assertTrue(log_polar((0.0, 0.0))[2])

    def test_12_sdf_and_csg_signs(self) -> None:
        a = sdf_circle((0.0, 0.0), radius=1.0)
        b = sdf_circle((2.0, 0.0), center=(2.0, 0.0), radius=0.5)
        self.assertLess(a, 0)
        self.assertLess(b, 0)
        self.assertEqual(implicit_union(a, b), min(a, b))
        self.assertEqual(implicit_intersection(a, b), max(a, b))
        self.assertEqual(implicit_subtraction(a, b), max(a, -b))


class DutchPhoneticTests(unittest.TestCase):
    def test_13_negentien_profile(self) -> None:
        item = lexeme(19)
        self.assertEqual(item.orthography, "negentien")
        self.assertEqual(item.pronunciation_segments, ("ne", "gen", "tien"))
        self.assertEqual(item.place_order, (10, 9))
        self.assertEqual(item.spoken_order, (9, "tien"))

    def test_14_drieentwintig_profile(self) -> None:
        item = lexeme(23)
        self.assertEqual(item.orthography, "drieëntwintig")
        self.assertEqual(item.pronunciation_segments, ("drie", "en", "twin", "tig"))
        self.assertTrue(item.pulse_match)

    def test_15_place_and_spoken_order_are_distinct(self) -> None:
        item = lexeme(21)
        self.assertEqual(item.place_order, (20, 1))
        self.assertEqual(item.spoken_order, (1, "en", 20))
        self.assertEqual(item.hinge_kind, "en_connector")

    def test_16_multiple_of_ten_has_no_connector(self) -> None:
        item = lexeme(20)
        self.assertEqual(item.hinge_count, 0)
        self.assertEqual(item.spoken_order, (20,))

    def test_17_zeventien_segments(self) -> None:
        self.assertEqual(lexeme(17).syllable_count, 3)
        self.assertEqual(lexeme(17).hinge_kind, "teen_suffix")

    def test_18_elf_is_irregular(self) -> None:
        item = lexeme(11)
        self.assertEqual(item.hinge_kind, "irregular")
        self.assertEqual(item.syllable_count, 1)

    def test_19_ninety_nine_profile(self) -> None:
        item = lexeme(99)
        self.assertEqual(item.orthography, "negenennegentig")
        self.assertEqual(item.place_order, (90, 9))
        self.assertEqual(item.spoken_order, (9, "en", 90))

    def test_20_lexicon_is_complete_and_unique(self) -> None:
        entries = generate_lexicon()
        self.assertEqual(len(entries), 100)
        self.assertEqual(len({entry.value for entry in entries}), 100)
        self.assertEqual(len({entry.orthography for entry in entries}), 100)

    def test_21_pulse_match_set_is_declared(self) -> None:
        matches = pulse_match_values()
        self.assertEqual(len(matches), 28)
        self.assertIn(19, matches)
        self.assertIn(23, matches)

    def test_22_profile_bounds(self) -> None:
        with self.assertRaises(ValueError):
            lexeme(100)
        with self.assertRaises(TypeError):
            lexeme(1.0)  # type: ignore[arg-type]


class TopologyHingeTests(unittest.TestCase):
    def test_23_permutation_connector_hinge(self) -> None:
        hinge = PermutationHinge((1, 0), connector="en")
        self.assertEqual(hinge.apply((20, 3)), (3, "en", 20))

    def test_24_bad_permutation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PermutationHinge((0, 0)).apply((1, 2))

    def test_25_affine_composition_is_noncommutative(self) -> None:
        r = rotation_about(math.pi / 2)
        t = translation(1.0, 0.0)
        p = (2.0, 0.0)
        rt = apply_affine(matmul3(r, t), p)
        tr = apply_affine(matmul3(t, r), p)
        self.assertNotAlmostEqual(rt[0], tr[0])
        self.assertNotAlmostEqual(rt[1], tr[1])

    def test_26_mobius_flip(self) -> None:
        point, orientation = MobiusQuotient(4.0, 2.0).map((4.5, 0.25), 1)
        self.assertAlmostEqual(point[0], 0.5)
        self.assertAlmostEqual(point[1], 1.75)
        self.assertEqual(orientation, -1)

    def test_27_klein_flip_and_sheet_toggle(self) -> None:
        point, orientation, sheet = KleinQuotient(4.0, 2.0).map((4.5, 0.25), 1, 0)
        self.assertAlmostEqual(point[0], 0.5)
        self.assertEqual(orientation, -1)
        self.assertEqual(sheet, 1)

    def test_28_linear_crossing_time(self) -> None:
        self.assertAlmostEqual(crossing_time_linear(-1.0, 1.0, 0.0, 4.0) or -1, 2.0)
        self.assertIsNone(crossing_time_linear(1.0, 2.0, 0.0, 1.0))

    def test_29_hourglass_routes(self) -> None:
        self.assertEqual(hourglass_route(1, 1, 0), "A")
        self.assertEqual(hourglass_route(1, 1, 1), "C")
        self.assertEqual(hourglass_route(-1, 1, 0), "B")

    def test_30_topological_order_and_cycle(self) -> None:
        self.assertEqual(topological_order(("a", "b", "c"), {"b": ("a",), "c": ("b",)}), ("a", "b", "c"))
        with self.assertRaises(DefinitionCycleError):
            topological_order(("a", "b"), {"a": ("b",), "b": ("a",)})


class SubstrateRuntimeTests(unittest.TestCase):
    def test_31_json_schema_validation(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(example)), [])

    def test_32_substrate_load_and_order(self) -> None:
        substrate = Substrate.load(EXAMPLE)
        self.assertEqual(substrate.schema_version, "3.6.0")
        self.assertIn("op:count-compare-v1", substrate.definition_order())

    def test_33_all_definition_hashes_verify(self) -> None:
        substrate = Substrate.load(EXAMPLE)
        self.assertTrue(all(verify_content_hash(node.record) for node in substrate.definitions.values()))

    def test_34_runtime_trace_for_19(self) -> None:
        trace = Runtime(Substrate.load(EXAMPLE)).execute("pipeline:number-to-geometry", "number:19")
        compare = next(item.output for item in trace if item.kind == "feature_count_compare")
        polygon = next(item.output for item in trace if item.kind == "regular_polygon_embedding")
        self.assertTrue(compare["equal"])
        self.assertEqual(compare["semantics"], "feature-count coincidence; no numeric identity")
        self.assertEqual(polygon["vertex_count"], 3)

    def test_35_runtime_trace_for_23(self) -> None:
        trace = Runtime(Substrate.load(EXAMPLE)).execute("pipeline:number-to-geometry", "number:23")
        lexeme_output = next(item.output for item in trace if item.kind == "nl_number_lexeme")
        polygon = next(item.output for item in trace if item.kind == "regular_polygon_embedding")
        self.assertEqual(lexeme_output["spoken_order"], [3, "en", 20])
        self.assertEqual(polygon["vertex_count"], 4)

    def test_36_missing_reference_is_rejected(self) -> None:
        raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        raw["instances"][0]["definition_ref"] = "missing:def"
        with self.assertRaises(KeyError):
            Substrate.from_dict(raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
