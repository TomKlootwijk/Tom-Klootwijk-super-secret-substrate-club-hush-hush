#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ugts5.canonical import content_hash, sha256_hex, write_json  # noqa: E402

DATE = "2026-08-29"
VERSION = "5.0.0"
CANONICAL_ID = "ugts.foundation.unicode-set-field-klein-converse@5.0.0"
GLYPH_PROFILE = "ugts.canonical.capsule-glyph.v1"


def unicode_record(literal: str) -> dict[str, Any]:
    scalars = [f"U+{ord(ch):04X}" for ch in literal]
    names = [unicodedata.name(ch, "UNNAMED") for ch in literal]
    return {
        "literal": literal,
        "scalars": scalars,
        "names": names,
        "utf8_hex": literal.encode("utf-8").hex(),
        "normalization": "NFC",
    }


def pair_cell(
    *,
    family: int,
    kernel: str,
    direct_literal: str,
    converse_literal: str,
    direct_id: str,
    converse_id: str,
    canonical_ports: list[str],
    type_domain: list[str],
    formula: str,
    glyph_primitive: str,
    exactness: str = "exact_finite_or_profile_bounded",
) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for kappa, literal, op_id, other_id in [
        (0, direct_literal, direct_id, converse_id),
        (1, converse_literal, converse_id, direct_id),
    ]:
        surface_ports = canonical_ports if kappa == 0 else list(reversed(canonical_ports))
        record: dict[str, Any] = {
            "id": op_id,
            "version": VERSION,
            "family_id": family,
            "kappa": kappa,
            "converse_id": other_id,
            "unicode": unicode_record(literal),
            "syntax": {
                "fixity": "infix",
                "semantic_arity": 2,
                "surface_argument_order": surface_ports,
                "canonical_argument_order": canonical_ports,
                "surface_to_canonical": [0, 1] if kappa == 0 else [1, 0],
            },
            "typing": {
                "domain": type_domain if kappa == 0 else list(reversed(type_domain)),
                "canonical_domain": type_domain,
                "codomain": "Bool",
                "type_parameters": ["T"],
            },
            "semantic": {
                "kernel": kernel,
                "canonical_formula": formula,
                "converse_law": "E_converse(b,a) = E_direct(a,b)",
            },
            "field_action": {
                "kind": "predicate",
                "sign_convention": "negative_inside_zero_boundary_positive_outside",
                "capability_ladder": [
                    "exact_sdf",
                    "metric_signed_set_field",
                    "conservative_distance_bound",
                    "implicit_signed_residual",
                    "signed_membership_field",
                    "symbolic_membership_oracle",
                ],
            },
            "glyph": {
                "profile_id": GLYPH_PROFILE,
                "primitive": glyph_primitive,
                "geometry_role": "literal_port_orientation_witness",
                "mirror_axis": "x=0",
                "mirror_law": "G_converse(-x,y) = G_direct(x,y)",
                "stroke_radius": 0.075,
                "bbox": [-1.0, -1.0, 1.0, 1.0],
                "font_exactness": "not_claimed",
            },
            "klein": {
                "transform_id": "ugts.klein-converse.reflect-swap-toggle.v1",
                "theta_map": "theta' = (pi - theta) mod 2pi",
                "operand_map": "(a,b) -> (b,a)",
                "kappa_map": "kappa' = kappa xor 1",
                "orientation_map": "o' = -o",
                "involution": True,
            },
            "exactness": {
                "semantic": exactness,
                "canonical_glyph": "exact_sdf_to_finite_capsule_union",
                "font_glyph": "profile_bound",
                "continuous_global_relation": "certificate_required",
            },
            "provenance": {
                "class": "engineering-derived",
                "source_motif": "Unicode set-operator converse, glyph mirror, packed parity/topology selector",
                "release": CANONICAL_ID,
            },
        }
        record["content_hash"] = content_hash(record)
        cells.append(record)
    return cells


