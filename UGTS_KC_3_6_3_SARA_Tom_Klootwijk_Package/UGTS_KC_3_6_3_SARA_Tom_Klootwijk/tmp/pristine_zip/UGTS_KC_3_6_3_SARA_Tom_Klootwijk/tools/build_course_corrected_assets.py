#!/usr/bin/env python3
"""Generate the BEA 3.6.1 course-corrected catalogs, example and tables."""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ugts36.bea_synthetic import (  # noqa: E402
    SOURCE_ANNOTATION,
    TARGET_ANNOTATION,
    SyntheticTextProfile,
    build_synthetic_bea_certificate,
)
from ugts36.canonical import attach_content_hash  # noqa: E402


def operator_rows() -> list[dict[str, str]]:
    S = "source PDF pp.1-5"
    P = "course-correction profile prompt"
    rows = [
        ("BEA361-D001", "bea361.profile.synthetic-text-v2", "Profile", "Synthetic text representation profile", "P=(Sigma,N,tau,L,w,T4,nu) fixes normalization, provenance transduction, explicit cycle annotations, zero-metric whitespace hinges, torus dimension 4 and target value 19.", P, "PROFILE-AXIOM", "Valid only inside the named profile; not standard font topology.", "Schema + constructor tests"),
        ("BEA361-D002", "bea361.normalize.canonical-space-v1", "Representation", "Canonical whitespace normalization", "N lowercases, applies NFC and reduces every non-empty whitespace run to one separator while preserving separator count after normalization.", P, "ENGINEERING", "Positional cycle annotations require unchanged layout.", "Unit tests"),
        ("BEA361-D003", "bea361.transduce.leet-provenance-v1", "Encoding", "Leet transducer with provenance", "tau maps a->4, e->3, i->1, o->0 while retaining each source index and source symbol as cell provenance.", S, "SOURCE-DERIVED", "Finite versioned map; not a universal leet alphabet.", "Exact pair reproduction"),
        ("BEA361-D004", "bea361.cell.token-path-v1", "Cell complex", "Token backbone path", "Each token of m symbols becomes a path with m edges and m+1 vertices; separate tokens begin as distinct components.", P, "PROFILE-AXIOM", "One-dimensional CW model only.", "Graph count tests"),
        ("BEA361-D005", "bea361.cell.intrinsic-cycle-annotation-v1", "Cell complex", "Profile-annotated intrinsic cycle", "Each declared cycle position adds one loop 1-cell at the symbol anchor. The source and target records each declare exactly four positions.", S + "; " + P, "PROFILE-AXIOM", "Annotations are explicit data, not inferred glyph counters.", "beta1=4 after canonical gluing"),
        ("BEA361-D006", "bea361.cell.whitespace-space-loop-v1", "Cell complex", "Whitespace as zero-metric space loop", "Each token boundary contributes one zero-metric loop edge at the right endpoint of the preceding token, tagged with the next token's entry vertex.", S + "; " + P, "PROFILE-AXIOM", "Pseudometric weight zero does not remove the topological cell.", "Target pre-gluing beta1=6"),
        ("BEA361-D007", "bea361.topology.betti-graph-v1", "Topology", "Finite-graph Betti evaluator", "For finite graph X, beta0 is the component count and beta1=E-V+beta0, with loop edges included.", P, "ENGINEERING", "Graph/CW complexes only.", "Exact formula tests"),
        ("BEA361-D008", "bea361.topology.euler-characteristic-v1", "Topology", "Euler characteristic evaluator", "chi(X)=V-E=beta0-beta1.", S + "; " + P, "SOURCE-DERIVED", "No planar-renderer interpretation is imported.", "Exact formula tests"),
        ("BEA361-D009", "bea361.hinge.space-hole-trade-v1", "Topology", "Space-Hole Trading Lemma", "Replace a loop edge (u,u) by a bridge (u,v) to a distinct component. V and E stay fixed; beta0 and beta1 both decrease by one; chi is conserved.", S + "; " + P, "PROFILE-AXIOM", "Requires v in a different component and an actual loop edge.", "Proof + executable tests"),
        ("BEA361-D010", "bea361.hinge.zero-metric-bridge-v1", "Metric topology", "Zero-width pathway realization", "The traded separator becomes a bridge with metric weight 0. It joins components topologically while collapsing its metric length in the profile pseudometric.", P, "PROFILE-AXIOM", "Weighted algorithms must accept a pseudometric.", "Edge metadata tests"),
        ("BEA361-D011", "bea361.hinge.iterated-space-collapse-v1", "Topology", "Iterated whitespace collapse", "Apply the Space-Hole trade once per separator. For k tokens and h intrinsic cycles, (beta0,beta1)=(k,h+k-1) becomes (1,h) with chi=1-h throughout.", P, "ENGINEERING", "Separator adjacency must be a tree/order chain.", "Generic k-token tests"),
        ("BEA361-D012", "bea361.torus.spanning-tree-collapse-v1", "Algebraic topology", "Cycle-quotient tree collapse", "Collapse the canonical backbone/bridge spanning tree T, obtaining X/T homeomorphic to a wedge of beta1 circles.", P, "ENGINEERING", "The quotient, not the uncollapsed tree, is the immersion domain.", "Symbolic certificate"),
        ("BEA361-D013", "bea361.torus.cycle-basis-four-v1", "Algebraic topology", "Ordered four-cycle basis", "When beta1=4, order the four intrinsic loop edges by profile cycle index to obtain c1,...,c4 and H1(X/T;Z)=Z^4.", S + "; " + P, "PROFILE-AXIOM", "Reject if canonical beta1 is not exactly four.", "Rank tests"),
        ("BEA361-D014", "bea361.torus.coordinate-circle-immersion-v1", "Algebraic topology", "Synthetic T4 coordinate immersion", "Map cj(t) to the jth coordinate circle in T_syn^4=(R/Z)^4; all four cycle generators have winding vectors e_j.", P, "PROFILE-AXIOM", "Image is the union of four coordinate circles, not the full torus.", "Endpoint/coordinate tests"),
        ("BEA361-D015", "bea361.torus.homology-rank-certificate-v1", "Algebraic topology", "Torus homology certificate", "The induced H1 matrix is I4 and has rank 4.", P, "ENGINEERING", "Certifies generator alignment, not homeomorphism to T4.", "Matrix rank test"),
        ("BEA361-D016", "bea361.bits.ascii-fixed-width-v1", "Binary encoding", "ASCII byte profile", "Encode the two transduced strings in 8-bit ASCII.", S, "SOURCE-DERIVED", "ASCII only in the shipped witness.", "Exact bytes"),
        ("BEA361-D017", "bea361.bits.left-nul-alignment-v1", "Binary encoding", "Left alignment with NUL extension", "Embed both byte strings in length n=max(lengths) by appending 0x00 to the shorter source.", S, "SOURCE-DERIVED", "Alignment and pad byte are part of the witness.", "n=11 reproduction"),
        ("BEA361-D018", "bea361.bits.xor-delta-matrix-v1", "Binary algebra", "XOR delta matrix", "Delta=X xor Y in F2^(n x 8); applying the same Delta again inverts the affine translation.", S, "SOURCE-DERIVED", "This is bytewise XOR, not a shift instruction.", "Roundtrip tests"),
        ("BEA361-D019", "bea361.bits.even-weight-subspace-v1", "Binary algebra", "Even-weight delta subspace", "E_n=ker(p), p(Delta)=sum_ij Delta_ij mod 2. It has dimension 8n-1 for n>0.", P, "PROFILE-AXIOM", "Guarantees parity class, not Hamming weight.", "Witness weight=38; dimension=87"),
        ("BEA361-D020", "bea361.bits.symmetric-row-pairs-v1", "Binary algebra", "Repeated-mask symmetry constraints", "The shipped affine subspace adds Delta_3=Delta_4 and Delta_7=Delta_8, reproducing masks 0x5d and 0x5e.", S + "; " + P, "ENGINEERING", "Zero-based row indices; pair constraints are profile-specific.", "Exact rows + dimension=71"),
        ("BEA361-D021", "bea361.bits.parity-coset-invariance-v1", "Binary algebra", "Global parity preservation", "For Y=X+Delta, pi(Y)=pi(X)+p(Delta). Delta in E_n forces pi(Y)=pi(X).", P, "ENGINEERING", "One-bit global parity only.", "source parity=target parity=1"),
        ("BEA361-D022", "bea361.bits.bijective-entropy-invariance-v1", "Information theory", "Entropy under fixed XOR translation", "x->x+Delta is a bijection. For any random variable X on the fixed-width code space, H(X+Delta)=H(X); an even Delta additionally keeps parity cosets invariant.", P, "ENGINEERING", "Does not assert equal empirical bit weight or physical entropy.", "Proof by bijection"),
        ("BEA361-D023", "bea361.semantic.profile-evaluator-v1", "Semantics", "Typed evaluator to scalar value", "nu maps each declared representation ID to a finite real value; the shipped source and target both map to 19.", S + "; " + P, "PROFILE-AXIOM", "No external linguistic universality is inferred.", "Exact dictionary evaluation"),
        ("BEA361-D024", "bea361.semantic.fiber-quotient-v1", "Metric semantics", "Semantic fiber quotient", "r~r' iff nu(r)=nu(r'). The quotient Q=R/~ is identified with im(nu) subset R.", P, "ENGINEERING", "Evaluator/profile must be declared.", "Equivalence tests"),
        ("BEA361-D025", "bea361.semantic.pullback-pseudometric-v1", "Metric semantics", "Spatial pullback pseudometric", "For spatial samples p,q labeled by representations, d_nu(p,q)=|nu(lambda(p))-nu(lambda(q))|. It is a pseudometric on space and a metric on Q.", P, "PROFILE-AXIOM", "Distinct spatial points in one semantic fiber may have distance zero.", "Metric-law tests"),
        ("BEA361-D026", "bea361.semantic.sdf19-v1", "Implicit field", "Semantic-boundary signed distance", "F_19(p)=nu(lambda(p))-19 and Z_19=F_19^-1(0). Under d_nu, |F_19(p)|=dist_dnu(p,Z_19).", S + "; " + P, "PROFILE-AXIOM", "Exact only in the semantic quotient/pullback metric, not Euclidean rendering space.", "SDF identity tests"),
        ("BEA361-D027", "bea361.semantic.zero-set-guard-v1", "Event calculus", "Finite semantic guard band", "g_epsilon(r)=|nu(r)-19|-epsilon; commit when g_epsilon<=0 under ordinary UGTS support and compatibility gates.", P, "ENGINEERING", "epsilon must be finite and non-negative.", "Guard tests"),
        ("BEA361-D028", "bea361.certificate.integrated-bea-v2", "Certificate", "Integrated BEA certificate", "Record augmented/canonical Betti signatures, trade records, T4 homology certificates, XOR witness, parity/entropy scope, semantic quotient and explicit non-claims.", P, "ENGINEERING", "Certificate validity is profile-exact and non-transferable without profile identity.", "End-to-end tests"),
        ("BEA361-D029", "bea361.pipeline.query-first-handoff-v1", "Architecture", "Handoff to UGTS event order", "After the BEA certificate, continue support -> compatibility -> guard -> verified event -> transition -> lineage.", "UGTS baseline + " + P, "ENGINEERING", "BEA does not replace support or compatibility.", "Definition DAG validation"),
        ("BEA361-D030", "bea361.lineage.course-correction-v1", "Governance", "Superseding revision lineage", "Mark this package as the course-corrected 3.6.1 edition and retain the earlier 3.6 baseline as provenance, while superseding the prior planar-glyph BEA interpretation.", P, "ENGINEERING", "Version remains 3.6.1; revision status must be explicit.", "Metadata + changelog"),
    ]
    fields = ["catalog_id", "operator_id", "domain", "mechanism", "formal_definition", "source_basis", "disposition", "bounds", "validation"]
    return [dict(zip(fields, row)) for row in rows]


