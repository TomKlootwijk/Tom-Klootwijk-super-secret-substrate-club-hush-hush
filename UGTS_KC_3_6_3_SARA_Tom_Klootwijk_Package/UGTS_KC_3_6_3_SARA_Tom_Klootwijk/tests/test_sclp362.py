from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jsonschema import Draft202012Validator

from ugts36 import (
    BoundedBinaryGrammar,
    FiniteCone,
    HingeState,
    KeyLayout64,
    LinearHingeModel,
    LinearSweepSegment,
    LogPolarChart,
    OneBitJitter,
    PairedSphereSupport,
    PhaseClock,
    QuantizedCoordinates,
    RadialTwistBundle,
    SCLPRuntime,
    SparseRadixTrie,
    SphereRelation,
    Substrate,
    TopologicalWrapState,
    build_reference_sclp362_certificate,
    certify_linear_cone_sweep,
    comparable_compression_ratio,
    compile_motion_polyline,
    matrix_rank,
    nullity,
    release_constraint_row,
    source_width_metrics,
    tangent_project_velocity,
    verify_content_hash,
)

EXAMPLE = ROOT / "examples/ugts_kc_3_6_2_sclp_example.json"
SCHEMA = ROOT / "spec/ugts_kc_3_6_2_sclp.schema.json"
CATALOG = ROOT / "spec/sclp_3_6_2_delta_operator_catalog.json"
CLAIMS = ROOT / "spec/sclp_3_6_2_claims_ledger.json"
SCHEDULE = ROOT / "data/sclp362_morton_schedule.json"


class ConeAndSupportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cone = FiniteCone(2.0, math.radians(30.0))

    def test_01_cone_parameterization(self) -> None:
        self.assertAlmostEqual(self.cone.height, math.sqrt(3.0), places=12)
        self.assertAlmostEqual(self.cone.base_radius, 1.0, places=12)

    def test_02_apex_is_zero(self) -> None:
        self.assertAlmostEqual(self.cone.signed_distance((0.0, 0.0, 0.0)), 0.0, places=12)

    def test_03_axis_interior_is_negative(self) -> None:
        self.assertLess(self.cone.signed_distance((0.0, 0.0, self.cone.height / 2.0)), 0.0)

    def test_04_base_rim_is_zero(self) -> None:
        self.assertAlmostEqual(
            self.cone.signed_distance((self.cone.base_radius, 0.0, self.cone.height)),
            0.0,
            places=12,
        )

    def test_05_above_base_is_positive(self) -> None:
        self.assertAlmostEqual(self.cone.signed_distance((0.0, 0.0, self.cone.height + 1.0)), 1.0, places=12)

    def test_06_translation_invariance(self) -> None:
        p = (0.1, 0.2, 0.7)
        offset = (3.0, -2.0, 1.0)
        a = self.cone.signed_distance(p)
        b = self.cone.translated(offset).signed_distance(tuple(p[i] + offset[i] for i in range(3)))
        self.assertAlmostEqual(a, b, places=12)

    def test_07_relation_class(self) -> None:
        self.assertEqual(self.cone.relation_class((0.0, 0.0, 0.0), 1e-12), 0)
        self.assertEqual(self.cone.relation_class((0.0, 0.0, 0.5), 1e-12), -1)
        self.assertEqual(self.cone.relation_class((3.0, 0.0, 0.5), 1e-12), 1)

    def test_08_invalid_cone_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FiniteCone(0.0, math.radians(30.0))
        with self.assertRaises(ValueError):
            FiniteCone(2.0, 0.0)

    def test_09_sphere_relation(self) -> None:
        sphere = SphereRelation((0.0, 0.0, 0.0), 2.0)
        self.assertAlmostEqual(sphere.signed_distance((2.0, 0.0, 0.0)), 0.0)
        self.assertLess(sphere.signed_distance((0.0, 0.0, 0.0)), 0.0)

    def test_10_paired_sphere_union(self) -> None:
        support = PairedSphereSupport(
            SphereRelation((-1.0, 0.0, 0.0), 1.1),
            SphereRelation((1.0, 0.0, 0.0), 1.1),
            "union",
        )
        result = support.classify((-1.0, 0.0, 0.0))
        self.assertTrue(result["admitted"])
        self.assertFalse(result["overlap"])

    def test_11_paired_sphere_intersection(self) -> None:
        support = PairedSphereSupport(
            SphereRelation((-0.5, 0.0, 0.0), 1.0),
            SphereRelation((0.5, 0.0, 0.0), 1.0),
            "intersection",
        )
        self.assertTrue(support.classify((0.0, 0.0, 0.0))["admitted"])
        self.assertFalse(support.classify((-1.4, 0.0, 0.0))["admitted"])


class SweepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cone = FiniteCone(2.0, math.radians(30.0))
        self.segment = LinearSweepSegment((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))

    def test_12_sweep_interval_contains_dense_reference(self) -> None:
        p = (0.45, 0.1, 0.7)
        cert = certify_linear_cone_sweep(p, self.cone, self.segment, sample_count=17)
        dense = min(
            self.cone.translated(self.segment.offset_at(i / 20000)).signed_distance(p)
            for i in range(20001)
        )
        self.assertLessEqual(cert.lower_bound - 1e-12, dense)
        self.assertLessEqual(dense, cert.upper_bound + 1e-12)

    def test_13_more_samples_reduce_error(self) -> None:
        a = certify_linear_cone_sweep((0.5, 0.0, 0.7), self.cone, self.segment, sample_count=9)
        b = certify_linear_cone_sweep((0.5, 0.0, 0.7), self.cone, self.segment, sample_count=65)
        self.assertLess(b.lipschitz_error, a.lipschitz_error)

    def test_14_zero_length_sweep_is_exact(self) -> None:
        segment = LinearSweepSegment((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        p = (0.1, 0.0, 0.5)
        cert = certify_linear_cone_sweep(p, self.cone, segment, sample_count=2)
        self.assertEqual(cert.lipschitz_error, 0.0)
        self.assertAlmostEqual(cert.lower_bound, self.cone.signed_distance(p))
        self.assertAlmostEqual(cert.upper_bound, self.cone.signed_distance(p))

    def test_15_far_point_is_certified_outside(self) -> None:
        cert = certify_linear_cone_sweep((100.0, 0.0, 0.0), self.cone, self.segment, sample_count=9)
        self.assertEqual(cert.status, "certified-outside")

    def test_16_invalid_sample_count(self) -> None:
        with self.assertRaises(ValueError):
            certify_linear_cone_sweep((0.0, 0.0, 0.0), self.cone, self.segment, sample_count=1)


class LogPolarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chart = LogPolarChart()

    def test_17_roundtrip(self) -> None:
        rho, theta, core = self.chart.encode(0.3, -0.4)
        x, y = self.chart.decode(rho, theta)
        self.assertFalse(core)
        self.assertAlmostEqual(x, 0.3, places=12)
        self.assertAlmostEqual(y, -0.4, places=12)

    def test_18_core_flag(self) -> None:
        rho, theta, core = self.chart.encode(0.0, 0.0)
        self.assertTrue(core)
        self.assertEqual(rho, self.chart.rho_min)
        self.assertEqual(theta, 0.0)

    def test_19_metric_scale(self) -> None:
        self.assertAlmostEqual(self.chart.metric_scale(math.log(0.25)), 0.25**2, places=12)

    def test_20_exact_radial_increment(self) -> None:
        rho = math.log(0.5)
        d = 0.1
        exact = self.chart.exact_radial_increment(rho, d)
        self.assertAlmostEqual(exact, 0.5 * (math.exp(d) - 1.0), places=12)

    def test_21_velocity_matches_finite_difference(self) -> None:
        rho, theta = -0.7, 0.4
        rd, td = 0.2, -0.3
        h = 1e-7
        p0 = self.chart.decode(rho, theta)
        p1 = self.chart.decode(rho + rd * h, theta + td * h)
        numeric = ((p1[0] - p0[0]) / h, (p1[1] - p0[1]) / h)
        analytic = self.chart.cartesian_velocity(rho, theta, rd, td)
        self.assertAlmostEqual(numeric[0], analytic[0], places=6)
        self.assertAlmostEqual(numeric[1], analytic[1], places=6)

    def test_22_acceleration_matches_second_difference(self) -> None:
        rho, theta = -0.3, 0.2
        rd, td, rdd, tdd = 0.1, 0.25, -0.05, 0.08
        h = 2e-5

        def position(t: float) -> tuple[float, float]:
            return self.chart.decode(
                rho + rd * t + 0.5 * rdd * t * t,
                theta + td * t + 0.5 * tdd * t * t,
            )

        pm, p0, pp = position(-h), position(0.0), position(h)
        numeric = ((pp[0] - 2 * p0[0] + pm[0]) / h**2, (pp[1] - 2 * p0[1] + pm[1]) / h**2)
        analytic = self.chart.cartesian_acceleration(rho, theta, rd, td, rdd, tdd)
        self.assertAlmostEqual(numeric[0], analytic[0], places=5)
        self.assertAlmostEqual(numeric[1], analytic[1], places=5)

    def test_23_gradient_transform(self) -> None:
        rho, theta = math.log(0.7), 0.6
        x, y = self.chart.decode(rho, theta)
        # f=x^2+y^2=r^2, so f_rho=2r^2 and f_theta=0.
        grad = self.chart.gradient_to_cartesian(rho, theta, 2.0 * (x * x + y * y), 0.0)
        self.assertAlmostEqual(grad[0], 2.0 * x, places=12)
        self.assertAlmostEqual(grad[1], 2.0 * y, places=12)

    def test_24_invalid_chart_range(self) -> None:
        with self.assertRaises(ValueError):
            LogPolarChart(rho_min=0.0, rho_max=0.0)


class JitterClockTopologyTests(unittest.TestCase):
    def test_25_jitter_is_deterministic(self) -> None:
        jitter = OneBitJitter(1e-4, 1e-3, "seed")
        self.assertEqual(jitter.bit(123, 456), jitter.bit(123, 456))

    def test_26_jitter_offset_has_two_values(self) -> None:
        jitter = OneBitJitter(0.25, 1.0, "seed")
        values = {jitter.signed_offset(7, t) for t in range(100)}
        self.assertTrue(values.issubset({-0.25, 0.25}))
        self.assertGreaterEqual(len(values), 1)

    def test_27_jitter_margin_contract(self) -> None:
        self.assertTrue(OneBitJitter(0.1, 0.2).safe_under_margin)
        self.assertFalse(OneBitJitter(0.2, 0.2).safe_under_margin)

    def test_28_jitter_interval(self) -> None:
        self.assertEqual(OneBitJitter(0.1, 0.2).interval(2.0), (1.9, 2.1))

    def test_29_phase_clock_winding(self) -> None:
        state = PhaseClock(reference_tick=100, period_ticks=10, unit="tick").state(135)
        self.assertEqual(state["winding"], 3)
        self.assertAlmostEqual(state["phase_S1"], 0.5)

    def test_30_phase_clock_negative_winding(self) -> None:
        state = PhaseClock(reference_tick=100, period_ticks=10, unit="tick").state(95)
        self.assertEqual(state["winding"], -1)
        self.assertAlmostEqual(state["phase_S1"], 0.5)

    def test_31_source_half_turn_profile_is_not_base_klein(self) -> None:
        bundle = RadialTwistBundle(-2.0, 0.0)
        result = bundle.source_half_turn(TopologicalWrapState(0.25, 0.2, 0.3, 1))
        self.assertFalse(result["base_non_orientable"])
        self.assertTrue(result["source_formula_preserved"])
        self.assertEqual(result["orientation"], -1)

    def test_32_reflective_klein_odd_wrap(self) -> None:
        bundle = RadialTwistBundle(-2.0, 0.0)
        result = bundle.klein_reflection(TopologicalWrapState(0.25, 0.2, 0.3, 1))
        self.assertTrue(result["base_non_orientable"])
        self.assertEqual(result["orientation"], -1)
        self.assertAlmostEqual(result["theta"], math.pi - 0.2, places=12)
        self.assertAlmostEqual(result["phi"], -0.3, places=12)

    def test_33_two_wraps_restore_orientation(self) -> None:
        bundle = RadialTwistBundle(-2.0, 0.0)
        result = bundle.klein_reflection(TopologicalWrapState(2.25, 0.2, 0.3, 1))
        self.assertEqual(result["orientation"], 1)
        self.assertAlmostEqual(result["theta"], 0.2, places=12)
        self.assertAlmostEqual(result["phi"], 0.3, places=12)

    def test_34_invalid_orientation(self) -> None:
        with self.assertRaises(ValueError):
            TopologicalWrapState(0.0, 0.0, 0.0, 0)


class HingeConstraintTests(unittest.TestCase):
    def test_35_hinge_torque_requires_model(self) -> None:
        state = HingeState(phi=0.2, omega=0.3, alpha=0.4)
        model = LinearHingeModel(inertia=2.0, damping=0.5, stiffness=3.0)
        self.assertAlmostEqual(model.torque(state), 2.0 * 0.4 + 0.5 * 0.3 + 3.0 * 0.2)

    def test_36_hinge_reflection(self) -> None:
        state = HingeState(phi=0.2, omega=0.3, alpha=-0.4).reflected()
        self.assertAlmostEqual(state.phi, -0.2)
        self.assertAlmostEqual(state.omega, -0.3)
        self.assertAlmostEqual(state.alpha, 0.4)

    def test_37_matrix_rank_and_nullity(self) -> None:
        matrix = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        self.assertEqual(matrix_rank(matrix), 2)
        self.assertEqual(nullity(matrix), 1)

    def test_38_missing_shackle_freedom_gain(self) -> None:
        cert = release_constraint_row(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), 1)
        self.assertEqual(cert.freedom_gain, 1)
        self.assertEqual(cert.released_nullity, 2)
        self.assertEqual(len(cert.released_basis), 2)

    def test_39_dependent_row_release_gives_no_gain(self) -> None:
        cert = release_constraint_row(((1.0, 0.0), (2.0, 0.0)), 1)
        self.assertEqual(cert.freedom_gain, 0)

    def test_40_tangent_projection(self) -> None:
        projected = tangent_project_velocity((0.0, 0.0, 2.0), (1.0, 2.0, 3.0))
        self.assertAlmostEqual(projected[2], 0.0, places=12)
        self.assertEqual(projected[:2], (1.0, 2.0))


class GrammarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.grammar = BoundedBinaryGrammar(
            initial_scale=1.0,
            turn_angle=math.radians(25),
            delta_rho=0.001,
            max_depth=6,
            max_symbols=10000,
            max_stack=64,
        )

    def test_41_forward_count_doubles(self) -> None:
        expansion = self.grammar.expand([0, 1, 0, 1], depth=4, rho=-1.0)
        self.assertEqual(expansion.forward_count, 16)

    def test_42_chirality_flips_turn_signs(self) -> None:
        plus = self.grammar.expand([0], depth=1, rho=-1.0, chirality=1)
        minus = self.grammar.expand([0], depth=1, rho=-1.0, chirality=-1)
        pturn = next(s.value for s in plus.symbols if s.kind == "TURN")
        mturn = next(s.value for s in minus.symbols if s.kind == "TURN")
        self.assertAlmostEqual(pturn, -mturn)

    def test_43_depth_budget(self) -> None:
        with self.assertRaises(ValueError):
            self.grammar.expand([0] * 7, depth=7, rho=-1.0)

    def test_44_symbol_budget(self) -> None:
        grammar = BoundedBinaryGrammar(1.0, 0.2, 0.001, max_depth=8, max_symbols=20, max_stack=64)
        with self.assertRaises(ValueError):
            grammar.expand([0, 0, 0], depth=3, rho=-1.0)

    def test_45_state_word_is_deterministic(self) -> None:
        a = self.grammar.expand([0, 1], depth=2, rho=-1.0)
        b = self.grammar.expand([0, 1], depth=2, rho=-1.0)
        self.assertEqual(a.grammar_state_word_12, b.grammar_state_word_12)
        self.assertLess(a.grammar_state_word_12, 4096)

    def test_46_compile_polyline(self) -> None:
        expansion = self.grammar.expand([0, 1], depth=2, rho=-1.0)
        points = compile_motion_polyline(expansion)
        self.assertGreater(len(points), expansion.forward_count)
        self.assertEqual(points[0], (0.0, 0.0))


class KeyAndTrieTests(unittest.TestCase):
    def setUp(self) -> None:
        self.layout = KeyLayout64()
        self.q = self.layout.quantize(-2.0, 1.0, 1135, 0.5)

    def test_47_capacity_fields(self) -> None:
        self.assertEqual(self.layout.capacities, {"rho": 1048576, "theta": 262144, "time": 16384, "phi": 4096})
        self.assertEqual(self.layout.state_capacity, 1 << 64)

    def test_48_contiguous_roundtrip(self) -> None:
        key = self.layout.pack_contiguous(self.q)
        self.assertEqual(self.layout.unpack_contiguous(key), self.q)

    def test_49_morton_schedule_prefix(self) -> None:
        self.assertEqual(
            self.layout.morton_schedule()[:4],
            (("rho", 19), ("theta", 17), ("time", 13), ("phi", 11)),
        )
        self.assertEqual(len(self.layout.morton_schedule()), 64)

    def test_50_morton_roundtrip(self) -> None:
        key = self.layout.pack_morton(self.q)
        self.assertEqual(self.layout.unpack_morton(key), self.q)

    def test_51_layouts_are_distinct(self) -> None:
        self.assertNotEqual(self.layout.pack_contiguous(self.q), self.layout.pack_morton(self.q))

    def test_52_prefix_refinement_narrows_one_or_more_fields(self) -> None:
        key = self.layout.pack_morton(self.q)
        p8 = key >> 56
        p9 = key >> 55
        b8 = self.layout.prefix_integer_bounds(p8, 8)
        b9 = self.layout.prefix_integer_bounds(p9, 9)
        widths8 = {k: v[1] - v[0] for k, v in b8.items()}
        widths9 = {k: v[1] - v[0] for k, v in b9.items()}
        self.assertTrue(all(widths9[k] <= widths8[k] for k in widths8))
        self.assertTrue(any(widths9[k] < widths8[k] for k in widths8))

    def test_53_append_prefix_bit(self) -> None:
        self.assertEqual(self.layout.append_prefix_bit(0b101, 3, 1), (0b1011, 4))

    def test_54_quantization_metrics(self) -> None:
        metrics = self.layout.quantization_metrics()
        self.assertAlmostEqual(metrics["theta_step_rad"], 2 * math.pi / 262144, places=15)
        self.assertAlmostEqual(metrics["phi_step_rad"], 2 * math.pi / 4096, places=15)
        self.assertEqual(metrics["keys_per_64_byte_cache_line"], 8)

    def test_55_periodic_quantization(self) -> None:
        a = self.layout.quantize(-2.0, 0.2, 1, 0.3)
        b = self.layout.quantize(-2.0, 0.2 + 2 * math.pi, 1 + 16384, 0.3 + 2 * math.pi)
        self.assertEqual(a, b)

    def test_56_invalid_field_width(self) -> None:
        with self.assertRaises(ValueError):
            self.layout.pack_contiguous(QuantizedCoordinates(1 << 20, 0, 0, 0))

    def test_57_sparse_trie_lookup(self) -> None:
        trie = SparseRadixTrie(8)
        trie.insert(0b10101010, 1)
        self.assertEqual(trie.lookup(0b10101010), 1)
        self.assertIsNone(trie.lookup(0))
        self.assertEqual(trie.path(0b10101010), (1,0,1,0,1,0,1,0))

    def test_58_sparse_trie_storage_lower_bound(self) -> None:
        trie = SparseRadixTrie(4)
        trie.insert(0b0000, 0)
        trie.insert(0b1111, 1)
        metrics = trie.storage_lower_bound_bits()
        self.assertGreater(metrics["topology_presence_min_bits"], trie.leaf_count)
        self.assertEqual(metrics["leaf_payload_bits"], 2)


class MetricAuditTests(unittest.TestCase):
    def test_59_source_width_ratios(self) -> None:
        rows = source_width_metrics()
        self.assertEqual([row.ratio for row in rows[:2]], [3.0, 32.0])
        self.assertAlmostEqual(rows[2].ratio, 42.666666666666664)
        self.assertTrue(all(not row.semantic_equivalence for row in rows))

    def test_60_comparable_ratio(self) -> None:
        self.assertEqual(comparable_compression_ratio(96, 48), 2.0)
        with self.assertRaises(ValueError):
            comparable_compression_ratio(96, 0)


class IntegrationTests(unittest.TestCase):
    def test_61_reference_certificate(self) -> None:
        cert = build_reference_sclp362_certificate()
        self.assertTrue(cert.valid)
        self.assertTrue(cert.keys["layouts_are_distinct"])
        self.assertEqual(cert.shackle["freedom_gain"], 1)
        self.assertEqual(cert.metrics["morton_schedule_length"], 64)

    def test_62_schema_validation(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(example))
        self.assertEqual(errors, [])

    def test_63_definition_hashes(self) -> None:
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertTrue(all(verify_content_hash(record) for record in example["definitions"]))

    def test_64_referential_order(self) -> None:
        substrate = Substrate.load(EXAMPLE)
        self.assertEqual(substrate.schema_version, "3.6.2")
        order = substrate.definition_order()
        self.assertLess(order.index("sclp362:op:cone-parameterize-v1"), order.index("sclp362:op:cone-relation-v1"))
        self.assertLess(order.index("sclp362:op:certificate-v1"), order.index("sclp362:schedule:ugts-handoff-v1"))

    def test_65_runtime_trace(self) -> None:
        substrate = Substrate.load(EXAMPLE)
        trace = SCLPRuntime(substrate).execute(
            "sclp362:pipeline:reference-certificate-v1",
            "sclp362:instance:reference-query-v1",
        )
        self.assertEqual(len(trace), 22)
        outputs = {entry.kind: entry.output for entry in trace}
        self.assertTrue(outputs["integrated_sclp_certificate"]["valid"])
        self.assertEqual(outputs["pack_morton_key"]["schedule_prefix"][:4], ["rho19", "theta17", "time13", "phi11"])
        self.assertEqual(outputs["missing_shackle_release"]["freedom_gain"], 1)
        self.assertEqual(outputs["ugts_event_handoff"]["sequence"][0], "support")

    def test_66_operator_catalog(self) -> None:
        rows = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 50)
        self.assertTrue(all(row["operator_id"].startswith("sclp362.") for row in rows))
        self.assertEqual(rows[5]["mechanism"], "Cone from slant length and half-angle")

    def test_67_claims_ledger(self) -> None:
        rows = json.loads(CLAIMS.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 20)
        self.assertTrue(any(row["disposition"] == "REJECT" for row in rows))
        self.assertTrue(any("infinite detail" in row["source_claim_or_motif"] for row in rows))

    def test_68_morton_schedule_file(self) -> None:
        rows = json.loads(SCHEDULE.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 64)
        self.assertEqual((rows[0]["field"], rows[0]["source_bit"]), ("rho", 19))
        self.assertEqual((rows[3]["field"], rows[3]["source_bit"]), ("phi", 11))

    def test_69_attribution(self) -> None:
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        attribution = example["metadata"]["requester_attribution"]
        self.assertEqual(attribution["name"], "Tom Klootwijk")
        self.assertEqual(attribution["identifier"], "NL200678942")
        self.assertEqual(attribution["date_of_birth"], "10-07-1990")

    def test_70_source_hash(self) -> None:
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(
            example["metadata"]["source"]["sha256"],
            "7e29c1c800d905268f35084a6a4c7d9c1cfed50c926c63a8ec2c79021e32ab63",
        )


if __name__ == "__main__":
    unittest.main()