def algebra_cell(literal: str, op_id: str, kernel: str, arity: int, formula: str, primitive: str) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": op_id,
        "version": VERSION,
        "family_id": None,
        "kappa": None,
        "converse_id": None,
        "unicode": unicode_record(literal),
        "syntax": {
            "fixity": "prefix" if arity == 1 else "infix" if arity == 2 else "literal",
            "semantic_arity": arity,
            "surface_argument_order": [f"arg{i}" for i in range(arity)],
            "canonical_argument_order": [f"arg{i}" for i in range(arity)],
            "surface_to_canonical": list(range(arity)),
        },
        "typing": {
            "domain": ["Set[T]"] * arity,
            "canonical_domain": ["Set[T]"] * arity,
            "codomain": "Set[T]" if kernel != "set_equality" else "Bool",
            "type_parameters": ["T"],
        },
        "semantic": {"kernel": kernel, "canonical_formula": formula},
        "field_action": {
            "kind": "field_transform" if kernel != "set_equality" else "predicate",
            "sign_convention": "negative_inside_zero_boundary_positive_outside",
            "distance_warning": "min/max/negation preserves sign but not always exact Euclidean distance",
        },
        "glyph": {
            "profile_id": GLYPH_PROFILE,
            "primitive": primitive,
            "geometry_role": "literal_operator_shape",
            "stroke_radius": 0.075,
            "bbox": [-1.0, -1.0, 1.0, 1.0],
            "font_exactness": "not_claimed",
        },
        "klein": {"role": "not_converse_paired_in_set-core-16"},
        "exactness": {
            "semantic": "exact_for_declared_set_model",
            "canonical_glyph": "exact_sdf_to_finite_capsule_union",
            "composed_field": "capability_may_downgrade",
        },
        "provenance": {
            "class": "engineering-derived",
            "release": CANONICAL_ID,
        },
    }
    record["content_hash"] = content_hash(record)
    return record


