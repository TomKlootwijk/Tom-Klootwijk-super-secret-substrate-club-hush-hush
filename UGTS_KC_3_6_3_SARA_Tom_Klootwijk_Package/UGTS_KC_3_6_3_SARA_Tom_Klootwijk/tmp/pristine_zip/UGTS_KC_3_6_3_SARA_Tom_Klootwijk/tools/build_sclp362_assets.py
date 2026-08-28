#!/usr/bin/env python3
"""Build machine-readable UGTS-KC 3.6.2 SCLP delta assets."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts36.canonical import attach_content_hash, canonical_json  # noqa: E402
from ugts36.model import Substrate  # noqa: E402
from ugts36.sclp362 import (  # noqa: E402
    KeyLayout64,
    build_reference_sclp362_certificate,
    source_width_metrics,
)
from ugts36.sclp_runtime import SCLPRuntime  # noqa: E402

SOURCE_NAME = "1855-sdf-with-a-sweeping-cone-analytical-1bit-jitter-with-T-as-side-of-the-pyramid-the-circle-of-the-cone-the-delta-the-sphere-and-change-of-chang.pdf"
SOURCE_SHA256 = "7e29c1c800d905268f35084a6a4c7d9c1cfed50c926c63a8ec2c79021e32ab63"
SOURCE_PAGES = 13


def ensure_dirs() -> None:
    for name in ("spec", "examples", "data", "sources", "report", "report/figures"):
        (ROOT / name).mkdir(parents=True, exist_ok=True)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    if fieldnames is None:
        fieldnames = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def operator_catalog() -> list[dict[str, Any]]:
    rows = [
        ("sclp362.profile.packed-swept-cone-v1", "Profile", "Packed SCLP profile", "Typed finite profile combining a cone relation, log-polar chart, modular time, topology, grammar and two 64-bit key layouts.", "ENGINEERING-DERIVED", "Specified", "pp.9-13"),
        ("sclp362.type.symbol-separation-v1", "Typing", "Overloaded-symbol separation", "T is slant length; t is linear time; X is a modular tick; phi is a hoop angle; delta_rho and epsilon_guard are distinct.", "CORRECTED", "Exact contract", "pp.1-8"),
        ("sclp362.type.lowercase-phi-circle-v1", "Typing", "Lower-case phi as S1 coordinate", "Represent phi as a periodic angle in R/(2pi Z); do not identify it with the golden ratio Phi.", "RETAIN", "Exact", "pp.1,3,7-10"),
        ("sclp362.type.delta-family-v1", "Typing", "Typed delta family", "Separate log-radius increment, time increment, finite-difference step, jitter amplitude and guard margin.", "CORRECTED", "Exact contract", "pp.1-3,7-8"),
        ("sclp362.type.evidence-boundary-v1", "Governance", "Source/normalization boundary", "Every claim is labeled source-derived, corrected, bounded or rejected and carries a profile scope.", "ENGINEERING-DERIVED", "Implemented", "all"),
        ("sclp362.geometry.cone-slant-angle-v1", "Geometry", "Cone from slant length and half-angle", "Given T>0 and alpha in (0,pi/2), derive height h=T cos alpha and base radius R=T sin alpha.", "CORRECTED", "Exact", "p.1"),
        ("sclp362.geometry.finite-cone-sdf-v1", "Geometry", "Exact finite-cone signed distance", "Reduce to signed distance from the meridian point to the filled triangle (-R,h),(R,h),(0,0).", "ENGINEERING-DERIVED", "Implemented", "pp.1,8,10"),
        ("sclp362.geometry.cone-relation-class-v1", "Geometry", "Three-state relation class", "Classify a finite-cone residual as interior, guard-zero or exterior with a declared epsilon.", "RETAIN", "Implemented", "pp.9-10"),
        ("sclp362.geometry.sphere-sdf-v1", "Geometry", "Sphere relation", "Use ||x-c||-R as an exact local spherical relation.", "RETAIN", "Implemented", "p.1"),
        ("sclp362.geometry.paired-sphere-support-v1", "Support", "Two-sphere support pair", "Treat the two-sphered eye motif as two local spherical supports with union/intersection and overlap tags.", "TRANSLATE", "Implemented", "p.1"),
        ("sclp362.sweep.translation-family-v1", "Sweep", "Rigid translational cone family", "C(u)=C0+s(u) with fixed orientation and a declared finite interval.", "TRANSLATE", "Implemented", "pp.1,6-8"),
        ("sclp362.sweep.lipschitz-interval-v1", "Sweep", "Certified sweep interval", "Uniform samples plus the 1-Lipschitz translation law bound the true sweep infimum in [m-Lh/2,m].", "ENGINEERING-DERIVED", "Implemented", "pp.1,6-8"),
        ("sclp362.sweep.zero-tangent-projector-v1", "Kinematics", "Zero-surface tangent projection", "Project a proposed velocity with P=I-n n^T so its first-order field derivative vanishes on a regular zero set.", "TRANSLATE", "Implemented", "pp.3-4"),
        ("sclp362.logpolar.chart-v1", "Coordinates", "Log-polar chart", "rho=ln(r/r0), theta=atan2(y,x) with an explicit core radius.", "RETAIN", "Implemented", "pp.2-3,8-10"),
        ("sclp362.logpolar.core-v1", "Coordinates", "Explicit origin core", "The logarithmic chart does not remove the r=0 singularity; a core flag and radius are mandatory.", "CORRECTED", "Implemented", "p.2"),
        ("sclp362.logpolar.metric-v1", "Metric", "Conformal metric tensor", "In the plane ds^2=r^2(d rho^2+d theta^2), so the metric factor is r^2=e^(2 rho) r0^2.", "ENGINEERING-DERIVED", "Implemented", "pp.2,9-10"),
        ("sclp362.logpolar.exact-radial-step-v1", "Metric", "Exact local radial increment", "A log step delta_rho gives delta_r=r(exp(delta_rho)-1), approximately r delta_rho only to first order.", "CORRECTED", "Implemented", "p.2"),
        ("sclp362.logpolar.jacobian-v1", "Kinematics", "Log-polar Jacobian", "J=r[[cos theta,-sin theta],[sin theta,cos theta]].", "ENGINEERING-DERIVED", "Implemented", "pp.3,8,10"),
        ("sclp362.logpolar.velocity-v1", "Kinematics", "Velocity transform", "v=r(rho_dot e_r+theta_dot e_theta).", "ENGINEERING-DERIVED", "Implemented", "p.3"),
        ("sclp362.logpolar.acceleration-v1", "Kinematics", "Change-of-change transform", "a=r[(rho_ddot+rho_dot^2-theta_dot^2)e_r+(theta_ddot+2 rho_dot theta_dot)e_theta].", "ENGINEERING-DERIVED", "Implemented", "pp.1,3,8,10"),
        ("sclp362.logpolar.gradient-v1", "Metric", "Gradient covector transform", "Cartesian gradient equals (f_rho e_r+f_theta e_theta)/r; physical force scaling still requires a model.", "CORRECTED", "Implemented", "p.10"),
        ("sclp362.jitter.deterministic-bit-v1", "Topology/control", "Deterministic one-bit jitter", "Hash address, time tick and seed to a reproducible bit used as a bounded signed perturbation or selector.", "TRANSLATE", "Implemented", "pp.1-6"),
        ("sclp362.jitter.interval-guard-v1", "Event calculus", "Jitter interval certificate", "Authoritative residual f is enclosed by [f-epsilon_j,f+epsilon_j]; epsilon_j must remain below the event margin.", "CORRECTED", "Implemented", "pp.1-3"),
        ("sclp362.time.phase-clock-v1", "Time", "Linear-time phase clock", "Keep linear time and map it to phase plus integer winding; the source timestamp is profile metadata with a declared unit.", "CORRECTED", "Implemented", "pp.3-5"),
        ("sclp362.time.winding-lineage-v1", "Persistence", "Winding lineage", "Record winding count and parity separately from periodic phase so repeated coordinates retain history.", "TRANSLATE", "Implemented", "pp.3-4"),
        ("sclp362.topology.source-half-turn-v0", "Topology", "Source half-turn bundle twist", "On odd radial wraps apply theta+pi, phi->-phi and orientation flip; base gluing is not itself a Klein quotient.", "RETAIN/BOUND", "Implemented", "pp.9-10"),
        ("sclp362.topology.klein-reflection-v1", "Topology", "Reflective Klein radial gluing", "Use theta->pi-theta plus phi and orientation reversal on odd radial wraps to obtain an orientation-reversing quotient.", "CORRECTED", "Implemented", "pp.2-4,9-10"),
        ("sclp362.topology.tangent-chirality-v1", "Topology", "Tangent chirality map", "The chart transition sends dtheta and dphi to their negatives on odd reflective wraps; it is not a physical impulse.", "ENGINEERING-DERIVED", "Implemented", "pp.4,6,10"),
        ("sclp362.topology.wrap-event-v1", "Event calculus", "Topological wrap event", "Crossing rho_max emits a transition with coordinate map, orientation patch, wrap count and lineage.", "TRANSLATE", "Specified", "pp.2-5,9-11"),
        ("sclp362.hinge.state-v1", "Kinematics", "Hinge state phi, omega, alpha", "Store angle, angular velocity and angular acceleration as separate typed coordinates.", "CORRECTED", "Implemented", "pp.1,3,8,10"),
        ("sclp362.hinge.torque-model-v1", "Kinematics", "Optional physical torque model", "Only after declaring inertia, damping and stiffness may torque be computed as I alpha+c omega+k phi.", "CORRECTED", "Implemented", "pp.1,3,8"),
        ("sclp362.constraint.row-release-v1", "Kinematics", "Missing-shackle row deletion", "Model the missing shackle as removal of one constraint-Jacobian row.", "TRANSLATE", "Implemented", "pp.1,3-6,8-10"),
        ("sclp362.constraint.nullity-gain-v1", "Kinematics", "Freedom-gain certificate", "Compare nullities before and after row deletion; one independent row can add one degree of freedom.", "ENGINEERING-DERIVED", "Implemented", "pp.1,3,8,10"),
        ("sclp362.branch.binary-guard-v1", "Event calculus", "Binary guard branch", "A declared guard partitions state into branch 0 or 1 and selects a transition/grammar rule.", "TRANSLATE", "Implemented", "pp.4-7"),
        ("sclp362.branch.no-chaos-inference-v1", "Audit", "No automatic chaos inference", "Binary branching is deterministic; chaos requires a defined dynamical map and measured sensitivity/Lyapunov evidence.", "CORRECTED", "Enforced", "p.5"),
        ("sclp362.grammar.bounded-binary-lsystem-v1", "Grammar", "Bounded binary parametric L-system", "Each F emits two dyadically scaled branches, a typed turn and jitter token under depth, symbol and stack budgets.", "TRANSLATE", "Implemented", "pp.6-8"),
        ("sclp362.grammar.chirality-automorphism-v1", "Grammar", "Chirality turn automorphism", "A topological orientation flip maps positive turns to negative turns and vice versa.", "RETAIN", "Implemented", "pp.6-7"),
        ("sclp362.packing.quantize-20-18-14-12-v1", "Packing", "20/18/14/12 quantizer", "Quantize rho, theta, modular time and phi into exactly 64 field bits with declared ranges and errors.", "RETAIN/BOUND", "Implemented", "pp.11-13"),
        ("sclp362.packing.contiguous-key-v1", "Packing", "Contiguous field key", "Pack fields into source table ranges [63:44],[43:26],[25:12],[11:0].", "RETAIN", "Implemented", "p.12"),
        ("sclp362.packing.morton-key-v1", "Packing", "MSB round-robin Morton key", "Interleave rho19,theta17,time13,phi11, then continue round-robin until all 64 bits are consumed.", "RETAIN/CLARIFY", "Implemented", "pp.10-12"),
        ("sclp362.packing.layout-separation-v1", "Packing", "Key-layout separation", "The contiguous table and interleaved Morton word are two distinct encodings, never silently treated as the same bit layout.", "CORRECTED", "Implemented", "pp.10-12"),
        ("sclp362.index.prefix-refinement-v1", "Indexing", "Radix prefix refinement", "Appending a bit fixes one scheduled coordinate bit and refines a quantized cell; it does not directly divide rho or theta values.", "CORRECTED", "Implemented", "pp.4-5"),
        ("sclp362.index.radix-trie-v1", "Indexing", "Radix-2 trie terminology", "Use a radix trie over key prefixes rather than calling the structure a comparison-based binary search tree.", "CORRECTED", "Implemented", "pp.1-12"),
        ("sclp362.index.one-bit-payload-v1", "Indexing", "Narrow one-bit payload", "A leaf bit may encode route, occupancy class or predicate result; continuous residual, uncertainty and lineage remain external.", "CORRECTED", "Implemented", "pp.1-2,9-10"),
        ("sclp362.index.sparse-presence-accounting-v1", "Memory", "Sparse presence accounting", "Pointerless sparse storage still needs topology/presence bits and rank/select or equivalent navigation metadata.", "CORRECTED", "Implemented lower bound", "pp.11-12"),
        ("sclp362.metrics.cacheline-eight-keys-v1", "Metrics", "Eight raw keys per cache line", "A 64-byte line stores eight 64-bit keys; this does not imply eight evaluations in one cycle.", "CORRECTED", "Exact capacity", "p.13"),
        ("sclp362.metrics.nominal-width-audit-v1", "Metrics", "Nominal width audit", "Report 3x,32x and 42.666x only as bit-width ratios because the compared records do not preserve equal semantics.", "CORRECTED", "Implemented", "pp.12-13"),
        ("sclp362.metrics.finite-capacity-v1", "Metrics", "Finite 2^64 key capacity", "The 20+18+14+12 profile has exactly 2^64 address combinations, not infinite detail.", "CORRECTED", "Exact", "pp.12-13"),
        ("sclp362.query.direct-lookup-bound-v1", "Query", "Bounded direct lookup", "Fixed-width array/hash lookup may be constant expected RAM access after key construction; traversal, decoding, verification and storage remain costs.", "BOUNDED", "Specified", "pp.7-11"),
        ("sclp362.query.ugts-handoff-v1", "Architecture", "Canonical UGTS handoff", "SCLP outputs feed support, compatibility, guard, verified event, transition and lineage in that order.", "ENGINEERING-DERIVED", "Implemented", "p.9-11"),
    ]
    return [
        {
            "operator_id": op_id,
            "domain": domain,
            "mechanism": mechanism,
            "formal_definition": definition,
            "disposition": disposition,
            "validation": validation,
            "source_scope": source_scope,
        }
        for op_id, domain, mechanism, definition, disposition, validation, source_scope in rows
    ]


def claims_ledger() -> list[dict[str, Any]]:
    rows = [
        ("C362-01", "A side length T alone defines the cone", "CORRECTED", "T is paired with a half-angle; h=T cos alpha and R=T sin alpha."),
        ("C362-02", "The source theta+pi wrap alone is a Klein-bottle base quotient", "BOUNDED", "It is retained as an internal state-bundle half-turn. A reflective theta map is required for the non-orientable base profile."),
        ("C362-03", "Time stops being linear and becomes a loop", "CORRECTED", "Linear time is retained; phase is time modulo a declared period and winding remains separate lineage."),
        ("C362-04", "18:55 is an intrinsic physical constant", "REJECT", "It is a profile seed/reference tick with a declared unit."),
        ("C362-05", "Bit shifting directly halves rho and theta", "CORRECTED", "Appending a trie bit refines one scheduled quantized interval; coordinate values are decoded separately."),
        ("C362-06", "Every branch is chaotic", "REJECT", "A binary branch is deterministic. Chaos requires a specified map and measured sensitivity."),
        ("C362-07", "A missing shackle automatically produces chaos", "CORRECTED", "Constraint-row deletion changes rank/nullity; dynamics require mass, force and damping models."),
        ("C362-08", "All forces automatically scale by e^-rho", "CORRECTED", "Coordinate covectors transform by the inverse Jacobian; physical force laws remain separately typed."),
        ("C362-09", "The sweep field is always an exact SDF", "REJECT", "The report provides an exact cone SDF and a certified interval for the sweep infimum; a generic sweep envelope is not automatically an exact SDF."),
        ("C362-10", "One jitter bit contains roughness, sensor noise and full state", "REJECT", "The bit is a bounded deterministic perturbation or selector; residual, error, topology and lineage remain separate."),
        ("C362-11", "The contiguous bit table is the same as Morton interleaving", "CORRECTED", "Two explicit layouts are supplied and tested independently."),
        ("C362-12", "Pointerless sparse trees have zero metadata", "REJECT", "They avoid explicit child pointers but still require topology/presence and navigation metadata."),
        ("C362-13", "192-to-64 is an equivalent 3:1 compression", "BOUNDED", "It is a nominal width ratio unless decode ranges, errors and semantic equivalence are declared."),
        ("C362-14", "A sign bit is equivalent to a float SDF", "REJECT", "It discards magnitude and uncertainty and needs a separate boundary representation."),
        ("C362-15", "A 12-bit word is equivalent to any 4x4 float matrix", "REJECT", "It can only select a versioned finite codebook/state family."),
        ("C362-16", "Eight keys per cache line means eight outcomes per clock", "REJECT", "Capacity does not establish execution width, latency or instruction throughput."),
        ("C362-17", "Log packing stores infinite detail in finite memory", "REJECT", "The declared profile contains exactly 2^64 keys and finite grammar/state budgets."),
        ("C362-18", "All possible movements are universal O(1)", "REJECT", "Only bounded direct lookup after key construction may be constant expected access; generation, collisions, verification and memory remain."),
        ("C362-19", "L-system recursion is infinite in the substrate", "CORRECTED", "Expansion is finite and rejects depth, symbol or stack overflow."),
        ("C362-20", "Rasterization/raymarching are required", "EXCLUDED", "The 3.6.2 core is purely referential geometry, topology, indexing and event calculus; display remains downstream."),
    ]
    return [{"claim_id": a, "source_claim_or_motif": b, "disposition": c, "technical_boundary": d} for a, b, c, d in rows]


def definitions() -> list[dict[str, Any]]:
    def rec(
        id_: str,
        kind: str,
        domain: str,
        codomain: str,
        phase: int,
        deps: list[str],
        parameters: dict[str, Any],
        note: str,
        refs: list[str],
        provenance_class: str = "engineering-derived",
        invariants: list[str] | None = None,
    ) -> dict[str, Any]:
        return attach_content_hash(
            {
                "id": id_,
                "kind": kind,
                "domain": domain,
                "codomain": codomain,
                "evaluation_phase": phase,
                "dependencies": deps,
                "parameters": parameters,
                "invariants": invariants or [],
                "provenance": {
                    "class": provenance_class,
                    "note": note,
                    "source_refs": refs,
                },
            }
        )

    profile = "sclp362:profile:packed-swept-cone-v1"
    rows = [
        rec(profile, "sclp_profile", "query_literal", "sclp_profile", 0, [], {
            "title": "Swept-Cone Log-Polar Packing",
            "rendering_authority": False,
            "source_sha256": SOURCE_SHA256,
            "source_pages": SOURCE_PAGES,
            "key_bits": {"rho": 20, "theta": 18, "time": 14, "phi": 12},
            "base_version": "3.6.1 BEA course-corrected",
        }, "Versioned SCLP profile.", ["source pp.1-13"], "profile-axiom", ["all operators remain profile-bound"]),
        rec("sclp362:op:typed-symbols-v1", "typed_symbol_contract", "sclp_profile", "typed_symbols", 1, [profile], {}, "Separates T, t, X, phi and the delta family.", ["source pp.1-8"], "corrected"),
        rec("sclp362:op:cone-parameterize-v1", "cone_parameterize", "query_literal", "finite_cone", 2, ["sclp362:op:typed-symbols-v1"], {"parameterization": "T,alpha -> h,R"}, "Finite cone from slant length and half-angle.", ["source p.1"], "corrected", ["T>0", "0<alpha<pi/2"]),
        rec("sclp362:op:cone-relation-v1", "cone_relation", "finite_cone x point", "relation_residual", 3, ["sclp362:op:cone-parameterize-v1"], {"sign": "inside<0,boundary=0,outside>0"}, "Exact finite-cone SDF by meridian reduction.", ["source pp.1,8,10"], "engineering-derived"),
        rec("sclp362:op:paired-sphere-support-v1", "paired_sphere_support", "point", "support_certificate", 3, ["sclp362:op:typed-symbols-v1"], {"mode": "union/intersection"}, "Two-sphere support normalization.", ["source p.1"], "bounded"),
        rec("sclp362:op:logpolar-state-v1", "logpolar_state", "point", "logpolar_metric_state", 3, ["sclp362:op:typed-symbols-v1"], {"rho": "ln(r/r0)", "theta": "atan2(y,x)", "core_required": True}, "Log-polar coordinate and metric record.", ["source pp.2-3,8-10"], "source-derived"),
        rec("sclp362:op:phase-clock-v1", "phase_clock", "linear_time", "phase_winding", 3, ["sclp362:op:typed-symbols-v1"], {"reference": "18:55 -> 1135 declared minutes", "linear_time_retained": True}, "Phase/winding interpretation of the time thread.", ["source pp.3-5"], "corrected"),
        rec("sclp362:op:quantize-key-v1", "quantize_key_fields", "logpolar_metric_state x phase_winding x phi", "quantized_fields", 4, ["sclp362:op:logpolar-state-v1", "sclp362:op:phase-clock-v1"], {"bits": [20, 18, 14, 12]}, "Finite field quantization.", ["source pp.11-13"], "bounded"),
        rec("sclp362:op:contiguous-key-v1", "pack_contiguous_key", "quantized_fields", "u64", 5, ["sclp362:op:quantize-key-v1"], {"ranges": ["63:44", "43:26", "25:12", "11:0"]}, "Contiguous source-table layout.", ["source p.12"], "source-derived"),
        rec("sclp362:op:morton-key-v1", "pack_morton_key", "quantized_fields", "u64", 5, ["sclp362:op:quantize-key-v1"], {"schedule": "MSB round-robin rho,theta,time,phi"}, "Distinct Morton layout.", ["source pp.10-12"], "source-derived"),
        rec("sclp362:op:prefix-refine-v1", "radix_prefix_refinement", "u64", "quantized_cell_bounds", 6, ["sclp362:op:morton-key-v1"], {"depth": 12}, "Bit shift as trie-prefix refinement.", ["source pp.4-5"], "corrected"),
        rec("sclp362:op:jitter-guard-v1", "one_bit_jitter_guard", "relation_residual x u64 x time", "guard_interval", 6, ["sclp362:op:cone-relation-v1", "sclp362:op:morton-key-v1", "sclp362:op:phase-clock-v1"], {"role": "bounded deterministic perturbation"}, "One-bit jitter with error interval.", ["source pp.1-6"], "corrected", ["jitter amplitude below guard margin"]),
        rec("sclp362:op:source-twist-v0", "source_bundle_twist", "wrap_state", "bundle_twist_state", 6, ["sclp362:op:logpolar-state-v1"], {"odd_wrap": "theta+pi,phi->-phi,o->-o"}, "Literal source half-turn bundle twist.", ["source pp.9-10"], "source-derived", ["not named a base Klein quotient"]),
        rec("sclp362:op:klein-wrap-v1", "klein_reflective_wrap", "wrap_state", "klein_state", 6, ["sclp362:op:logpolar-state-v1"], {"odd_wrap": "theta->pi-theta,phi->-phi,o->-o"}, "Orientation-reversing radial gluing.", ["source pp.2-4,9-10"], "corrected", ["odd wrap flips orientation"]),
        rec("sclp362:op:shackle-release-v1", "missing_shackle_release", "constraint_jacobian", "nullity_certificate", 5, ["sclp362:op:typed-symbols-v1"], {"operation": "delete one declared row"}, "Constraint release for missing shackle.", ["source pp.1,3-6,8-10"], "bounded"),
        rec("sclp362:op:hinge-calculus-v1", "hinge_calculus", "hinge_state x model", "torque_and_reflection", 5, ["sclp362:op:typed-symbols-v1"], {"torque": "I alpha+c omega+k phi"}, "Typed hinge kinematics and optional mechanics.", ["source pp.1,3,8,10"], "corrected"),
        rec("sclp362:op:binary-branch-v1", "binary_branch_select", "relation_residual", "branch_bit", 6, ["sclp362:op:cone-relation-v1"], {"threshold": 0.0}, "Deterministic bifurcation selector.", ["source pp.4-7"], "corrected", ["no chaos inference"]),
        rec("sclp362:op:bounded-grammar-v1", "bounded_binary_grammar", "branch_bits x chirality", "grammar_state", 7, ["sclp362:op:binary-branch-v1", "sclp362:op:jitter-guard-v1", "sclp362:op:klein-wrap-v1", "sclp362:op:logpolar-state-v1"], {"budgets": ["max_depth", "max_symbols", "max_stack"]}, "Finite binary parametric L-system.", ["source pp.6-8"], "bounded"),
        rec("sclp362:op:sweep-bound-v1", "certified_cone_sweep", "finite_cone x linear_segment", "sweep_interval", 7, ["sclp362:op:cone-parameterize-v1"], {"bound": "sample_min-L/(2(n-1)) <= inf <= sample_min"}, "Certified translational sweep relation.", ["source pp.1,6-8"], "engineering-derived"),
        rec("sclp362:op:compression-audit-v1", "compression_audit", "key_layout", "metric_ledger", 7, ["sclp362:op:contiguous-key-v1", "sclp362:op:morton-key-v1"], {"semantic_equivalence_required": True}, "Audits source width ratios and finite capacity.", ["source pp.11-13"], "corrected"),
        rec("sclp362:op:certificate-v1", "integrated_sclp_certificate", "all_delta_certificates", "sclp_certificate", 8, [
            "sclp362:op:paired-sphere-support-v1", "sclp362:op:prefix-refine-v1", "sclp362:op:jitter-guard-v1", "sclp362:op:source-twist-v0", "sclp362:op:klein-wrap-v1", "sclp362:op:shackle-release-v1", "sclp362:op:hinge-calculus-v1", "sclp362:op:bounded-grammar-v1", "sclp362:op:sweep-bound-v1", "sclp362:op:compression-audit-v1"
        ], {"claim_level": "bounded-referential-geometric-topological-integration"}, "Integrated profile certificate.", ["source pp.1-13"], "engineering-derived"),
        rec("sclp362:schedule:ugts-handoff-v1", "ugts_event_handoff", "sclp_certificate", "ugts_event_record", 9, ["sclp362:op:certificate-v1", "sclp362:op:binary-branch-v1", "sclp362:op:bounded-grammar-v1"], {"sequence": ["support", "compatibility", "guard", "verified_event", "transition", "lineage"]}, "Returns authority to the canonical UGTS event sequence.", ["base UGTS architecture"], "engineering-derived"),
    ]
    return rows


def example_substrate() -> dict[str, Any]:
    return {
        "$schema": "../spec/ugts_kc_3_6_2_sclp.schema.json",
        "schema_version": "3.6.2",
        "substrate_id": "ugts:kc:3.6.2:sclp:packed-swept-cone-logpolar",
        "metadata": {
            "title": "UGTS-KC 3.6.2 SCLP referential example",
            "description": "Literal integration of swept-cone geometry, log-polar metric calculus, one-bit bounded jitter, radial topological wrapping, finite grammar and two explicit 64-bit key layouts.",
            "evidence_boundary": "Source motifs are retained only under typed finite profiles. No renderer, universal O(1), infinite-detail, physical-chaos or semantically unequal compression claim is made.",
            "revision_status": "delta-over-3.6.1-course-corrected",
            "requester_attribution": {
                "name": "Tom Klootwijk",
                "identifier": "NL200678942",
                "date_of_birth": "10-07-1990",
                "status": "requester-supplied-unverified",
            },
            "source": {
                "descriptive_name": SOURCE_NAME,
                "sha256": SOURCE_SHA256,
                "pages": SOURCE_PAGES,
                "redistributed": False,
            },
        },
        "definitions": definitions(),
        "instances": [
            {
                "id": "sclp362:instance:reference-query-v1",
                "definition_ref": "sclp362:profile:packed-swept-cone-v1",
                "literal": {
                    "point": [0.15, 0.0, 0.6],
                    "cone": {
                        "slant_length": 2.0,
                        "half_angle_deg": 30.0,
                        "apex": [0.0, 0.0, 0.0],
                        "axis": [0.0, 0.0, 1.0],
                    },
                    "paired_spheres": {
                        "left_center": [-0.25, 0.0, 0.5],
                        "right_center": [0.25, 0.0, 0.5],
                        "radius": 0.55,
                        "mode": "union",
                    },
                    "logpolar": {
                        "r0": 1.0,
                        "rho_min": -20.0,
                        "rho_max": 0.0,
                        "core_radius": 1e-12,
                        "delta_rho": 0.001,
                    },
                    "time": {
                        "tick": 1920,
                        "reference_tick": 1135,
                        "period_ticks": 256,
                        "unit": "minute",
                        "reference_label": "18:55",
                    },
                    "hinge": {
                        "phi_deg": 20.0,
                        "omega": 0.2,
                        "alpha": -0.05,
                        "inertia": 2.0,
                        "damping": 0.1,
                        "stiffness": 0.5,
                    },
                    "jitter": {
                        "amplitude": 0.0001,
                        "guard_margin": 0.001,
                        "seed": "sclp362-reference",
                    },
                    "wrap_state": {
                        "rho": 0.25,
                        "theta": 0.3,
                        "phi_deg": 20.0,
                        "orientation": 1,
                        "wrap_count": 0,
                    },
                    "constraint": {
                        "jacobian": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                        "release_row": 1,
                    },
                    "grammar": {
                        "initial_scale": 1.0,
                        "turn_angle_deg": 25.0,
                        "delta_rho": 0.001,
                        "depth": 4,
                        "max_depth": 6,
                        "max_symbols": 20000,
                        "max_stack": 64,
                    },
                    "sweep": {
                        "query_point": [0.5, 0.0, 0.6],
                        "start_offset": [0.0, 0.0, 0.0],
                        "end_offset": [0.75, 0.0, 0.0],
                        "sample_count": 65,
                        "guard_band": 0.001,
                    },
                },
                "state": {
                    "profile_ref": "sclp362:profile:packed-swept-cone-v1",
                    "base_substrate": "UGTS-KC 3.6.1 BEA course-corrected",
                },
            }
        ],
        "pipelines": [
            {
                "id": "sclp362:pipeline:reference-certificate-v1",
                "description": "Build the typed SCLP certificate and hand it to the canonical UGTS event sequence.",
                "steps": [
                    "sclp362:profile:packed-swept-cone-v1",
                    "sclp362:op:typed-symbols-v1",
                    "sclp362:op:cone-parameterize-v1",
                    "sclp362:op:cone-relation-v1",
                    "sclp362:op:paired-sphere-support-v1",
                    "sclp362:op:logpolar-state-v1",
                    "sclp362:op:phase-clock-v1",
                    "sclp362:op:quantize-key-v1",
                    "sclp362:op:contiguous-key-v1",
                    "sclp362:op:morton-key-v1",
                    "sclp362:op:prefix-refine-v1",
                    "sclp362:op:jitter-guard-v1",
                    "sclp362:op:source-twist-v0",
                    "sclp362:op:klein-wrap-v1",
                    "sclp362:op:shackle-release-v1",
                    "sclp362:op:hinge-calculus-v1",
                    "sclp362:op:binary-branch-v1",
                    "sclp362:op:bounded-grammar-v1",
                    "sclp362:op:sweep-bound-v1",
                    "sclp362:op:compression-audit-v1",
                    "sclp362:op:certificate-v1",
                    "sclp362:schedule:ugts-handoff-v1",
                ],
            }
        ],
        "queries": [
            {"id": "sclp362:query:certificate", "kind": "integrated-certificate"},
            {"id": "sclp362:query:definition-order", "kind": "definition-order"},
        ],
    }


def schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:ugts-kc:3.6.2:sclp",
        "title": "UGTS-KC 3.6.2 SCLP Substrate",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "substrate_id", "metadata", "definitions", "instances", "pipelines"],
        "properties": {
            "$schema": {"type": "string"},
            "schema_version": {"const": "3.6.2"},
            "substrate_id": {"type": "string", "pattern": "^[A-Za-z0-9:._/-]+$"},
            "metadata": {
                "type": "object",
                "additionalProperties": True,
                "required": ["title", "description", "evidence_boundary", "revision_status", "requester_attribution", "source"],
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "description": {"type": "string", "minLength": 1},
                    "evidence_boundary": {"type": "string", "minLength": 1},
                    "revision_status": {"const": "delta-over-3.6.1-course-corrected"},
                    "requester_attribution": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["name", "identifier", "date_of_birth", "status"],
                        "properties": {
                            "name": {"const": "Tom Klootwijk"},
                            "identifier": {"const": "NL200678942"},
                            "date_of_birth": {"const": "10-07-1990"},
                            "status": {"const": "requester-supplied-unverified"},
                        },
                    },
                    "source": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["descriptive_name", "sha256", "pages", "redistributed"],
                        "properties": {
                            "descriptive_name": {"type": "string"},
                            "sha256": {"const": SOURCE_SHA256},
                            "pages": {"const": SOURCE_PAGES},
                            "redistributed": {"const": False},
                        },
                    },
                },
            },
            "definitions": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/definition"}},
            "instances": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/instance"}},
            "pipelines": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/pipeline"}},
            "queries": {"type": "array", "items": {"type": "object", "required": ["id", "kind"], "additionalProperties": True}},
        },
        "$defs": {
            "id": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9:._/-]*$"},
            "definition": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "kind", "domain", "codomain", "evaluation_phase", "dependencies", "parameters", "invariants", "provenance", "content_hash"],
                "properties": {
                    "id": {"$ref": "#/$defs/id"},
                    "kind": {"type": "string", "minLength": 1},
                    "domain": {"type": "string", "minLength": 1},
                    "codomain": {"type": "string", "minLength": 1},
                    "evaluation_phase": {"type": "integer", "minimum": 0, "maximum": 12},
                    "dependencies": {"type": "array", "uniqueItems": True, "items": {"$ref": "#/$defs/id"}},
                    "parameters": {"type": "object", "additionalProperties": True},
                    "invariants": {"type": "array", "items": {"type": "string"}},
                    "provenance": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["class", "note", "source_refs"],
                        "properties": {
                            "class": {"enum": ["source-derived", "profile-axiom", "engineering-derived", "corrected", "bounded"]},
                            "note": {"type": "string"},
                            "source_refs": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "content_hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                },
            },
            "instance": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "definition_ref", "literal", "state"],
                "properties": {
                    "id": {"$ref": "#/$defs/id"},
                    "definition_ref": {"$ref": "#/$defs/id"},
                    "literal": {"type": "object", "additionalProperties": True, "required": ["point", "cone", "logpolar", "time", "hinge", "jitter", "wrap_state", "constraint", "grammar", "sweep"]},
                    "state": {"type": "object", "additionalProperties": True, "required": ["profile_ref"]},
                },
            },
            "pipeline": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "description", "steps"],
                "properties": {
                    "id": {"$ref": "#/$defs/id"},
                    "description": {"type": "string"},
                    "steps": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"$ref": "#/$defs/id"}},
                },
            },
        },
    }


def source_distillation() -> str:
    return f"""# Source distillation for UGTS-KC 3.6.2 SCLP