def definitions() -> list[dict[str, Any]]:
    raw = [
        {
            "id": "bea361:profile:synthetic-cell-complex-v2",
            "kind": "synthetic_text_profile",
            "domain": "representation_pair",
            "codomain": "profile",
            "evaluation_phase": 0,
            "dependencies": [],
            "parameters": {
                "unicode_normalization": "NFC",
                "lowercase": True,
                "whitespace_policy": "single-separator",
                "whitespace_metric_weight": 0.0,
                "torus_dimension": 4,
                "semantic_target": 19.0,
                "scope": "synthetic 1D cell complex; not standard font rendering"
            },
            "capabilities": ["profile-bound-topology", "zero-metric-hinges"],
            "invariants": ["profile ID accompanies every certificate"],
            "provenance": {"class": "profile-axiom", "note": "Course-corrected representation profile.", "source_refs": ["source PDF pp.1-5", "course-correction prompt"]}
        },
        {
            "id": "bea361:op:normalize-v1",
            "kind": "normalize_pair",
            "domain": "representation_pair",
            "codomain": "normalized_pair",
            "evaluation_phase": 1,
            "dependencies": ["bea361:profile:synthetic-cell-complex-v2"],
            "parameters": {"profile_ref": "bea361:profile:synthetic-cell-complex-v2"},
            "invariants": ["cycle annotation positions remain valid"],
            "provenance": {"class": "engineering-derived", "note": "NFC/lowercase/single-space normalization.", "source_refs": ["course-correction prompt"]}
        },
        {
            "id": "bea361:op:leet-provenance-v1",
            "kind": "leet_pair_transduce",
            "domain": "normalized_pair",
            "codomain": "transduced_pair_with_provenance",
            "evaluation_phase": 2,
            "dependencies": ["bea361:op:normalize-v1"],
            "parameters": {"map": {"a": "4", "e": "3", "i": "1", "o": "0"}},
            "invariants": ["source index retained for every output cell"],
            "provenance": {"class": "source-derived", "note": "Finite leet substitution pair.", "source_refs": ["source PDF pp.2-3"]}
        },
        {
            "id": "bea361:op:cell-build-v1",
            "kind": "build_augmented_cell_pair",
            "domain": "transduced_pair_with_provenance",
            "codomain": "augmented_cell_complex_pair",
            "evaluation_phase": 3,
            "dependencies": ["bea361:op:leet-provenance-v1"],
            "parameters": {"token_model": "path", "cycle_model": "annotated-loop", "space_model": "zero-metric-loop"},
            "invariants": ["chi=1-h before gluing", "h=4 intrinsic cycles per shipped representation"],
            "provenance": {"class": "profile-axiom", "note": "Synthetic 1D CW construction.", "source_refs": ["source PDF pp.1,5", "course-correction prompt"]}
        },
        {
            "id": "bea361:op:space-hole-trade-v1",
            "kind": "space_hole_trade_pair",
            "domain": "augmented_cell_complex_pair",
            "codomain": "canonical_cell_complex_pair",
            "evaluation_phase": 4,
            "dependencies": ["bea361:op:cell-build-v1"],
            "parameters": {"operation": "rewire (u,u) to (u,v) across distinct components", "metric_weight": 0.0},
            "invariants": ["delta beta0=-1 per separator", "delta beta1=-1 per separator", "delta chi=0"],
            "provenance": {"class": "profile-axiom", "note": "Formal Space-Hole Trading Lemma.", "source_refs": ["source PDF p.5", "course-correction prompt"]}
        },
        {
            "id": "bea361:op:betti-certificate-v1",
            "kind": "betti_pair_certificate",
            "domain": "canonical_cell_complex_pair",
            "codomain": "betti_pair",
            "evaluation_phase": 5,
            "dependencies": ["bea361:op:space-hole-trade-v1"],
            "parameters": {"formula": "beta1=E-V+beta0; chi=V-E"},
            "invariants": ["source canonical=(1,4,-3)", "target canonical=(1,4,-3)"],
            "provenance": {"class": "engineering-derived", "note": "Finite graph homology accounting.", "source_refs": ["course-correction prompt"]}
        },
        {
            "id": "bea361:op:torus-immersion-v1",
            "kind": "torus_pair_immersion",
            "domain": "canonical_cell_complex_pair",
            "codomain": "torus_immersion_pair",
            "evaluation_phase": 6,
            "dependencies": ["bea361:op:betti-certificate-v1"],
            "parameters": {"target": "T_syn^4=(R/Z)^4", "tree_collapse": True, "homology_matrix": "I4"},
            "invariants": ["beta1=4", "rank H1 map=4"],
            "provenance": {"class": "profile-axiom", "note": "Cycle quotient immersed in four coordinate circles.", "source_refs": ["source PDF pp.1,5", "course-correction prompt"]}
        },
        {
            "id": "bea361:op:ascii-align-v1",
            "kind": "ascii_left_nul_align",
            "domain": "transduced_pair_with_provenance",
            "codomain": "aligned_byte_pair",
            "evaluation_phase": 5,
            "dependencies": ["bea361:op:leet-provenance-v1"],
            "parameters": {"encoding": "ascii", "alignment": "left", "pad_byte": 0, "width_bytes": 11},
            "invariants": ["original lengths retained"],
            "provenance": {"class": "source-derived", "note": "Exact alignment policy reconstructed from source table.", "source_refs": ["source PDF pp.3-4"]}
        },
        {
            "id": "bea361:op:xor-delta-v1",
            "kind": "xor_delta_matrix",
            "domain": "aligned_byte_pair",
            "codomain": "F2[11,8]",
            "evaluation_phase": 6,
            "dependencies": ["bea361:op:ascii-align-v1"],
            "parameters": {"operation": "Delta=X xor Y"},
            "invariants": ["X xor Delta=Y", "Y xor Delta=X"],
            "provenance": {"class": "source-derived", "note": "Bytewise XOR witness.", "source_refs": ["source PDF pp.3-4"]}
        },
        {
            "id": "bea361:op:even-parity-v1",
            "kind": "even_parity_entropy_certificate",
            "domain": "F2[11,8]",
            "codomain": "parity_entropy_certificate",
            "evaluation_phase": 7,
            "dependencies": ["bea361:op:xor-delta-v1"],
            "parameters": {"subspace": "ker(sum bits mod 2)", "symmetric_pairs": [[3,4],[7,8]]},
            "invariants": ["delta weight even", "global parity preserved", "fixed XOR translation is bijective"],
            "provenance": {"class": "profile-axiom", "note": "Narrow parity and entropy statement.", "source_refs": ["source PDF pp.4-5", "course-correction prompt"]}
        },
        {
            "id": "bea361:op:semantic-evaluator-v1",
            "kind": "semantic_pair_evaluate",
            "domain": "representation_pair",
            "codomain": "R x R",
            "evaluation_phase": 3,
            "dependencies": ["bea361:profile:synthetic-cell-complex-v2"],
            "parameters": {"target": 19.0, "evaluator": "profile literal semantic_value"},
            "invariants": ["both shipped representations evaluate to 19"],
            "provenance": {"class": "profile-axiom", "note": "Typed profile evaluator.", "source_refs": ["source PDF p.2", "course-correction prompt"]}
        },
        {
            "id": "bea361:op:semantic-quotient-v1",
            "kind": "semantic_fiber_quotient",
            "domain": "representation_pair x R",
            "codomain": "metric_quotient",
            "evaluation_phase": 7,
            "dependencies": ["bea361:op:semantic-evaluator-v1"],
            "parameters": {"equivalence": "r~r' iff nu(r)=nu(r')", "metric": "|nu(r)-nu(r')|"},
            "invariants": ["metric is well-defined on quotient"],
            "provenance": {"class": "engineering-derived", "note": "Semantic fiber and scalar metric.", "source_refs": ["course-correction prompt"]}
        },
        {
            "id": "bea361:op:semantic-sdf19-v1",
            "kind": "semantic_boundary_sdf",
            "domain": "spatial_samples x metric_quotient",
            "codomain": "signed_scalar_field",
            "evaluation_phase": 8,
            "dependencies": ["bea361:op:semantic-quotient-v1"],
            "parameters": {"field": "F19(p)=nu(lambda(p))-19", "zero_set": "F19^-1(0)"},
            "invariants": ["|F19| equals distance to zero set in pullback pseudometric"],
            "provenance": {"class": "profile-axiom", "note": "Semantic-boundary SDF integration.", "source_refs": ["source PDF p.2", "course-correction prompt"]}
        },
        {
            "id": "bea361:op:certificate-v2",
            "kind": "integrated_bea_certificate",
            "domain": "all BEA witnesses",
            "codomain": "BEA361 certificate",
            "evaluation_phase": 9,
            "dependencies": [
                "bea361:op:betti-certificate-v1",
                "bea361:op:torus-immersion-v1",
                "bea361:op:even-parity-v1",
                "bea361:op:semantic-sdf19-v1"
            ],
            "parameters": {"claim_level": "profile-exact-synthetic-topology-equivalence"},
            "invariants": ["all references resolve", "all profile claims remain scoped"],
            "provenance": {"class": "engineering-derived", "note": "Integrated course-corrected BEA certificate.", "source_refs": ["course-correction prompt"]}
        },
        {
            "id": "bea361:schedule:handoff-v1",
            "kind": "evaluation_schedule",
            "domain": "definition_graph",
            "codomain": "ordered_steps",
            "evaluation_phase": 10,
            "dependencies": ["bea361:op:certificate-v2"],
            "parameters": {"after_bea": ["support", "compatibility", "guard", "verified_event", "transition", "lineage"]},
            "invariants": ["BEA certificate precedes ordinary event commit"],
            "provenance": {"class": "engineering-derived", "note": "Retains UGTS query-first event order.", "source_refs": ["UGTS baseline", "course-correction prompt"]}
        }
    ]
    return [attach_content_hash(record) for record in raw]