def build_atlas() -> dict[str, Any]:
    operators: list[dict[str, Any]] = []
    operators += pair_cell(
        family=0,
        kernel="membership",
        direct_literal="∈",
        converse_literal="∋",
        direct_id="set.membership.element-of",
        converse_id="set.membership.contains-as-member",
        canonical_ports=["element", "container"],
        type_domain=["Element[T]", "Set[T]"],
        formula="phi_container(element) <= 0",
        glyph_primitive="open_ellipse_with_central_bar",
    )
    operators += pair_cell(
        family=1,
        kernel="nonmembership",
        direct_literal="∉",
        converse_literal="∌",
        direct_id="set.membership.not-element-of",
        converse_id="set.membership.does-not-contain-as-member",
        canonical_ports=["element", "container"],
        type_domain=["Element[T]", "Set[T]"],
        formula="phi_container(element) > 0",
        glyph_primitive="open_ellipse_with_central_bar_and_slash",
    )
    operators += pair_cell(
        family=2,
        kernel="proper_subset",
        direct_literal="⊂",
        converse_literal="⊃",
        direct_id="set.inclusion.proper-subset",
        converse_id="set.inclusion.proper-superset",
        canonical_ports=["subset", "superset"],
        type_domain=["Set[T]", "Set[T]"],
        formula="A subseteq B and A != B",
        glyph_primitive="open_ellipse",
    )
    operators += pair_cell(
        family=3,
        kernel="subset_or_equal",
        direct_literal="⊆",
        converse_literal="⊇",
        direct_id="set.inclusion.subset-or-equal",
        converse_id="set.inclusion.superset-or-equal",
        canonical_ports=["subset", "superset"],
        type_domain=["Set[T]", "Set[T]"],
        formula="A subseteq B",
        glyph_primitive="open_ellipse_with_lower_bar",
    )
    operators += pair_cell(
        family=4,
        kernel="not_proper_subset",
        direct_literal="⊄",
        converse_literal="⊅",
        direct_id="set.inclusion.not-proper-subset",
        converse_id="set.inclusion.not-proper-superset",
        canonical_ports=["subset", "superset"],
        type_domain=["Set[T]", "Set[T]"],
        formula="not (A subseteq B and A != B)",
        glyph_primitive="open_ellipse_with_slash",
    )
    operators += pair_cell(
        family=5,
        kernel="not_subset_or_equal",
        direct_literal="⊈",
        converse_literal="⊉",
        direct_id="set.inclusion.not-subset-or-equal",
        converse_id="set.inclusion.not-superset-or-equal",
        canonical_ports=["subset", "superset"],
        type_domain=["Set[T]", "Set[T]"],
        formula="not (A subseteq B)",
        glyph_primitive="open_ellipse_with_lower_bar_and_slash",
    )
    operators += pair_cell(
        family=6,
        kernel="proper_subset_variant",
        direct_literal="⊊",
        converse_literal="⊋",
        direct_id="set.inclusion.subset-with-not-equal",
        converse_id="set.inclusion.superset-with-not-equal",
        canonical_ports=["subset", "superset"],
        type_domain=["Set[T]", "Set[T]"],
        formula="A subseteq B and A != B",
        glyph_primitive="open_ellipse_with_not-equal_bar",
    )
    operators += [
        algebra_cell("∪", "set.algebra.union", "union", 2, "phi_union = min(phi_A, phi_B)", "lower_arc"),
        algebra_cell("∩", "set.algebra.intersection", "intersection", 2, "phi_intersection = max(phi_A, phi_B)", "upper_arc"),
        algebra_cell("∖", "set.algebra.difference", "difference", 2, "phi_A_minus_B = max(phi_A, -phi_B)", "diagonal_set_minus"),
        algebra_cell("∁", "set.algebra.complement", "complement", 1, "phi_complement = -phi_A", "complement_mark"),
        algebra_cell("∅", "set.literal.empty", "empty_set", 0, "members = empty", "slashed_ellipse"),
        algebra_cell("=", "set.relation.equality", "set_equality", 2, "A subseteq B and B subseteq A", "parallel_bars"),
    ]
    atlas: dict[str, Any] = {
        "$schema": "./ugts5_operator_atlas.schema.json",
        "schema_id": "ugts.operator-atlas.schema@5.0.0",
        "atlas_id": "ugts.unicode-set-field-klein-converse.atlas",
        "version": VERSION,
        "canonical_release": CANONICAL_ID,
        "generated": DATE,
        "unicode_identity_rule": "exact scalar sequence is the cold-atlas key",
        "normalization": "NFC",
        "operators": operators,
    }
    atlas["atlas_hash"] = content_hash(atlas, excluded=("atlas_hash",))
    return atlas


def build_codebook(atlas: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any] | None] = [None] * 16
    by_family_kappa = {(op["family_id"], op["kappa"]): op for op in atlas["operators"] if op["family_id"] is not None}
    for family in range(7):
        for kappa in (0, 1):
            slot = (family << 1) | kappa
            op = by_family_kappa[(family, kappa)]
            entries[slot] = {
                "slot": slot,
                "family": family,
                "kappa": kappa,
                "literal": op["unicode"]["literal"],
                "operator_id": op["id"],
                "operator_content_hash": op["content_hash"],
            }
    codebook: dict[str, Any] = {
        "$schema": "./ugts5_hot_codebook.schema.json",
        "schema_id": "ugts.hot-codebook.schema@5.0.0",
        "codebook_id": "ugts.set-core-16.v1",
        "version": "1.0.0",
        "atlas_id": atlas["atlas_id"],
        "atlas_hash": atlas["atlas_hash"],
        "operator_id_rule": "operator_id = (family << 1) | kappa",
        "reserved_slots": [14, 15],
        "entries": entries,
    }
    codebook["codebook_hash"] = content_hash(codebook, excluded=("codebook_hash",))
    return codebook