## Source register

- Descriptive file: `{SOURCE_NAME}`
- SHA-256: `{SOURCE_SHA256}`
- Length: {SOURCE_PAGES} pages
- Raw source PDF is not redistributed in this package.

## Source-derived mechanism groups

1. **Geometric relation family (pp. 1-2):** finite cone/pyramidal side `T`, circular base, sphere relations, SDF zero, a sweeping path, deterministic one-bit jitter and a log-polar chart.
2. **Kinematic and topological state (pp. 1-5):** lower-case phi as a hoop angle, angular acceleration as "change of change", a missing-shackle constraint break, time-to-phase winding, chirality inversion and a radial wrap motif.
3. **Branching grammar (pp. 4-8):** bit-shifted tree traversal, binary bifurcation, a context-dependent L-system, branch-conditioned turn signs and an instantaneous state lookup proposal.
4. **Pure substrate restatement (pp. 9-11):** no rasterization/raymarching/rendering; use a one-bit radix structure, a topological state flag, a twist operator, a static typed tensor record and a query path.
5. **Bit allocation and memory claims (pp. 11-13):** 20/18/14/12 field widths, a 64-bit key, a Morton-style interleave, pointerless bit vectors and proposed width/compression metrics.

## Formal normalization

- `T` is paired with a half-angle; a side length alone does not determine a cone.
- The finite cone receives an exact signed-distance definition. The continuous sweep receives a certified interval rather than an unsupported universal exact-SDF claim.
- `rho=ln(r/r0)` is equipped with its metric, Jacobian, exact radial step, velocity, acceleration and gradient transforms.
- The source `theta+pi, phi->-phi` formula is retained as a half-turn **state-bundle twist**. A separate reflective `theta->pi-theta` profile supplies a genuine non-orientable Klein base gluing.
- Time remains linear. A declared 18:55 reference maps to a periodic phase plus an integer winding count.
- The missing shackle is a constraint-Jacobian row deletion with a rank/nullity certificate.
- A bit shift appends a radix-trie prefix bit and refines a scheduled quantized coordinate interval. It does not directly halve physical coordinates.
- The L-system is finite and budgeted.
- The contiguous bit table and Morton interleave are separate 64-bit layouts.
- The source ratios 3:1, 32:1 and 42.6:1 are recorded as nominal width ratios, not semantically equivalent compression claims.

