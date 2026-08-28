"""Referential executor for the UGTS-KC 3.6.1 BEA synthetic profile."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bea_synthetic import (
    RepresentationAnnotation,
    SemanticBoundaryProfile,
    SemanticPoint,
    SyntheticTextProfile,
    build_augmented_cell_complex,
    build_synthetic_bea_certificate,
    build_torus_immersion,
    collapse_whitespace_hinges,
    xor_delta_matrix,
)
from .model import Substrate


@dataclass(frozen=True)
class BEATraceEntry:
    step_id: str
    kind: str
    output: Any


class SyntheticBEARuntime:
    """Execute the definition-backed pair pipeline shipped in the package."""

    def __init__(self, substrate: Substrate):
        self.substrate = substrate

    def _annotation(self, instance_id: str) -> RepresentationAnnotation:
        instance = next((item for item in self.substrate.instances if item.get("id") == instance_id), None)
        if instance is None:
            raise KeyError(instance_id)
        literal = instance["literal"]
        return RepresentationAnnotation(
            representation_id=instance_id,
            text=str(literal["text"]),
            semantic_value=float(literal["semantic_value"]),
            cycle_positions=tuple(int(value) for value in literal["cycle_positions"]),
        )

    def execute_pair(self, pipeline_id: str, source_id: str, target_id: str) -> list[BEATraceEntry]:
        pipeline = next((item for item in self.substrate.pipelines if item.get("id") == pipeline_id), None)
        if pipeline is None:
            raise KeyError(pipeline_id)
        source = self._annotation(source_id)
        target = self._annotation(target_id)
        profile = SyntheticTextProfile()

        source_t = profile.transduce(source)
        target_t = profile.transduce(target)
        source_aug = build_augmented_cell_complex(source_t, profile)
        target_aug = build_augmented_cell_complex(target_t, profile)
        source_can, source_trades = collapse_whitespace_hinges(source_aug)
        target_can, target_trades = collapse_whitespace_hinges(target_aug)
        torus_source = build_torus_immersion(source_can, profile)
        torus_target = build_torus_immersion(target_can, profile)
        xor = xor_delta_matrix(source_t.output_text, target_t.output_text)
        semantic = SemanticBoundaryProfile(
            profile_id="bea361:semantic-boundary-sdf19-v2",
            values={source_id: source.semantic_value, target_id: target.semantic_value},
            target_value=profile.target_value,
        )
        certificate = build_synthetic_bea_certificate(source, target, profile=profile)

        outputs: dict[str, Any] = {
            "normalize_pair": {
                "source": profile.normalize(source.text),
                "target": profile.normalize(target.text),
                "profile_id": profile.profile_id,
            },
            "leet_pair_transduce": {
                "source": source_t.output_text,
                "target": target_t.output_text,
                "source_cycle_positions": list(source_t.cycle_positions),
                "target_cycle_positions": list(target_t.cycle_positions),
            },
            "build_augmented_cell_pair": {
                "source": source_aug.to_dict(),
                "target": target_aug.to_dict(),
            },
            "space_hole_trade_pair": {
                "source": source_can.to_dict(),
                "target": target_can.to_dict(),
                "source_trade_records": [record.__dict__ | {"valid": record.valid} for record in source_trades],
                "target_trade_records": [record.__dict__ | {"valid": record.valid} for record in target_trades],
            },
            "betti_pair_certificate": {
                "source_augmented": source_aug.betti_signature(),
                "target_augmented": target_aug.betti_signature(),
                "source_canonical": source_can.betti_signature(),
                "target_canonical": target_can.betti_signature(),
                "chi_conserved": source_aug.euler_characteristic == source_can.euler_characteristic
                == target_aug.euler_characteristic == target_can.euler_characteristic,
            },
            "torus_pair_immersion": {
                "source": torus_source.to_dict(),
                "target": torus_target.to_dict(),
            },
            "ascii_left_nul_align": {
                "source_hex": xor.source.hex(),
                "target_hex": xor.target.hex(),
                "aligned_length": xor.n,
            },
            "xor_delta_matrix": xor.to_dict(),
            "even_parity_entropy_certificate": {
                "delta_weight": xor.delta_weight,
                "delta_is_even": xor.delta_is_even,
                "source_parity": xor.source_parity,
                "target_parity": xor.target_parity,
                "parity_preserved": xor.parity_preserved,
                "symmetric_pairs": [[3, 4], [7, 8]],
                "symmetric_pairs_hold": xor.satisfies_equal_row_pairs(((3, 4), (7, 8))),
                "symmetric_subspace_dimension": xor.symmetric_subspace_dimension(((3, 4), (7, 8))),
                "entropy_scope": xor.entropy_preservation_statement(),
            },
            "semantic_pair_evaluate": {
                "source_value": semantic.value(source_id),
                "target_value": semantic.value(target_id),
                "equivalent": semantic.equivalent(source_id, target_id),
            },
            "semantic_fiber_quotient": semantic.to_dict(),
            "semantic_boundary_sdf": {
                "source_residual": semantic.signed_residual(source_id),
                "target_residual": semantic.signed_residual(target_id),
                "source_sdf_identity": semantic.sdf_identity_holds(SemanticPoint(source_id, (0.0,))),
                "target_sdf_identity": semantic.sdf_identity_holds(SemanticPoint(target_id, (0.0,))),
            },
            "integrated_bea_certificate": certificate.to_dict(),
            "evaluation_schedule": {
                "after_bea": ["support", "compatibility", "guard", "verified_event", "transition", "lineage"]
            },
        }

        trace: list[BEATraceEntry] = []
        for step_id in pipeline.get("steps", []):
            node = self.substrate.definition(step_id)
            if node.kind not in outputs:
                raise NotImplementedError(node.kind)
            trace.append(BEATraceEntry(step_id=step_id, kind=node.kind, output=outputs[node.kind]))
        return trace