def schemas() -> dict[str, dict[str, Any]]:
    return {
        "ugts5_operator_atlas.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://ugts.example/schema/operator-atlas-5.0.json",
            "title": "UGTS 5.0 Unicode Operator Atlas",
            "type": "object",
            "required": ["schema_id", "atlas_id", "version", "operators", "atlas_hash"],
            "properties": {
                "schema_id": {"const": "ugts.operator-atlas.schema@5.0.0"},
                "atlas_id": {"type": "string", "minLength": 1},
                "version": {"const": "5.0.0"},
                "operators": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/operator"}},
                "atlas_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            },
            "$defs": {
                "operator": {
                    "type": "object",
                    "required": ["id", "version", "unicode", "syntax", "typing", "semantic", "glyph", "exactness", "content_hash"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "version": {"const": "5.0.0"},
                        "family_id": {"type": ["integer", "null"], "minimum": 0, "maximum": 7},
                        "kappa": {"type": ["integer", "null"], "enum": [0, 1, None]},
                        "converse_id": {"type": ["string", "null"]},
                        "unicode": {
                            "type": "object",
                            "required": ["literal", "scalars", "utf8_hex", "normalization"],
                            "properties": {
                                "literal": {"type": "string", "minLength": 1},
                                "scalars": {"type": "array", "minItems": 1, "items": {"type": "string", "pattern": "^U\\+[0-9A-F]{4,6}$"}},
                                "utf8_hex": {"type": "string", "pattern": "^[0-9a-f]+$"},
                                "normalization": {"const": "NFC"},
                            },
                        },
                        "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    },
                }
            },
        },
        "ugts5_hot_codebook.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://ugts.example/schema/hot-codebook-5.0.json",
            "type": "object",
            "required": ["codebook_id", "atlas_hash", "entries", "codebook_hash"],
            "properties": {
                "entries": {
                    "type": "array",
                    "minItems": 16,
                    "maxItems": 16,
                    "items": {"type": ["object", "null"]},
                },
                "atlas_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "codebook_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            },
        },
        "ugts5_stream_header.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://ugts.example/schema/packed-stream-header-5.0.json",
            "title": "UGTS 5.0 Packed Set-Field Node Stream Header",
            "type": "object",
            "required": ["schema_id", "codebook_id", "codebook_hash", "atlas_hash", "chart", "quantization", "error_contract"],
            "properties": {
                "schema_id": {"const": "ugts.packed-set-field-node-stream@5.0.0"},
                "codebook_id": {"type": "string"},
                "codebook_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "atlas_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "chart": {
                    "type": "object",
                    "required": ["rho_origin", "theta_origin_code", "theta_bins", "wrap_profile"],
                    "properties": {
                        "theta_bins": {"const": 256},
                        "theta_origin_code": {"type": "integer", "minimum": 0, "maximum": 255},
                        "wrap_profile": {"const": "reflective-klein-converse-v1"},
                    },
                },
                "quantization": {"type": "object"},
                "error_contract": {"type": "object"},
            },
        },
        "ugts5_release_record.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://ugts.example/schema/release-record-5.0.json",
            "type": "object",
            "required": ["canonical_identity", "component_type", "version", "chronology_key", "parents", "artifact_policy"],
            "properties": {
                "canonical_identity": {"const": CANONICAL_ID},
                "component_type": {"const": "foundation"},
                "version": {"const": "5.0.0"},
            },
        },
    }