## Excluded escalation

The delta does not claim universal O(1), infinite detail, physical chaos, zero metadata, one-bit complete state, eight evaluations per clock, or renderer authority. It does not use historical or dialect material.
"""


def formal_definition() -> str:
    return r"""# UGTS-KC 3.6.2 SCLP - Formal Definition

**Version:** 3.6.2  
**SCLP:** Swept-Cone Log-Polar Packing  
**Requester-supplied attribution:** Tom Klootwijk, 10-07-1990, NL200678942 (not independently verified).

## 1. Scope and authoritative object

Version 3.6.2 is a referential delta over the course-corrected 3.6.1 BEA substrate. The attached source is treated as a source of geometric, topological, kinematic, grammar and packing operators. Rasterization, ray marching and display are outside the authoritative core.

The SCLP state is typed:

\[
q=(x,t,\rho,\theta,\phi,\dot\phi,\ddot\phi,o,s,b,\omega_L,K,a,\mathcal L,u),
\]

where `x` is position, `t` is linear time, `(rho,theta)` is a local log-polar chart, `phi` is a periodic hinge angle, `o` is orientation, `s` a sheet, `b` a branch bit, `omega_L` a bounded grammar-state word, `K` a 64-bit key, `a` a generative address, `L` lineage and `u` uncertainty.