def build_example() -> dict[str, Any]:
    defs = definitions()
    return {
        "$schema": "../spec/ugts_kc_3_6_1_bea_synthetic.schema.json",
        "schema_version": "3.6.1",
        "substrate_id": "ugts:kc:3.6.1:bea:course-corrected:synthetic-cell-complex",
        "metadata": {
            "title": "UGTS-KC 3.6.1 BEA course-corrected synthetic topology example",
            "description": "Literal referential integration of the Space-Hole Trading Lemma, four-cycle torus immersion, even-parity XOR subspace and semantic-boundary SDF.",
            "evidence_boundary": "All equivalence claims are exact only inside the named synthetic profile. No standard font, dialect, historical, physical-energy or Euclidean SDF claim is made.",
            "revision_status": "course-corrected-superseding-edition",
            "requester_attribution": {
                "name": "Tom Klootwijk",
                "identifier": "NL200678942",
                "date_of_birth": "10-07-1990",
                "status": "requester-supplied-unverified"
            }
        },
        "definitions": defs,
        "instances": [
            {
                "id": SOURCE_ANNOTATION.representation_id,
                "definition_ref": "bea361:profile:synthetic-cell-complex-v2",
                "literal": {
                    "text": SOURCE_ANNOTATION.text,
                    "semantic_value": SOURCE_ANNOTATION.semantic_value,
                    "cycle_positions": list(SOURCE_ANNOTATION.cycle_positions)
                },
                "state": {"profile_ref": "bea361:profile:synthetic-cell-complex-v2", "role": "source"}
            },
            {
                "id": TARGET_ANNOTATION.representation_id,
                "definition_ref": "bea361:profile:synthetic-cell-complex-v2",
                "literal": {
                    "text": TARGET_ANNOTATION.text,
                    "semantic_value": TARGET_ANNOTATION.semantic_value,
                    "cycle_positions": list(TARGET_ANNOTATION.cycle_positions)
                },
                "state": {"profile_ref": "bea361:profile:synthetic-cell-complex-v2", "role": "target"}
            }
        ],
        "pipelines": [
            {
                "id": "bea361:pipeline:course-corrected-certificate-v2",
                "description": "Build the synthetic cell complexes, trade space loops into zero-metric bridges, immerse four cycle generators, verify the even XOR delta and evaluate the semantic SDF to 19.",
                "steps": [record["id"] for record in defs if record["id"] != "bea361:profile:synthetic-cell-complex-v2"]
            }
        ],
        "queries": [
            {
                "id": "bea361:query:certificate",
                "kind": "execute_pair_pipeline",
                "pipeline_ref": "bea361:pipeline:course-corrected-certificate-v2",
                "source_instance_ref": SOURCE_ANNOTATION.representation_id,
                "target_instance_ref": TARGET_ANNOTATION.representation_id
            },
            {"id": "bea361:query:definition-order", "kind": "definition_order"}
        ]
    }