def build_release_record(atlas: dict[str, Any], codebook: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "./ugts5_release_record.schema.json",
        "canonical_identity": CANONICAL_ID,
        "canonical_display_name": "UGTS Foundation / Unicode Set-Field and Klein-Converse Atlas 5.0.0",
        "legacy_alias": "UGTS-KC 5.0",
        "component_type": "foundation",
        "version": VERSION,
        "chronology_key": "2026-08-29T00:00:00+02:00",
        "release_date": DATE,
        "codename": "USF-KCA",
        "parents": [
            {"identity": "ugts.formal.literal-referential@3.6.0", "relationship": "extends-concept"},
            {"identity": "ugts.formal.bea@3.6.1", "relationship": "extends-representation-profile"},
            {"identity": "ugts.profile.sclp@3.6.2", "relationship": "extends-log-polar-and-reflective-klein"},
            {"identity": "ugts.compute.gpu-native@1.1.0", "relationship": "retains-packed-evidence-discipline"},
            {"identity": "ugts.operator.general-order@4.2.0", "relationship": "extends-operator-record-and-order"},
            {"identity": "ugts.profile.iq-field@3.9.3", "relationship": "retains-field-capability-discipline"},
        ],
        "source_motif": {
            "filename": "mandible-broad-set-math-operator-CE-logo-like-simd256.pdf",
            "sha256": "6149e3d398c22b53d0664ba2f624c046d6260506f9ac009dfb2b2572afb3d18c",
        },
        "mechanism_namespace": {
            "primary": "USF001-USF064",
            "legacy_continuity": "M886-M949",
            "continuity_parent": "UGTS-KC 4.2 General Operator and Order Addendum M630-M885",
        },
        "atlas_id": atlas["atlas_id"],
        "atlas_hash": atlas["atlas_hash"],
        "hot_codebook_id": codebook["codebook_id"],
        "hot_codebook_hash": codebook["codebook_hash"],
        "artifact_policy": {
            "raw_sources_redistributed": False,
            "projection_downstream": True,
            "authoritative_sequence": ["support", "compatibility", "guard", "verified_proposal", "deterministic_commit", "lineage"],
            "private_identifiers_included": False,
        },
        "formal_conclusion": "A Unicode operator is no longer merely text and no longer merely an icon. It is a content-addressed, executable geometric rule cell whose literal codepoint resolves both its canonical shape and its typed operation. A Klein-converse parity flip mirrors the shape, reverses the typed ports and selects the converse Unicode spelling while preserving the mathematical truth value.",
    }