## 2. Finite cone relation

Let `T>0` be slant length and `alpha in (0,pi/2)` the half-angle. Define

\[
h=T\cos\alpha,\qquad R=T\sin\alpha.
\]

For apex `c` and unit axis `a`, write

\[
z=a\cdot(x-c),\qquad q=\|(x-c)-za\|.
\]

The exact Euclidean signed distance is the signed distance from `(q,z)` to the filled meridian triangle with vertices `(-R,h),(R,h),(0,0)`. Interior is `0<=z<=h` and `q<=z tan(alpha)`.

A sphere relation is `f_S(x)=||x-c_S||-R_S`. Two sphere relations may form a union/intersection support certificate.

## 3. Swept relation with a certified bound

For a fixed-orientation translation `s(u)`, `u in [0,1]`, define the sweep relation

\[
F_{\rm sweep}(x)=\inf_{u\in[0,1]} d_C(x-s(u)).
\]

For a linear segment of length `L`, `n>=2` uniform samples and sample minimum `m_n`, the signed-distance translation law gives

\[
m_n-\frac{L}{2(n-1)}\le F_{\rm sweep}(x)\le m_n.
\]

This interval is the reference certificate. It does not claim that every sweep envelope is itself an exact SDF.

## 4. Log-polar metric and change-of-change

