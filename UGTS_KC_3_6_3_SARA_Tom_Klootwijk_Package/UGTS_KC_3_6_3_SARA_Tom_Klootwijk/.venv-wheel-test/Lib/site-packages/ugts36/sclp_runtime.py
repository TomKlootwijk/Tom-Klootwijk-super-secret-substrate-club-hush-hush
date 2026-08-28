"""Referential runtime for the UGTS-KC 3.6.2 SCLP example substrate."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .model import Substrate
from .sclp362 import (
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
    RadialTwistBundle,
    SphereRelation,
    TopologicalWrapState,
    certify_linear_cone_sweep,
    release_constraint_row,
    source_width_metrics,
)


@dataclass(frozen=True)
class SCLPTraceEntry:
    step_id: str
    kind: str
    output: Any


class SCLPRuntime:
    def __init__(self, substrate: Substrate):
        self.substrate = substrate
        self._operators: dict[str, Callable[[dict[str, Any], dict[str, Any]], Any]] = {
            "sclp_profile": self._profile,
            "typed_symbol_contract": self._typed_symbols,
            "cone_parameterize": self._cone_parameterize,
            "cone_relation": self._cone_relation,
            "paired_sphere_support": self._paired_sphere_support,
            "logpolar_state": self._logpolar_state,
            "phase_clock": self._phase_clock,
            "quantize_key_fields": self._quantize,
            "pack_contiguous_key": self._pack_contiguous,
            "pack_morton_key": self._pack_morton,
            "radix_prefix_refinement": self._prefix_refinement,
            "one_bit_jitter_guard": self._jitter,
            "source_bundle_twist": self._source_twist,
            "klein_reflective_wrap": self._klein_wrap,
            "missing_shackle_release": self._shackle,
            "hinge_calculus": self._hinge,
            "binary_branch_select": self._branch,
            "bounded_binary_grammar": self._grammar,
            "certified_cone_sweep": self._sweep,
            "compression_audit": self._compression,
            "integrated_sclp_certificate": self._certificate,
            "ugts_event_handoff": self._handoff,
        }

    def execute(self, pipeline_id: str, instance_id: str) -> list[SCLPTraceEntry]:
        pipeline = next((item for item in self.substrate.pipelines if item.get("id") == pipeline_id), None)
        if pipeline is None:
            raise KeyError(pipeline_id)
        instance = next((item for item in self.substrate.instances if item.get("id") == instance_id), None)
        if instance is None:
            raise KeyError(instance_id)
        context: dict[str, Any] = {"instance": instance, "literal": instance["literal"]}
        trace: list[SCLPTraceEntry] = []
        for step_id in pipeline.get("steps", []):
            node = self.substrate.definition(step_id)
            operator = self._operators.get(node.kind)
            if operator is None:
                raise NotImplementedError(node.kind)
            output = operator(context, dict(node.record))
            context[step_id] = output
            context["last"] = output
            trace.append(SCLPTraceEntry(step_id=step_id, kind=node.kind, output=output))
        return trace

    @staticmethod
    def _profile(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        return dict(record.get("parameters", {}))

    @staticmethod
    def _typed_symbols(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        return {
            "T": "cone slant length",
            "t": "linear continuous time",
            "X": "declared modular time tick",
            "phi": "periodic hinge/hoop angle in S1",
            "delta_rho": "log-radius increment",
            "epsilon_guard": "event guard margin",
            "one_bit": "branch/jitter/predicate metadata",
            "golden_ratio": "not used by this delta",
        }

    @staticmethod
    def _cone_parameterize(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        literal = context["literal"]
        data = literal["cone"]
        cone = FiniteCone(
            slant_length=float(data["slant_length"]),
            half_angle=math.radians(float(data["half_angle_deg"])),
            apex=tuple(data.get("apex", (0.0, 0.0, 0.0))),
            axis=tuple(data.get("axis", (0.0, 0.0, 1.0))),
        )
        context["_cone"] = cone
        return {
            "slant_length": cone.slant_length,
            "half_angle_rad": cone.half_angle,
            "height": cone.height,
            "base_radius": cone.base_radius,
            "axis": list(cone.axis),
            "apex": list(cone.apex),
        }

    @staticmethod
    def _cone_relation(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        cone: FiniteCone = context["_cone"]
        point = tuple(context["literal"]["point"])
        epsilon = float(record.get("parameters", {}).get("epsilon", 1e-12))
        residual = cone.signed_distance(point)
        context["_cone_residual"] = residual
        return {
            "point": list(point),
            "signed_distance": residual,
            "relation_class": cone.relation_class(point, epsilon),
            "epsilon": epsilon,
            "exact_for": "finite right circular cone profile",
        }

    @staticmethod
    def _paired_sphere_support(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        data = context["literal"]["paired_spheres"]
        support = PairedSphereSupport(
            SphereRelation(tuple(data["left_center"]), float(data["radius"])),
            SphereRelation(tuple(data["right_center"]), float(data["radius"])),
            mode=str(data.get("mode", "union")),
        )
        output = support.classify(tuple(context["literal"]["point"]))
        context["_support"] = output
        return output

    @staticmethod
    def _logpolar_state(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        data = context["literal"]["logpolar"]
        chart = LogPolarChart(
            r0=float(data.get("r0", 1.0)),
            rho_min=float(data["rho_min"]),
            rho_max=float(data["rho_max"]),
            core_radius=float(data.get("core_radius", 1e-12)),
        )
        point = context["literal"]["point"]
        rho, theta, core = chart.encode(float(point[0]), float(point[1]))
        context["_chart"] = chart
        context["_rho"] = rho
        context["_theta"] = theta
        return {
            "rho": rho,
            "theta": theta,
            "core": core,
            "metric_scale": chart.metric_scale(rho),
            "jacobian": [list(row) for row in chart.jacobian(rho, theta)],
            "delta_r_exact": chart.exact_radial_increment(rho, float(data.get("delta_rho", 1e-3))),
        }

    @staticmethod
    def _phase_clock(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        data = context["literal"]["time"]
        clock = PhaseClock(
            reference_tick=int(data["reference_tick"]),
            period_ticks=int(data["period_ticks"]),
            unit=str(data["unit"]),
        )
        output = clock.state(float(data["tick"]))
        context["_time"] = output
        return output

    @staticmethod
    def _layout(context: dict[str, Any]) -> KeyLayout64:
        if "_layout" not in context:
            chart: LogPolarChart = context["_chart"]
            context["_layout"] = KeyLayout64(rho_min=chart.rho_min, rho_max=chart.rho_max)
        return context["_layout"]

    @classmethod
    def _quantize(cls, context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        layout = cls._layout(context)
        q = layout.quantize(
            context["_rho"],
            context["_theta"],
            context["_time"]["tick"],
            math.radians(float(context["literal"]["hinge"]["phi_deg"])),
        )
        context["_q"] = q
        return q.as_dict()

    @classmethod
    def _pack_contiguous(cls, context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        key = cls._layout(context).pack_contiguous(context["_q"])
        context["_contiguous_key"] = key
        return {"key_u64": key, "hex": f"0x{key:016x}", "layout": "contiguous-fields"}

    @classmethod
    def _pack_morton(cls, context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        layout = cls._layout(context)
        key = layout.pack_morton(context["_q"])
        context["_morton_key"] = key
        return {
            "key_u64": key,
            "hex": f"0x{key:016x}",
            "layout": "msb-round-robin-morton",
            "schedule_prefix": [f"{name}{bit}" for name, bit in layout.morton_schedule()[:16]],
        }

    @classmethod
    def _prefix_refinement(cls, context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        layout = cls._layout(context)
        depth = int(record.get("parameters", {}).get("depth", 12))
        key = context["_morton_key"]
        prefix = key >> (64 - depth)
        bounds = layout.prefix_integer_bounds(prefix, depth)
        return {
            "depth": depth,
            "prefix": prefix,
            "prefix_bits": f"{prefix:0{depth}b}",
            "integer_bounds": {name: list(pair) for name, pair in bounds.items()},
            "semantics": "each appended bit refines one scheduled coordinate interval",
        }

    @staticmethod
    def _jitter(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        data = context["literal"]["jitter"]
        jitter = OneBitJitter(float(data["amplitude"]), float(data["guard_margin"]), str(data["seed"]))
        output = jitter.certificate(
            context["_cone_residual"],
            context["_morton_key"],
            int(context["_time"]["tick"]),
        )
        context["_jitter"] = jitter
        context["_jitter_certificate"] = output
        return output

    @staticmethod
    def _twist_state(context: dict[str, Any]) -> TopologicalWrapState:
        data = context["literal"]["wrap_state"]
        return TopologicalWrapState(
            rho=float(data["rho"]),
            theta=float(data["theta"]),
            phi=math.radians(float(data["phi_deg"])),
            orientation=int(data["orientation"]),
            wrap_count=int(data.get("wrap_count", 0)),
        )

    @classmethod
    def _source_twist(cls, context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        chart: LogPolarChart = context["_chart"]
        bundle = RadialTwistBundle(chart.rho_min, chart.rho_max)
        return bundle.source_half_turn(cls._twist_state(context))

    @classmethod
    def _klein_wrap(cls, context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        chart: LogPolarChart = context["_chart"]
        bundle = RadialTwistBundle(chart.rho_min, chart.rho_max)
        output = bundle.klein_reflection(cls._twist_state(context))
        context["_topology"] = output
        return output

    @staticmethod
    def _shackle(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        data = context["literal"]["constraint"]
        certificate = release_constraint_row(data["jacobian"], int(data["release_row"]))
        output = asdict(certificate)
        context["_shackle"] = output
        return output

    @staticmethod
    def _hinge(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        data = context["literal"]["hinge"]
        state = HingeState(
            phi=math.radians(float(data["phi_deg"])),
            omega=float(data["omega"]),
            alpha=float(data["alpha"]),
        )
        model = LinearHingeModel(
            inertia=float(data["inertia"]),
            damping=float(data["damping"]),
            stiffness=float(data["stiffness"]),
        )
        reflected = state.reflected()
        return {
            "state": asdict(state),
            "torque": model.torque(state),
            "reflected_state": asdict(reflected),
            "reflected_torque": model.torque(reflected),
            "type_rule": "angular acceleration is not torque without a mechanical model",
        }

    @staticmethod
    def _branch(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        threshold = float(record.get("parameters", {}).get("threshold", 0.0))
        residual = float(context["_cone_residual"])
        bit = 0 if residual <= threshold else 1
        context["_branch_bit"] = bit
        return {
            "guard_value": residual,
            "threshold": threshold,
            "branch_bit": bit,
            "classification": "deterministic binary branch; chaos not inferred",
        }

    @staticmethod
    def _grammar(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        data = context["literal"]["grammar"]
        grammar = BoundedBinaryGrammar(
            initial_scale=float(data["initial_scale"]),
            turn_angle=math.radians(float(data["turn_angle_deg"])),
            delta_rho=float(data["delta_rho"]),
            max_depth=int(data["max_depth"]),
            max_symbols=int(data["max_symbols"]),
            max_stack=int(data["max_stack"]),
        )
        depth = int(data["depth"])
        jitter: OneBitJitter = context["_jitter"]
        key = context["_morton_key"]
        tick = int(context["_time"]["tick"])
        bits = [jitter.bit(key, tick + i) for i in range(depth)]
        expansion = grammar.expand(
            bits,
            depth=depth,
            rho=context["_rho"],
            chirality=int(context["_topology"]["orientation"]),
            chart=context["_chart"],
        )
        context["_grammar"] = expansion
        output = expansion.to_dict()
        output["branch_bits"] = bits
        return output

    @staticmethod
    def _sweep(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        data = context["literal"]["sweep"]
        certificate = certify_linear_cone_sweep(
            point=tuple(data["query_point"]),
            cone=context["_cone"],
            segment=LinearSweepSegment(tuple(data["start_offset"]), tuple(data["end_offset"])),
            sample_count=int(data["sample_count"]),
            guard_band=float(data["guard_band"]),
        )
        output = asdict(certificate)
        context["_sweep"] = output
        return output

    @staticmethod
    def _compression(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        layout: KeyLayout64 = context["_layout"]
        return {
            "key_metrics": layout.quantization_metrics(),
            "source_width_metrics": [asdict(metric) for metric in source_width_metrics()],
            "finite_capacity": True,
            "universal_O1_claim": False,
            "infinite_detail_claim": False,
        }

    @staticmethod
    def _certificate(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        q = context["_q"]
        layout: KeyLayout64 = context["_layout"]
        checks = {
            "contiguous_roundtrip": layout.unpack_contiguous(context["_contiguous_key"]) == q,
            "morton_roundtrip": layout.unpack_morton(context["_morton_key"]) == q,
            "layouts_distinct": context["_contiguous_key"] != context["_morton_key"],
            "jitter_within_margin": bool(context["_jitter_certificate"]["safe_under_margin"]),
            "freedom_gain_one": context["_shackle"]["freedom_gain"] == 1,
            "klein_base_non_orientable": bool(context["_topology"]["base_non_orientable"]),
            "grammar_bounded": len(context["_grammar"].symbols) <= int(context["literal"]["grammar"]["max_symbols"]),
            "sweep_interval_ordered": context["_sweep"]["lower_bound"] <= context["_sweep"]["upper_bound"],
        }
        return {
            "profile_id": "sclp362:profile:packed-swept-cone-v1",
            "checks": checks,
            "valid": all(checks.values()),
            "claim_level": "bounded-referential-geometric-topological-integration",
        }

    @staticmethod
    def _handoff(context: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        interval = context["_jitter_certificate"]["interval"]
        support_ok = bool(context["_support"]["admitted"])
        compatibility_ok = int(context["_topology"]["orientation"]) in {-1, 1}
        guard_stable = not (interval[0] <= 0.0 <= interval[1])
        verified = support_ok and compatibility_ok and guard_stable
        return {
            "sequence": ["support", "compatibility", "guard", "verified_event", "transition", "lineage"],
            "support": support_ok,
            "compatibility": compatibility_ok,
            "guard_interval": interval,
            "guard_stable": guard_stable,
            "verified_event": verified,
            "transition": {
                "branch": context["_branch_bit"],
                "orientation": context["_topology"]["orientation"],
                "grammar_state_word_12": context["_grammar"].grammar_state_word_12,
            },
            "lineage": {
                "morton_key_hex": f"0x{context['_morton_key']:016x}",
                "wrap_count": context["_topology"]["wrap_count"],
                "time_winding": context["_time"]["winding"],
            },
        }