MECH_NAMES = [
    ("Release identity", "Component-scoped major release identity with legacy UGTS-KC 5.0 alias."),
    ("Source register", "Content-hashed source and parent register without raw-source redistribution."),
    ("OperatorCell", "One content-addressed record co-addresses literal, glyph, semantics and field action."),
    ("Unicode scalar key", "Exact Unicode scalar sequence is a canonical cold-atlas lookup key."),
    ("UTF-8 literal key", "UTF-8 spelling is recorded and round-tripped without ASCII aliasing."),
    ("NFC normalization profile", "NFC is explicit; compatibility normalization is not silently applied."),
    ("Typed signature", "Every operator declares domain, codomain, arity and type parameters."),
    ("Canonical argument order", "One semantic port order is authoritative for each converse family."),
    ("Surface argument map", "Surface operands map explicitly to canonical semantic ports."),
    ("Semantic evaluator", "Literal dispatch selects a bounded typed semantic kernel."),
    ("Canonical glyph SDF", "A versioned capsule-union field represents the literal operator shape."),
    ("Set-field action", "Operator records declare predicates or sign-compatible field transforms."),
    ("Converse link", "Direct and converse cells reference each other by stable operator ID."),
    ("Operator content hash", "Every cell carries a canonical SHA-256 content address."),
    ("Provenance class", "Source motif, engineering normalization and measured evidence stay distinct."),
    ("Capability class", "Exact SDF, metric field, bound, residual, membership field and oracle remain distinct."),
    ("Signed set field", "phi_A = d(x,A) - d(x,X\\A) under a declared metric profile."),
    ("Characteristic fallback", "Finite or non-metric sets can use a signed membership field."),
    ("Membership predicate", "x in A iff phi_A(x) <= 0 under the selected boundary policy."),
    ("Nonmembership predicate", "x notin A is the typed negation of membership."),
    ("Subset predicate", "A subseteq B is a quantified emptiness claim over A\\B."),
    ("Proper subset predicate", "Proper inclusion adds non-equality to subset."),
    ("Set equality", "A=B is mutual inclusion under a common universe/profile."),
    ("Empty-set predicate", "Emptiness is exact only when the domain proof is complete."),
    ("Union field", "min(phi_A,phi_B) preserves the union sign."),
    ("Intersection field", "max(phi_A,phi_B) preserves the intersection sign."),
    ("Complement field", "-phi_A reverses inside and outside."),
    ("Difference field", "max(phi_A,-phi_B) preserves the sign of A\\B."),
    ("Symmetric-difference field", "A sign-correct max/min formula represents A triangle B."),
    ("Field capability downgrade", "Composed fields never inherit exact-distance status without proof."),
    ("Finite-universe proof", "Exhaustive finite checks may issue exact relation certificates."),
    ("Interval/analytic proof", "Continuous global claims require analytic, interval or certified-cover evidence."),
    ("Sample-only nonproof", "A sampled LUT result is bounded evidence, not universal inclusion proof."),
    ("Klein-converse transform", "One transform reflects chart, swaps ports and toggles converse state."),
    ("Operator converse", "U maps to U-smile while preserving truth after operand exchange."),
    ("Operand swap", "Typed endpoints reverse rather than being reinterpreted in place."),
    ("Glyph reflection", "Canonical converse glyph is the x-reflection of the direct glyph."),
    ("Angular reflection", "theta maps to pi-theta on the reflective profile."),
    ("Orientation selector", "kappa is a semantic/topological selector and not an integrity bit."),
    ("Involution law", "Applying the Klein-converse transform twice returns the original state."),
    ("Reflective quotient", "Boundary gluing declares the actual orientation-reversing quotient."),
    ("Half-turn distinction", "A pi rotation remains distinct from a reflective Klein gluing."),
    ("Cold Unicode atlas", "The full literal record remains content-addressed outside hot SIMD state."),
    ("Hot 16-slot codebook", "A batch-local codebook maps four-bit slots to exact atlas cells."),
    ("Reserved-slot rejection", "Unassigned local codes reject rather than aliasing silently."),
    ("Codebook content hash", "Hot mappings are bound to the exact cold atlas."),
    ("Packed Set-Field Node 32", "A corrected 32-bit execution record carries local deltas and flags."),
    ("Integrity parity", "Bit 31 checks payload parity and remains separate from kappa."),
    ("Family/kappa extraction", "operator_id=(family<<1)|kappa enables converse-pair locality."),
    ("Signed log-radius delta", "An explicit int8 delta requires a stream scale/bias contract."),
    ("Cyclic angle delta", "An 8-bit angular delta has a declared 256-bin period."),
    ("Grammar path fragment", "Eight bits represent a bounded branch fragment, not an unbounded tree."),
    ("Local field flags", "Two bits carry profile-defined local status with declared meaning."),
    ("Active bit", "Bit zero is decoded and tested rather than silently dropped."),
    ("Stream header", "Atlas, codebook, chart, quantization and error contracts travel with nodes."),
    ("Block CRC", "Stream-level CRC supplements per-node parity and content hashes."),
    ("Scalar oracle", "Dependency-free scalar decoding is the conformance authority."),
    ("Branchless mask expansion", "Boolean selectors expand to full-lane masks before blending."),
    ("AVX2 profile", "Eight-lane extraction is specified behind the scalar oracle."),
    ("NEON profile", "Four-lane ARM decoding is a specified backend target."),
    ("Quantization certificate", "Angular/radial errors are calculated from the declared profile."),
    ("Event-margin guard", "Packed evaluation is accepted only below the relevant event margin."),
    ("UGTS authority handoff", "Pure operator evaluation cannot bypass support, compatibility and commit."),
    ("Validation and kill criteria", "Claims fail closed on hash, type, parity, exactness or evidence violations."),
]