With `r=r0 exp(rho)`:

\[
x=r\cos\theta,\qquad y=r\sin\theta,
\]

\[
ds^2=r^2(d\rho^2+d\theta^2),\qquad
J=r\begin{bmatrix}\cos\theta&-\sin\theta\\\sin\theta&\cos\theta\end{bmatrix}.
\]

An exact log-radius increment is

\[
\Delta r=r(e^{\Delta\rho}-1).
\]

Velocity and acceleration are

\[
v=r(\dot\rho e_r+\dot\theta e_\theta),
\]

\[
a=r[(\ddot\rho+\dot\rho^2-\dot\theta^2)e_r+(\ddot\theta+2\dot\rho\dot\theta)e_\theta].
\]

The Cartesian gradient is `(f_rho e_r+f_theta e_theta)/r`. A physical force law remains separately typed.

## 5. One-bit jitter contract

A deterministic bit `b=H(seed,K,X) mod 2` yields `sigma=2b-1`. The optional perturbation is

\[
f_j=f+\epsilon_j\sigma.
\]

The authoritative residual is enclosed by `[f-epsilon_j,f+epsilon_j]`. The profile is valid only when `epsilon_j` lies below the declared guard margin and cannot change verified event ordering.

## 6. Time, winding and topological wrapping

Linear time is not replaced. A declared reference tick `X0` and period `P` define