def tex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in value)


def main() -> None:
    rows = operator_rows()
    fields = list(rows[0])
    csv_path = ROOT / "spec" / "bea_3_6_1_delta_operator_catalog.csv"
    json_path = ROOT / "spec" / "bea_3_6_1_delta_operator_catalog.json"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    example = build_example()
    example_path = ROOT / "examples" / "ugts_kc_3_6_1_bea_synthetic_example.json"
    example_path.write_text(json.dumps(example, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    certificate = build_synthetic_bea_certificate(SOURCE_ANNOTATION, TARGET_ANNOTATION)
    output = certificate.to_dict()
    output_path = ROOT / "examples" / "demo_bea_synthetic_output.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    xor = certificate.xor
    xor_rows: list[dict[str, Any]] = []
    for index, (source_byte, target_byte, delta_byte) in enumerate(zip(xor.source, xor.target, xor.delta)):
        xor_rows.append({
            "index": index,
            "source_byte": source_byte,
            "source_char": "NUL" if source_byte == 0 else chr(source_byte),
            "source_bits": f"{source_byte:08b}",
            "delta_byte": delta_byte,
            "delta_hex": f"0x{delta_byte:02x}",
            "delta_bits": f"{delta_byte:08b}",
            "delta_weight": delta_byte.bit_count(),
            "target_byte": target_byte,
            "target_char": "NUL" if target_byte == 0 else ("SPACE" if target_byte == 32 else chr(target_byte)),
            "target_bits": f"{target_byte:08b}",
        })
    (ROOT / "data" / "bea361_xor_delta_rows.json").write_text(json.dumps(xor_rows, indent=2) + "\n", encoding="utf-8")
    with (ROOT / "data" / "bea361_xor_delta_rows.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(xor_rows[0]))
        writer.writeheader()
        writer.writerows(xor_rows)

    # Compact LaTeX catalog table.
    table = ROOT / "report" / "bea_delta_operator_catalog_table.tex"
    with table.open("w", encoding="utf-8") as handle:
        handle.write("\\setlength{\\tabcolsep}{3pt}\n")
        handle.write("\\renewcommand{\\arraystretch}{1.10}\n")
        handle.write("\\begin{longtable}{>{\\raggedright\\arraybackslash\\scriptsize}p{1.4cm}>{\\raggedright\\arraybackslash\\ttfamily\\scriptsize}p{5.8cm}>{\\RaggedRight\\arraybackslash\\scriptsize}p{13.6cm}>{\\raggedright\\arraybackslash\\scriptsize}p{2.4cm}}\n")
        handle.write("\\toprule\n\\textbf{ID} & \\textbf{Operator} & \\textbf{Formal role and bound} & \\textbf{Status} \\\\\n\\midrule\n\\endfirsthead\n")
        handle.write("\\toprule\n\\textbf{ID} & \\textbf{Operator} & \\textbf{Formal role and bound} & \\textbf{Status} \\\\\n\\midrule\n\\endhead\n")
        for row in rows:
            role = row["formal_definition"] + " Bound: " + row["bounds"]
            handle.write(f"{tex_escape(row['catalog_id'])} & \\seqsplit{{{tex_escape(row['operator_id'])}}} & {tex_escape(role)} & {tex_escape(row['disposition'])} \\\\\n")
        handle.write("\\bottomrule\n\\end{longtable}\n")

    # Exact XOR table for the report.
    table = ROOT / "report" / "bea_xor_delta_table.tex"
    with table.open("w", encoding="utf-8") as handle:
        handle.write("\\begin{longtable}{rrrrrr}\n\\toprule\n$i$ & source & source bits & $\\Delta_i$ & delta bits & target \\\\\n\\midrule\n\\endfirsthead\n")
        handle.write("\\toprule\n$i$ & source & source bits & $\\Delta_i$ & delta bits & target \\\\\n\\midrule\n\\endhead\n")
        for row in xor_rows:
            source_char = row["source_char"].replace(" ", "SPACE")
            target_char = row["target_char"].replace(" ", "SPACE")
            handle.write(f"{row['index']} & \\texttt{{{tex_escape(source_char)}}} & \\texttt{{{row['source_bits']}}} & \\texttt{{{row['delta_hex']}}} & \\texttt{{{row['delta_bits']}}} & \\texttt{{{tex_escape(target_char)}}} \\\\\n")
        handle.write("\\bottomrule\n\\end{longtable}\n")

    print(f"generated {len(rows)} operators")
    print(example_path)
    print(output_path)


if __name__ == "__main__":
    main()