def build_mechanisms() -> dict[str, Any]:
    mechanisms = []
    for i, (name, definition) in enumerate(MECH_NAMES, start=1):
        mechanisms.append({
            "id": f"USF{i:03d}",
            "legacy_id": f"M{885+i}",
            "domain": [
                "release", "source", "referential", "unicode", "unicode", "unicode", "typing", "typing",
                "typing", "semantics", "geometry", "field", "relation", "integrity", "provenance", "exactness",
                "field", "field", "relation", "relation", "relation", "relation", "relation", "relation",
                "field", "field", "field", "field", "field", "exactness", "proof", "proof", "proof",
                "topology", "topology", "topology", "geometry", "topology", "topology", "topology", "topology",
                "topology", "atlas", "atlas", "atlas", "integrity", "packing", "integrity", "packing", "packing",
                "packing", "grammar", "packing", "packing", "stream", "integrity", "runtime", "simd", "simd",
                "simd", "quantization", "guard", "authority", "validation",
            ][i-1],
            "name": name,
            "definition": definition,
            "provenance": "engineering-derived",
            "validation": "implemented-and-tested" if i not in {59, 60} else "specified-contract",
        })
    return {
        "schema_id": "ugts.mechanism-catalog@5.0.0",
        "release": CANONICAL_ID,
        "count": len(mechanisms),
        "mechanisms": mechanisms,
    }


CLAIMS = [
    ("Unicode literal can key shape and functionality", "ADMIT", "The same content-addressed cell co-addresses literal, glyph, evaluator and field action."),
    ("Geometry and semantics are identical", "REJECT", "They remain typed faces of one record; equality requires an explicit map/certificate."),
    ("Set theory can use signed set fields", "ADMIT_WITH_CAPABILITY", "Exact SDF is one capability; finite, metric, residual and oracle profiles are distinct."),
    ("Membership is a local sign query", "ADMIT", "Under a declared set-field profile, x in A iff phi_A(x)<=0."),
    ("Every subset claim is O(1)", "REJECT", "Global inclusion is quantified and needs finite exhaustion or a continuous-domain proof."),
    ("Converse pairs share one kernel", "ADMIT", "Surface operand maps and typed endpoints make the reuse exact."),
    ("Klein flip is merely a bit shift", "CORRECT", "The bit selects an involution that also swaps operands and reflects the chart."),
    ("Klein-converse preserves truth", "ADMIT", "E_converse(b,a)=E_direct(a,b) for registered relation pairs."),
    ("A half-turn is a Klein reflection", "REJECT", "Rotation and orientation-reversing gluing remain distinct profiles."),
    ("One bit can be both integrity and topology", "REJECT", "Integrity parity and kappa are separate logical and physical fields."),
    ("Canonical glyph converse is a mirror", "ADMIT_PROFILE_BOUND", "True for the UGTS canonical capsule profile; font-exact profiles may differ."),
    ("Unicode codepoint alone fixes font appearance", "REJECT", "Font, size, stroke, threshold and rendering policy remain profile data."),
    ("Four-bit operator ID is globally unique", "REJECT", "It is only a hot codebook slot bound to an atlas hash."),
    ("Packed node is complete world state", "REJECT", "Definitions, header, lineage, uncertainty and hashes remain external."),
    ("One parity bit detects all corruption", "REJECT", "It detects odd payload bit flips; CRC/hash layers cover stronger integrity roles."),
    ("32-bit record reduces traffic", "ADMIT_CONDITIONAL", "Only under a measured workload and an error/equivalence contract."),
    ("Eight-bit angle gives 1.40625 degree bins", "ADMIT", "360/256 with round-to-nearest maximum half-bin error 0.703125 degrees."),
    ("Composed min/max fields remain exact SDFs", "REJECT", "Sign is preserved, exact-distance status may be lost."),
    ("Sampled LUT proves continuous emptiness", "REJECT", "Sampling can miss features between samples unless a certificate closes the gap."),
    ("SIMD branchless selection is always faster", "REJECT", "Backend choice depends on branch cost, coherence and target measurement."),
    ("AVX2 eight-lane extraction is feasible", "ADMIT_AS_PROFILE", "Correct extraction and full-lane masks are supplied; target throughput remains benchmarked evidence."),
    ("Deterministic parity is true randomness", "REJECT", "Deterministic bits provide repeatable selection or checks, not entropy."),
    ("16 KB stores arbitrary worlds", "REJECT", "Small atlases and repetitive grammars may fit; arbitrary information does not."),
    ("This release enumerates all Unicode mathematics", "REJECT", "The schema is extensible; the shipped atlas is a bounded set-theory foundation."),
]