\[
u=(X-X_0)/P,\qquad w=\lfloor u\rfloor,\qquad \psi=u-w\in[0,1).
\]

The source half-turn bundle twist on odd radial wraps is

\[
(\rho,\theta,\phi,o)\mapsto(\rho',\theta+\pi,-\phi,-o).
\]

It is retained as an internal state-bundle map. The orientation-reversing Klein profile uses

\[
(\rho,\theta,\phi,o)\mapsto(\rho',\pi-\theta,-\phi,-o)
\]

on odd wraps, with angular periodicity on the other boundary. Winding count and wrap count are lineage.

## 7. Hinge and missing-shackle calculus

The hinge state is `(phi,omega,alpha)`. Torque is only defined after a mechanical model is selected, for example

\[
\tau=I\alpha+c\omega+k\phi.
\]

Let a holonomic velocity constraint be `A(q) qdot=0`. Removing the declared shackle row gives `A'`. The freedom gain is

\[
\Delta d=\operatorname{nullity}(A')-\operatorname{nullity}(A).
\]

No chaos follows from this rank change alone.

For a regular zero surface with normal `n`, a proposed velocity can be projected into the tangent space by `P_T=I-nn^T`.

## 8. Binary branch and finite grammar

A guard produces a branch bit `b in {0,1}` and selects a declared transition or grammar production. Binary branching is not automatically chaotic.

The reference grammar expands each `F(T)` into two `F(T/2)` branches with a signed turn, stack delimiters and a metric-aware jitter token. Expansion is rejected when depth, symbol or stack budgets are exceeded. A topological chirality flip acts by the automorphism `+ <-> -` on turn commands.

## 9. 64-bit keys

The field widths are

| field | bits | states |
|---|---:|---:|
| rho | 20 | 1,048,576 |
| theta | 18 | 262,144 |
| X | 14 | 16,384 |
| phi | 12 | 4,096 |

Two layouts are explicit:

1. **Contiguous:** `[63:44]=rho`, `[43:26]=theta`, `[25:12]=X`, `[11:0]=phi`.
2. **Morton:** MSB round-robin `rho19,theta17,X13,phi11,...` until all field bits are consumed.

A radix-trie shift appends one key-prefix bit. It refines the corresponding scheduled field interval. It does not directly divide the physical coordinate.

The finite key space contains exactly `2^64` combinations.

## 10. Memory and metric discipline

Pointerless does not mean metadata-free. A sparse trie needs topology/presence bits plus navigation support. Eight raw 64-bit keys fit in a 64-byte cache line, but no execution-width or one-cycle claim follows.

The source widths `192/64=3`, `32/1=32` and `512/12=42.666...` are nominal ratios only. They become valid compression metrics only when both records preserve the same semantics under a declared reconstruction/error contract.

## 11. Referential handoff

The 3.6.2 delta produces typed support, relation, topology, branch, grammar, key and uncertainty records. Authority then returns to

\[
\text{support}\to\text{compatibility}\to\text{guard}\to\text{verified event}\to\text{transition}\to\text{lineage}.
\]
"""


def key_data() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    layout = KeyLayout64()
    fields = [
        {"field": "rho", "bits": 20, "contiguous_range": "63:44", "states": 1 << 20, "range": "[-20,0]", "step": (20.0 / ((1 << 20) - 1))},
        {"field": "theta", "bits": 18, "contiguous_range": "43:26", "states": 1 << 18, "range": "[0,2pi)", "step": 2 * math.pi / (1 << 18)},
        {"field": "time", "bits": 14, "contiguous_range": "25:12", "states": 1 << 14, "range": "modular ticks", "step": 1},
        {"field": "phi", "bits": 12, "contiguous_range": "11:0", "states": 1 << 12, "range": "[0,2pi)", "step": 2 * math.pi / (1 << 12)},
    ]
    schedule = [
        {"output_position_msb0": i, "output_bit": 63 - i, "field": name, "source_bit": bit}
        for i, (name, bit) in enumerate(layout.morton_schedule())
    ]
    return fields, schedule


def source_register() -> dict[str, Any]:
    return {
        "version": "3.6.2",
        "records": [
            {
                "source_id": "SCLP362-S11",
                "descriptive_name": SOURCE_NAME,
                "sha256": SOURCE_SHA256,
                "pages": SOURCE_PAGES,
                "role": "Swept cone, log-polar metric, time/phase, topology, finite grammar, 64-bit packing and compression motifs.",
                "redistributed": False,
            },
            {
                "source_id": "BASE-361",
                "descriptive_name": "UGTS-KC 3.6.1 BEA Course-Corrected package",
                "role": "Immediate formal baseline and referential registry inherited by 3.6.2.",
                "redistributed": True,
            },
        ],
    }


def build() -> None:
    ensure_dirs()
    ops = operator_catalog()
    claims = claims_ledger()
    example = example_substrate()
    schema_value = schema()
    fields, schedule = key_data()
    certificate = build_reference_sclp362_certificate().to_dict()

    write_json(ROOT / "spec/sclp_3_6_2_delta_operator_catalog.json", ops)
    write_csv(ROOT / "spec/sclp_3_6_2_delta_operator_catalog.csv", ops)
    write_json(ROOT / "spec/sclp_3_6_2_claims_ledger.json", claims)
    write_csv(ROOT / "spec/sclp_3_6_2_claims_ledger.csv", claims)
    write_json(ROOT / "spec/ugts_kc_3_6_2_sclp.schema.json", schema_value)
    write_json(ROOT / "examples/ugts_kc_3_6_2_sclp_example.json", example)
    write_json(ROOT / "data/sclp362_key_layout.json", fields)
    write_csv(ROOT / "data/sclp362_key_layout.csv", fields)
    write_json(ROOT / "data/sclp362_morton_schedule.json", schedule)
    write_csv(ROOT / "data/sclp362_morton_schedule.csv", schedule)
    write_json(ROOT / "data/sclp362_reference_certificate.json", certificate)
    write_json(ROOT / "data/sclp362_source_width_metrics.json", [asdict(row) for row in source_width_metrics()])
    (ROOT / "sources/SRC_SCLP_3_6_2_DISTILLATION.md").write_text(source_distillation(), encoding="utf-8")
    write_json(ROOT / "sources/source_register_3_6_2_sclp.json", source_register())
    (ROOT / "spec/SCLP_3_6_2_FORMAL_DEFINITION.md").write_text(formal_definition(), encoding="utf-8")

    substrate = Substrate.from_dict(example)
    runtime = SCLPRuntime(substrate)
    trace = runtime.execute("sclp362:pipeline:reference-certificate-v1", "sclp362:instance:reference-query-v1")
    trace_json = [{"step_id": entry.step_id, "kind": entry.kind, "output": entry.output} for entry in trace]
    write_json(ROOT / "examples/demo_sclp362_trace.json", trace_json)
    write_json(ROOT / "examples/demo_sclp362_output.json", trace_json[-1]["output"])

    print(f"operators={len(ops)} definitions={len(example['definitions'])} trace_steps={len(trace_json)}")


if __name__ == "__main__":
    build()
