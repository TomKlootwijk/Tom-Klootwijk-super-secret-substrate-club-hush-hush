from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from ugts36.bea_runtime import SyntheticBEARuntime
from ugts36.bea_synthetic import (
    SOURCE_ANNOTATION,
    TARGET_ANNOTATION,
    CellComplex1D,
    CellEdge,
    RepresentationAnnotation,
    SemanticBoundaryProfile,
    SemanticPoint,
    SyntheticTextProfile,
    bit_parity,
    bit_weight,
    build_augmented_cell_complex,
    build_synthetic_bea_certificate,
    build_torus_immersion,
    collapse_whitespace_hinges,
    even_delta_subspace_member,
    parity_coset,
    trade_one_space_loop,
    xor_delta_matrix,
    xor_translation_preserves_parity,
)
from ugts36.canonical import verify_content_hash
from ugts36.model import Substrate

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "ugts_kc_3_6_1_bea_synthetic_example.json"
SCHEMA = ROOT / "spec" / "ugts_kc_3_6_1_bea_synthetic.schema.json"
CATALOG = ROOT / "spec" / "bea_3_6_1_delta_operator_catalog.json"


class ProfileAndTransductionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = SyntheticTextProfile()

    def test_01_profile_is_fixed_to_torus_four(self) -> None:
        with self.assertRaises(ValueError):
            SyntheticTextProfile(torus_dimension=3)

    def test_02_normalization_preserves_single_spaces(self) -> None:
        self.assertEqual(self.profile.normalize("  NO   NEG  MOAT  "), "no neg moat")

    def test_03_source_transduction(self) -> None:
        result = self.profile.transduce(SOURCE_ANNOTATION)
        self.assertEqual(result.output_text, "n3g3nt13n")
        self.assertEqual(result.intrinsic_cycle_count, 4)

    def test_04_target_transduction(self) -> None:
        result = self.profile.transduce(TARGET_ANNOTATION)
        self.assertEqual(result.output_text, "n0 n3g m04t")
        self.assertEqual(result.token_count, 3)
        self.assertEqual(result.whitespace_count, 2)

    def test_05_provenance_retained(self) -> None:
        result = self.profile.transduce(TARGET_ANNOTATION)
        self.assertEqual(result.provenance[4].source_symbol, "e")
        self.assertEqual(result.provenance[4].output_symbol, "3")

    def test_06_cycle_annotation_rejects_space(self) -> None:
        with self.assertRaises(ValueError):
            RepresentationAnnotation("bad", "a b", 19.0, (1,))

    def test_07_layout_changing_normalization_rejected(self) -> None:
        annotation = RepresentationAnnotation("x", "a  b", 19.0, (0,))
        with self.assertRaises(ValueError):
            self.profile.transduce(annotation)


class SpaceHoleTradingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = SyntheticTextProfile()
        self.source_t = self.profile.transduce(SOURCE_ANNOTATION)
        self.target_t = self.profile.transduce(TARGET_ANNOTATION)
        self.source_aug = build_augmented_cell_complex(self.source_t, self.profile)
        self.target_aug = build_augmented_cell_complex(self.target_t, self.profile)

    def test_08_source_augmented_signature(self) -> None:
        self.assertEqual(self.source_aug.betti_signature(), {"vertices": 10, "edges": 13, "beta0": 1, "beta1": 4, "chi": -3})

    def test_09_target_augmented_signature(self) -> None:
        self.assertEqual(self.target_aug.betti_signature(), {"vertices": 12, "edges": 15, "beta0": 3, "beta1": 6, "chi": -3})

    def test_10_target_has_two_space_loops(self) -> None:
        self.assertEqual(len([edge for edge in self.target_aug.edges if edge.kind == "space_loop"]), 2)
        self.assertTrue(all(edge.metric_weight == 0.0 for edge in self.target_aug.space_hinge_edges))

    def test_11_one_trade_preserves_euler(self) -> None:
        edge = next(edge for edge in self.target_aug.edges if edge.kind == "space_loop")
        after, record = trade_one_space_loop(self.target_aug, edge.edge_id)
        self.assertTrue(record.valid)
        self.assertEqual(record.chi_before, record.chi_after)
        self.assertEqual(after.vertex_count, self.target_aug.vertex_count)
        self.assertEqual(after.edge_count, self.target_aug.edge_count)

    def test_12_one_trade_reduces_betti_pair(self) -> None:
        edge = next(edge for edge in self.target_aug.edges if edge.kind == "space_loop")
        _, record = trade_one_space_loop(self.target_aug, edge.edge_id)
        self.assertEqual((record.after_beta0, record.after_beta1), (2, 5))

    def test_13_all_trades_produce_canonical_target(self) -> None:
        canonical, records = collapse_whitespace_hinges(self.target_aug)
        self.assertEqual(len(records), 2)
        self.assertEqual(canonical.betti_signature(), {"vertices": 12, "edges": 15, "beta0": 1, "beta1": 4, "chi": -3})

    def test_14_source_needs_no_trade(self) -> None:
        canonical, records = collapse_whitespace_hinges(self.source_aug)
        self.assertEqual(records, ())
        self.assertEqual(canonical.betti_signature(), self.source_aug.betti_signature())

    def test_15_canonical_signatures_match(self) -> None:
        source_can, _ = collapse_whitespace_hinges(self.source_aug)
        target_can, _ = collapse_whitespace_hinges(self.target_aug)
        self.assertEqual(source_can.beta0, target_can.beta0)
        self.assertEqual(source_can.beta1, target_can.beta1)
        self.assertEqual(source_can.euler_characteristic, target_can.euler_characteristic)

    def test_16_generic_k_token_formula(self) -> None:
        annotation = RepresentationAnnotation("generic", "a b c d", 19.0, (0, 2))
        transduced = self.profile.transduce(annotation)
        augmented = build_augmented_cell_complex(transduced, self.profile)
        canonical, records = collapse_whitespace_hinges(augmented)
        self.assertEqual((augmented.beta0, augmented.beta1, augmented.euler_characteristic), (4, 5, -1))
        self.assertEqual((canonical.beta0, canonical.beta1, canonical.euler_characteristic), (1, 2, -1))
        self.assertEqual(len(records), 3)

    def test_17_trade_rejects_non_space_edge(self) -> None:
        edge = next(edge for edge in self.target_aug.edges if edge.kind == "symbol_backbone")
        with self.assertRaises(ValueError):
            trade_one_space_loop(self.target_aug, edge.edge_id)

    def test_18_graph_formula_includes_loop_edges(self) -> None:
        graph = CellComplex1D(
            complex_id="g",
            vertices=("v",),
            edges=(CellEdge("loop", "v", "v", "intrinsic_cycle"),),
            representation_id="r",
            transduced_text="x",
            stage="test",
        )
        self.assertEqual((graph.beta0, graph.beta1, graph.euler_characteristic), (1, 1, 0))


class TorusImmersionTests(unittest.TestCase):
    def setUp(self) -> None:
        profile = SyntheticTextProfile()
        source_aug = build_augmented_cell_complex(profile.transduce(SOURCE_ANNOTATION), profile)
        target_aug = build_augmented_cell_complex(profile.transduce(TARGET_ANNOTATION), profile)
        self.source, _ = collapse_whitespace_hinges(source_aug)
        self.target, _ = collapse_whitespace_hinges(target_aug)
        self.profile = profile

    def test_19_source_torus_certificate(self) -> None:
        certificate = build_torus_immersion(self.source, self.profile)
        self.assertTrue(certificate.valid)
        self.assertEqual(certificate.homology_rank, 4)

    def test_20_target_torus_certificate(self) -> None:
        certificate = build_torus_immersion(self.target, self.profile)
        self.assertEqual(certificate.homology_matrix, ((1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)))

    def test_21_coordinate_circle_endpoints_close(self) -> None:
        certificate = build_torus_immersion(self.source, self.profile)
        for index in range(4):
            self.assertEqual(certificate.coordinate_point(index, 0.0), certificate.coordinate_point(index, 1.0))

    def test_22_coordinate_generators_are_distinct(self) -> None:
        certificate = build_torus_immersion(self.source, self.profile)
        points = [certificate.coordinate_point(index, 0.25) for index in range(4)]
        self.assertEqual(len(set(points)), 4)

    def test_23_wrong_cycle_rank_rejected(self) -> None:
        annotation = RepresentationAnnotation("three", "abc", 19.0, (0,1,2))
        augmented = build_augmented_cell_complex(self.profile.transduce(annotation), self.profile)
        canonical, _ = collapse_whitespace_hinges(augmented)
        with self.assertRaises(ValueError):
            build_torus_immersion(canonical, self.profile)