def build_claims() -> dict[str, Any]:
    return {
        "schema_id": "ugts.claims-ledger@5.0.0",
        "release": CANONICAL_ID,
        "claims": [
            {"id": f"USF-C{i:02d}", "claim": c, "disposition": d, "reason": r}
            for i, (c, d, r) in enumerate(CLAIMS, start=1)
        ],
    }


def source_register() -> dict[str, Any]:
    sources = [
        ("S0", "mandible-broad-set-math-operator-CE-logo-like-simd256.pdf", "6149e3d398c22b53d0664ba2f624c046d6260506f9ac009dfb2b2572afb3d18c", "Immediate Unicode/SDF/log-polar/SIMD source motif"),
        ("S1", "UGTS_KC_3_6_Tom_Klootwijk.pdf", "e21433cd8378368dafe4ae278d3c9c364725e45ae7fd75b743328bd2d6003a46", "Literal content-addressed definitions and operation order"),
        ("S2", "UGTS_KC_3_6_1_BEA_Tom_Klootwijk.pdf", "ac857c9c01f5f4e93edbc8657d2d549a085d939dd1cedce3829ab62bc1dca096", "Representation profile, glyph SDF and typed semantic evaluator separation"),
        ("S3", "UGTS_KC_3_6_2_SCLP_Tom_Klootwijk.pdf", "6987490a0a7b7ed76b0091057a2e69ab831fee786434a0b4219782923f5ea580", "Log-polar chart, finite packing, half-turn/Klein distinction"),
        ("S4", "Unified_Geometric_Topological_Substrate_GPU_Native_Addendum.pdf", "3a6b6c57118ca4e2d7d7e577508c3477a095d133791f3708cb56a054285225d2", "Packed-state, one-bit and hardware evidence discipline"),
        ("S5", "UGTS_KC_4_2_General_Operator_Order_Addendum(1).pdf", "413ef9568330e253ebb8e42cbc756257f3c138485f2d9697de48324b92f28efe", "General typed operator record and explicit order calculus"),
        ("S6", "UGTS_KC_3_9_3_IQ_Field_Substrate_Tom_Klootwijk(1).pdf", "c0ae58652436476f77be3b1f94d4b82cf66f8ba3ca5ae25ad5f6706b217ed8d4", "Field exactness/capability and sign-preserving CSG boundary"),
        ("S7", "UGTS_Versioning_Charter_Phase_1_Foundation_Chronology(1).pdf", "1b64495ed32a24a66f356652cb6fb1291d0727ab9bfa9174c994d757325f037b", "Component-scoped canonical identity and filename rule"),
    ]
    return {
        "schema_id": "ugts.source-register@5.0.0",
        "raw_sources_redistributed": False,
        "sources": [{"id": i, "filename": f, "sha256": h, "use": u} for i, f, h, u in sources],
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def main() -> None:
    spec = ROOT / "spec"
    spec.mkdir(exist_ok=True)
    atlas = build_atlas()
    codebook = build_codebook(atlas)
    release = build_release_record(atlas, codebook)
    mechanisms = build_mechanisms()
    claims = build_claims()

    write_json(spec / "operator_atlas.json", atlas)
    write_json(spec / "hot_codebook_set_core_16.json", codebook)
    write_json(spec / "release_record.json", release)
    write_json(spec / "mechanisms.json", mechanisms)
    write_json(spec / "claims_ledger.json", claims)
    write_json(spec / "source_register.json", source_register())
    for filename, schema in schemas().items():
        write_json(spec / filename, schema)

    write_csv(spec / "mechanisms.csv", mechanisms["mechanisms"], ["id", "legacy_id", "domain", "name", "definition", "provenance", "validation"])
    write_csv(spec / "claims_ledger.csv", claims["claims"], ["id", "claim", "disposition", "reason"])

    print(json.dumps({
        "atlas_hash": atlas["atlas_hash"],
        "codebook_hash": codebook["codebook_hash"],
        "operators": len(atlas["operators"]),
        "mechanisms": len(mechanisms["mechanisms"]),
        "claims": len(claims["claims"]),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