class ParityAndEntropyTests(unittest.TestCase):
    def setUp(self) -> None:
        profile = SyntheticTextProfile()
        self.source = profile.transduce(SOURCE_ANNOTATION).output_text
        self.target = profile.transduce(TARGET_ANNOTATION).output_text
        self.witness = xor_delta_matrix(self.source, self.target)

    def test_24_exact_lengths_and_weights(self) -> None:
        self.assertEqual((self.witness.source_length, self.witness.target_length, self.witness.n), (9,11,11))
        self.assertEqual((self.witness.source_weight, self.witness.target_weight, self.witness.delta_weight), (39,37,38))

    def test_25_even_delta_membership(self) -> None:
        self.assertTrue(even_delta_subspace_member(self.witness.delta))
        self.assertTrue(self.witness.delta_is_even)
        self.assertEqual(self.witness.even_subspace_dimension, 87)

    def test_26_parity_preserved(self) -> None:
        self.assertEqual((self.witness.source_parity, self.witness.target_parity), (1,1))
        self.assertTrue(self.witness.parity_preserved)
        self.assertTrue(xor_translation_preserves_parity(self.witness.source, self.witness.delta))

    def test_27_repeated_symmetric_rows(self) -> None:
        self.assertEqual(self.witness.repeated_row_classes["0x5d"], [3,4])
        self.assertEqual(self.witness.repeated_row_classes["0x5e"], [7,8])
        self.assertTrue(self.witness.satisfies_equal_row_pairs(((3,4),(7,8))))
        self.assertEqual(self.witness.symmetric_subspace_dimension(((3,4),(7,8))), 71)

    def test_28_xor_is_involutive(self) -> None:
        self.assertEqual(self.witness.apply(), self.witness.target)
        self.assertEqual(self.witness.inverse(), self.witness.source)

    def test_29_hamming_weight_not_preserved(self) -> None:
        self.assertNotEqual(self.witness.source_weight, self.witness.target_weight)

    def test_30_even_subspace_closed_under_xor(self) -> None:
        a = bytes([0b00000011])
        b = bytes([0b00001100])
        c = bytes([x ^ y for x, y in zip(a,b)])
        self.assertTrue(even_delta_subspace_member(a))
        self.assertTrue(even_delta_subspace_member(b))
        self.assertTrue(even_delta_subspace_member(c))

    def test_31_odd_delta_flips_parity(self) -> None:
        source = bytes([0])
        delta = bytes([1])
        self.assertFalse(even_delta_subspace_member(delta))
        self.assertFalse(xor_translation_preserves_parity(source, delta))

    def test_32_fixed_translation_is_bijective(self) -> None:
        delta = 0x5D
        image = {value ^ delta for value in range(256)}
        self.assertEqual(len(image), 256)

    def test_33_parity_coset_label(self) -> None:
        self.assertEqual(parity_coset(self.witness.source), 1)
        self.assertEqual(parity_coset(self.witness.target), 1)
        self.assertEqual(bit_weight(self.witness.delta) & 1, bit_parity(self.witness.delta))


class SemanticBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.semantic = SemanticBoundaryProfile(
            profile_id="test",
            values={"a": 19.0, "b": 19.0, "c": 20.0, "d": 17.0},
            target_value=19.0,
        )

    def test_34_semantic_fiber(self) -> None:
        self.assertTrue(self.semantic.equivalent("a", "b"))
        self.assertFalse(self.semantic.equivalent("a", "c"))
        self.assertEqual(set(self.semantic.zero_set()), {"a", "b"})

    def test_35_quotient_metric(self) -> None:
        self.assertEqual(self.semantic.quotient_distance("c", "d"), 3.0)
        self.assertEqual(self.semantic.quotient_distance("a", "b"), 0.0)

    def test_36_spatial_pseudometric_collapses_coordinates(self) -> None:
        p = SemanticPoint("a", (0.0, 0.0))
        q = SemanticPoint("a", (100.0, 200.0))
        self.assertEqual(self.semantic.spatial_pseudodistance(p, q), 0.0)

    def test_37_triangle_inequality(self) -> None:
        a = SemanticPoint("d", ())
        b = SemanticPoint("a", ())
        c = SemanticPoint("c", ())
        self.assertLessEqual(
            self.semantic.spatial_pseudodistance(a, c),
            self.semantic.spatial_pseudodistance(a, b) + self.semantic.spatial_pseudodistance(b, c),
        )

    def test_38_exact_sdf_identity(self) -> None:
        for representation_id in ("a", "b", "c", "d"):
            self.assertTrue(self.semantic.sdf_identity_holds(SemanticPoint(representation_id, (0.0,))))

    def test_39_signed_residual_and_guard(self) -> None:
        self.assertEqual(self.semantic.signed_residual("c"), 1.0)
        self.assertEqual(self.semantic.signed_residual("d"), -2.0)
        self.assertEqual(self.semantic.guard("c", epsilon=0.5), 0.5)
        self.assertLessEqual(self.semantic.guard("a", epsilon=0.0), 0.0)

    def test_40_zero_set_required(self) -> None:
        with self.assertRaises(ValueError):
            SemanticBoundaryProfile("bad", {"c": 20.0}, 19.0)


class IntegrationTests(unittest.TestCase):
    def test_41_end_to_end_certificate(self) -> None:
        certificate = build_synthetic_bea_certificate(SOURCE_ANNOTATION, TARGET_ANNOTATION)
        self.assertTrue(certificate.valid)
        self.assertEqual(certificate.claim_level, "profile-exact-synthetic-topology-equivalence")
        self.assertEqual(certificate.target_augmented["beta1"], 6)
        self.assertEqual(certificate.target_canonical["beta1"], 4)

    def test_42_schema_validation(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(example))
        self.assertEqual(errors, [])

    def test_43_definition_hashes_verify(self) -> None:
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertTrue(all(verify_content_hash(record) for record in example["definitions"]))

    def test_44_substrate_references_and_order(self) -> None:
        substrate = Substrate.load(EXAMPLE)
        self.assertEqual(substrate.schema_version, "3.6.1")
        order = substrate.definition_order()
        self.assertLess(order.index("bea361:op:cell-build-v1"), order.index("bea361:op:space-hole-trade-v1"))
        self.assertLess(order.index("bea361:op:certificate-v2"), order.index("bea361:schedule:handoff-v1"))

    def test_45_runtime_trace(self) -> None:
        substrate = Substrate.load(EXAMPLE)
        trace = SyntheticBEARuntime(substrate).execute_pair(
            "bea361:pipeline:course-corrected-certificate-v2",
            "repr:negentien",
            "repr:no-neg-moat",
        )
        by_kind = {entry.kind: entry.output for entry in trace}
        self.assertTrue(by_kind["betti_pair_certificate"]["chi_conserved"])
        self.assertEqual(by_kind["betti_pair_certificate"]["target_augmented"]["beta1"], 6)
        self.assertTrue(by_kind["even_parity_entropy_certificate"]["parity_preserved"])
        self.assertEqual(by_kind["even_parity_entropy_certificate"]["symmetric_subspace_dimension"], 71)
        self.assertTrue(by_kind["integrated_bea_certificate"]["valid"])

    def test_46_operator_catalog_has_delta_namespace(self) -> None:
        rows = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 30)
        self.assertTrue(all(row["operator_id"].startswith("bea361.") for row in rows))
        self.assertEqual(rows[8]["mechanism"], "Space-Hole Trading Lemma")

    def test_47_attribution_present(self) -> None:
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        attribution = example["metadata"]["requester_attribution"]
        self.assertEqual(attribution["name"], "Tom Klootwijk")
        self.assertEqual(attribution["identifier"], "NL200678942")
        self.assertEqual(attribution["date_of_birth"], "10-07-1990")


if __name__ == "__main__":
    unittest.main()
