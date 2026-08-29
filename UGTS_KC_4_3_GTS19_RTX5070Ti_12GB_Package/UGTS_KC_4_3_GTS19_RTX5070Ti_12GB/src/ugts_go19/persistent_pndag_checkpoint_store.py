"""Immutable checkpoint generations for the bounded persistent proof DAG.

This store is deliberately scoped to :class:`PersistentProofNumberDAG`, which
itself only accepts 1x1 and 2x2 fixtures.  Each publication installs an
immutable checkpoint, then an immutable chained manifest, and finally replaces
``CURRENT`` atomically.  Older generations are never overwritten.  Exact
node-prefix validation requires each generation to preserve every prior
committed graph fact; a larger work counter alone is not lineage.

Opening an existing store is intentionally impossible without an externally
retained :class:`PersistentPNDAGCheckpointTip`.  That pin makes replacement or
rollback of ``CURRENT`` detectable instead of silently accepting lost work.
The anti-rollback pin relies on SHA-256 collision resistance; proof identity
does not: canonical checkpoint bytes are passed to the DAG's strict loader,
which reconstructs and exactly validates every semantic state and edge.  For a
crash-safe external-tip handoff, callers use ``prepare``, durably journal its
small record outside this store, then call ``commit_prepared``; recovery is
idempotent with either the exact predecessor or intended ``CURRENT`` visible.

Exactly one writer may use a store directory.  Readers may restart from a
published tip, but writer locking, hostile concurrent file mutation, garbage
collection, resource bounds, symlink/reparse-point hardening, and Windows
directory-fsync support are outside this bounded vertical slice.  Store roots
are therefore assumed trusted and symlink-free.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable

from .digests import canonical_json_bytes, sha256_hex
from .persistent_history import SERIALIZATION_FORMAT as HISTORY_SERIALIZATION_FORMAT
from .persistent_pndag import (
    ALGORITHM_ID,
    CHECKPOINT_FORMAT,
    MOVE_ORDER_ID,
    PERSISTENT_STATE_FORMAT,
    PROOF_ARITHMETIC,
    SCOPE as PNDAG_SCOPE,
    SELECTION_ID,
    SYMMETRY_MODE,
    PersistentProofNumberDAG,
)
from .rules import Rules
from .segment_store import (
    SegmentStoreError,
    _atomic_replace_bytes,
    _fsync_directory,
    _fsync_file,
    _mkdir_durable,
    _publish_immutable,
)


CHECKPOINT_GENERATION_MANIFEST_FORMAT = (
    "UGTS-GO-PERSISTENT-PNDAG-CHECKPOINT-MANIFEST-v1"
)
CHECKPOINT_GENERATION_POINTER_FORMAT = "UGTS-GO-PERSISTENT-PNDAG-CHECKPOINT-POINTER-v1"
CHECKPOINT_GENERATION_SCOPE = "bounded-single-writer-persistent-pndag-1x1-2x2"
CHECKPOINT_PREPARATION_FORMAT = "UGTS-GO-PERSISTENT-PNDAG-PREPARATION-v1"

_UINT64_MAX = (1 << 64) - 1
_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_STATUS_VALUES = {"UNKNOWN", "PROVEN", "DISPROVEN"}
_EXPANSION_VALUES = {"unexpanded", "expanded", "terminal"}

DigestFunction = Callable[[bytes], bytes | str]

_CHECKPOINT_KEYS = {
    "algorithm",
    "checkpoint_sha256",
    "committed_expansions",
    "digest_index",
    "edge_count",
    "format",
    "graph_sha256",
    "history_digest_index",
    "history_format",
    "move_order",
    "node_count",
    "nodes",
    "proof_arithmetic",
    "root_disproof_number",
    "root_id",
    "root_proof_number",
    "root_state_object_id",
    "rules",
    "rules_sha256",
    "scope",
    "selection",
    "state_format",
    "status",
    "symmetry",
    "threshold2",
}
_RUN_KEYS = {
    "algorithm",
    "checkpoint_format",
    "digest_index",
    "history_digest_index",
    "history_format",
    "move_order",
    "proof_arithmetic",
    "root_state_hex",
    "root_state_object_id",
    "rules",
    "rules_sha256",
    "scope",
    "selection",
    "state_format",
    "symmetry",
    "threshold2",
}
_CHECKPOINT_ENTRY_KEYS = {
    "byte_length",
    "checkpoint_sha256",
    "committed_expansions",
    "file",
    "file_sha256",
    "graph_sha256",
    "status",
}
_MANIFEST_KEYS = {
    "checkpoint",
    "format",
    "generation",
    "manifest_sha256",
    "previous_manifest_sha256",
    "run",
    "run_sha256",
    "scope",
}
_POINTER_KEYS = {
    "format",
    "generation",
    "manifest_file",
    "manifest_sha256",
    "pointer_sha256",
}
_TIP_KEYS = {
    "checkpoint_file_sha256",
    "checkpoint_sha256",
    "committed_expansions",
    "generation",
    "graph_sha256",
    "manifest_sha256",
    "run_sha256",
}
_PREPARATION_KEYS = {"format", "intended_tip", "previous_tip"}
_NODE_KEYS = {
    "cached_disproof",
    "cached_proof",
    "children",
    "digest",
    "expansion",
    "id",
    "rank",
    "state_hex",
}
_EDGE_KEYS = {"child_id", "move"}


class PersistentPNDAGCheckpointStoreError(ValueError):
    """A checkpoint-generation store is malformed or violates its lineage."""


@dataclass(frozen=True, slots=True)
class PersistentPNDAGCheckpointTip:
    """Externally retainable anti-rollback pin for one published generation."""

    generation: int
    manifest_sha256: str
    checkpoint_file_sha256: str
    checkpoint_sha256: str
    run_sha256: str
    graph_sha256: str
    committed_expansions: int

    def __post_init__(self) -> None:
        _require_int(
            self.generation,
            "tip generation",
            minimum=1,
            maximum=_UINT64_MAX,
        )
        _require_int(
            self.committed_expansions,
            "tip committed expansions",
            minimum=0,
            maximum=_UINT64_MAX,
        )
        for label, value in (
            ("tip manifest hash", self.manifest_sha256),
            ("tip checkpoint file hash", self.checkpoint_file_sha256),
            ("tip checkpoint hash", self.checkpoint_sha256),
            ("tip run hash", self.run_sha256),
            ("tip graph hash", self.graph_sha256),
        ):
            _require_sha256(value, label)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> "PersistentPNDAGCheckpointTip":
        payload = _require_keys(value, _TIP_KEYS, "checkpoint tip")
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class PersistentPNDAGCheckpointPreparation:
    """Externally journalable intent produced before ``CURRENT`` can change."""

    previous_tip: PersistentPNDAGCheckpointTip | None
    intended_tip: PersistentPNDAGCheckpointTip

    def __post_init__(self) -> None:
        if self.previous_tip is not None and not isinstance(
            self.previous_tip, PersistentPNDAGCheckpointTip
        ):
            raise TypeError("previous_tip must be a checkpoint tip or None")
        if not isinstance(self.intended_tip, PersistentPNDAGCheckpointTip):
            raise TypeError("intended_tip must be a checkpoint tip")
        if self.previous_tip is None:
            if self.intended_tip.generation != 1:
                raise PersistentPNDAGCheckpointStoreError(
                    "a genesis preparation must target generation one"
                )
        else:
            if self.previous_tip.generation >= _UINT64_MAX:
                raise OverflowError("checkpoint generation counter exhausted")
            if self.intended_tip.generation != self.previous_tip.generation + 1:
                raise PersistentPNDAGCheckpointStoreError(
                    "prepared checkpoint generation is not the next generation"
                )
            if self.intended_tip.run_sha256 != self.previous_tip.run_sha256:
                raise PersistentPNDAGCheckpointStoreError(
                    "prepared checkpoint changed the exact run"
                )
            if (
                self.intended_tip.committed_expansions
                <= self.previous_tip.committed_expansions
            ):
                raise PersistentPNDAGCheckpointStoreError(
                    "prepared checkpoint did not increase committed work"
                )

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": CHECKPOINT_PREPARATION_FORMAT,
            "intended_tip": self.intended_tip.as_dict(),
            "previous_tip": (
                None if self.previous_tip is None else self.previous_tip.as_dict()
            ),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "PersistentPNDAGCheckpointPreparation":
        payload = _require_keys(value, _PREPARATION_KEYS, "checkpoint preparation")
        if payload["format"] != CHECKPOINT_PREPARATION_FORMAT:
            raise PersistentPNDAGCheckpointStoreError(
                "unsupported checkpoint preparation format"
            )
        previous = payload["previous_tip"]
        return cls(
            previous_tip=(
                None
                if previous is None
                else PersistentPNDAGCheckpointTip.from_dict(previous)
            ),
            intended_tip=PersistentPNDAGCheckpointTip.from_dict(
                payload["intended_tip"]
            ),
        )


class PersistentPNDAGCheckpointCommitUncertain(PersistentPNDAGCheckpointStoreError):
    """A post-replace failure whose outcome needs the retained preparation."""

    def __init__(self, preparation: PersistentPNDAGCheckpointPreparation) -> None:
        super().__init__(
            "checkpoint commit outcome is uncertain; recover with the retained "
            "preparation"
        )
        self.preparation = preparation


@dataclass(frozen=True, slots=True)
class _CheckpointMetadata:
    file_sha256: str
    byte_length: int
    checkpoint_sha256: str
    committed_expansions: int
    graph_sha256: str
    status: str
    run: dict[str, Any]
    run_sha256: str
    payload: dict[str, Any]


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PersistentPNDAGCheckpointStoreError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise PersistentPNDAGCheckpointStoreError(f"non-finite JSON constant: {value}")


def _decode_canonical_json(raw: bytes, label: str) -> dict[str, Any]:
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise PersistentPNDAGCheckpointStoreError(
            f"{label} must end in exactly one newline"
        )
    try:
        value = json.loads(
            raw[:-1].decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        PersistentPNDAGCheckpointStoreError,
    ) as exc:
        raise PersistentPNDAGCheckpointStoreError(
            f"{label} is not valid canonical JSON"
        ) from exc
    if not isinstance(value, dict):
        raise PersistentPNDAGCheckpointStoreError(f"{label} must be a JSON object")
    try:
        canonical = canonical_json_bytes(value)
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise PersistentPNDAGCheckpointStoreError(
            f"{label} is not valid canonical JSON"
        ) from exc
    if canonical != raw[:-1]:
        raise PersistentPNDAGCheckpointStoreError(f"{label} is not in canonical form")
    return value


def _require_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise PersistentPNDAGCheckpointStoreError(f"{label} has a noncanonical shape")
    return value


def _require_int(
    value: Any,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise PersistentPNDAGCheckpointStoreError(
            f"{label} must be an integer in {minimum}..{maximum}"
        )
    return value


def _require_sha256(value: Any, label: str) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise PersistentPNDAGCheckpointStoreError(
            f"{label} must be lowercase SHA-256 text"
        )
    return value


def _exact_json_equal(first: Any, second: Any) -> bool:
    """Compare JSON values without Python's ``True == 1`` coercion."""

    return canonical_json_bytes(first) == canonical_json_bytes(second)


def _validate_digest_index(value: Any, label: str) -> dict[str, Any]:
    index = _require_keys(value, {"collision_checked", "name"}, label)
    if index["collision_checked"] is not True:
        raise PersistentPNDAGCheckpointStoreError(
            f"{label} must declare collision-checked indexing"
        )
    if type(index["name"]) is not str or not index["name"]:
        raise PersistentPNDAGCheckpointStoreError(f"{label} name must be nonempty text")
    return index


def _validate_run_envelope(value: Any) -> dict[str, Any]:
    run = _require_keys(value, _RUN_KEYS, "checkpoint run envelope")
    expected_text = {
        "algorithm": ALGORITHM_ID,
        "checkpoint_format": CHECKPOINT_FORMAT,
        "history_format": HISTORY_SERIALIZATION_FORMAT,
        "move_order": MOVE_ORDER_ID,
        "scope": PNDAG_SCOPE,
        "selection": SELECTION_ID,
        "state_format": PERSISTENT_STATE_FORMAT,
        "symmetry": SYMMETRY_MODE,
    }
    for field, expected in expected_text.items():
        if type(run[field]) is not str or run[field] != expected:
            raise PersistentPNDAGCheckpointStoreError(
                f"checkpoint run {field} mismatch"
            )
    if not _exact_json_equal(run["proof_arithmetic"], PROOF_ARITHMETIC):
        raise PersistentPNDAGCheckpointStoreError(
            "checkpoint run proof arithmetic mismatch"
        )
    _validate_digest_index(run["digest_index"], "checkpoint run state digest index")
    _validate_digest_index(
        run["history_digest_index"], "checkpoint run history digest index"
    )
    root_state = _decode_lower_hex(run["root_state_hex"], "run root state hex")
    root_object_id = _require_sha256(
        run["root_state_object_id"], "run root state object id"
    )
    if sha256_hex(root_state) != root_object_id:
        raise PersistentPNDAGCheckpointStoreError(
            "run root state object id does not match exact root bytes"
        )
    try:
        rules = Rules.from_dict(run["rules"])
    except (TypeError, ValueError) as exc:
        raise PersistentPNDAGCheckpointStoreError(
            "checkpoint run rules are invalid"
        ) from exc
    if not _exact_json_equal(run["rules"], rules.as_dict()):
        raise PersistentPNDAGCheckpointStoreError(
            "checkpoint run rules are not type-exact"
        )
    rules_sha256 = _require_sha256(run["rules_sha256"], "run rules hash")
    if sha256_hex(canonical_json_bytes(run["rules"])) != rules_sha256:
        raise PersistentPNDAGCheckpointStoreError(
            "run rules hash does not match exact rules"
        )
    _require_int(
        run["threshold2"],
        "run threshold",
        minimum=_INT64_MIN,
        maximum=_INT64_MAX,
    )
    return run


def _self_hashed_payload(
    payload: dict[str, Any], hash_field: str
) -> tuple[dict[str, Any], str]:
    digest = sha256_hex(canonical_json_bytes(payload))
    complete = dict(payload)
    complete[hash_field] = digest
    return complete, digest


def _verify_self_hash(payload: dict[str, Any], hash_field: str, label: str) -> str:
    digest = _require_sha256(payload[hash_field], f"{label} hash")
    unhashed = dict(payload)
    unhashed.pop(hash_field)
    if sha256_hex(canonical_json_bytes(unhashed)) != digest:
        raise PersistentPNDAGCheckpointStoreError(f"{label} content hash mismatch")
    return digest


def _decode_lower_hex(value: Any, label: str) -> bytes:
    if type(value) is not str:
        raise PersistentPNDAGCheckpointStoreError(f"{label} must be text")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as exc:
        raise PersistentPNDAGCheckpointStoreError(
            f"{label} is not hexadecimal"
        ) from exc
    if not decoded or decoded.hex() != value:
        raise PersistentPNDAGCheckpointStoreError(
            f"{label} must be nonempty canonical lowercase hexadecimal"
        )
    return decoded


def _checkpoint_metadata(raw: bytes) -> _CheckpointMetadata:
    payload = _require_keys(
        _decode_canonical_json(raw, "persistent PNDAG checkpoint"),
        _CHECKPOINT_KEYS,
        "persistent PNDAG checkpoint",
    )
    checkpoint_sha256 = _verify_self_hash(payload, "checkpoint_sha256", "checkpoint")
    committed_expansions = _require_int(
        payload["committed_expansions"],
        "checkpoint committed expansions",
        minimum=0,
        maximum=_UINT64_MAX,
    )
    graph_sha256 = _require_sha256(payload["graph_sha256"], "checkpoint graph hash")
    root_id = _require_int(
        payload["root_id"],
        "checkpoint root id",
        minimum=0,
        maximum=_UINT64_MAX,
    )
    if root_id != 0:
        raise PersistentPNDAGCheckpointStoreError("checkpoint root must be node zero")
    nodes = payload["nodes"]
    if not isinstance(nodes, list) or not nodes:
        raise PersistentPNDAGCheckpointStoreError(
            "checkpoint must contain its root node"
        )
    declared_node_count = _require_int(
        payload["node_count"],
        "checkpoint node count",
        minimum=1,
        maximum=_UINT64_MAX,
    )
    if declared_node_count != len(nodes):
        raise PersistentPNDAGCheckpointStoreError("checkpoint node count mismatch")

    edge_count = 0
    expanded_count = 0
    exact_states: set[str] = set()
    for expected_id, raw_node in enumerate(nodes):
        node = _require_keys(raw_node, _NODE_KEYS, "checkpoint node record")
        node_id = _require_int(
            node["id"], "checkpoint node id", minimum=0, maximum=_UINT64_MAX
        )
        if node_id != expected_id:
            raise PersistentPNDAGCheckpointStoreError(
                "checkpoint node ids must be contiguous and ordered"
            )
        _require_sha256(node["digest"], "checkpoint node digest")
        _require_int(
            node["rank"],
            "checkpoint node rank",
            minimum=0,
            maximum=_UINT64_MAX,
        )
        _require_int(
            node["cached_proof"],
            "checkpoint cached proof",
            minimum=0,
            maximum=_UINT64_MAX,
        )
        _require_int(
            node["cached_disproof"],
            "checkpoint cached disproof",
            minimum=0,
            maximum=_UINT64_MAX,
        )
        state_bytes = _decode_lower_hex(node["state_hex"], "checkpoint node state")
        state_hex = state_bytes.hex()
        if state_hex in exact_states:
            raise PersistentPNDAGCheckpointStoreError(
                "checkpoint contains duplicate exact state records"
            )
        exact_states.add(state_hex)
        expansion = node["expansion"]
        if type(expansion) is not str or expansion not in _EXPANSION_VALUES:
            raise PersistentPNDAGCheckpointStoreError(
                "checkpoint node expansion marker is invalid"
            )
        children = node["children"]
        if not isinstance(children, list):
            raise PersistentPNDAGCheckpointStoreError(
                "checkpoint node children must be an array"
            )
        if expansion == "expanded":
            if not children:
                raise PersistentPNDAGCheckpointStoreError(
                    "expanded checkpoint node has no edges"
                )
            expanded_count += 1
        elif children:
            raise PersistentPNDAGCheckpointStoreError(
                "only expanded checkpoint nodes may contain edges"
            )
        moves: set[int] = set()
        for raw_edge in children:
            edge = _require_keys(raw_edge, _EDGE_KEYS, "checkpoint edge")
            move = _require_int(
                edge["move"],
                "checkpoint edge move",
                minimum=_INT64_MIN,
                maximum=_INT64_MAX,
            )
            if move in moves:
                raise PersistentPNDAGCheckpointStoreError(
                    "checkpoint node has duplicate move edges"
                )
            moves.add(move)
            child_id = _require_int(
                edge["child_id"],
                "checkpoint edge child id",
                minimum=0,
                maximum=_UINT64_MAX,
            )
            if child_id >= len(nodes):
                raise PersistentPNDAGCheckpointStoreError(
                    "checkpoint edge references an unknown node"
                )
            edge_count += 1
    if expanded_count != committed_expansions:
        raise PersistentPNDAGCheckpointStoreError(
            "checkpoint expansion count does not match committed work"
        )
    declared_edge_count = _require_int(
        payload["edge_count"],
        "checkpoint edge count",
        minimum=0,
        maximum=_UINT64_MAX,
    )
    if declared_edge_count != edge_count:
        raise PersistentPNDAGCheckpointStoreError("checkpoint edge count mismatch")

    root_node = nodes[0]
    root_state = _decode_lower_hex(root_node["state_hex"], "root state hex")
    root_state_object_id = _require_sha256(
        payload["root_state_object_id"], "root state object id"
    )
    if sha256_hex(root_state) != root_state_object_id:
        raise PersistentPNDAGCheckpointStoreError(
            "root state object id does not match exact root bytes"
        )
    root_proof = _require_int(
        payload["root_proof_number"],
        "checkpoint root proof number",
        minimum=0,
        maximum=_UINT64_MAX,
    )
    root_disproof = _require_int(
        payload["root_disproof_number"],
        "checkpoint root disproof number",
        minimum=0,
        maximum=_UINT64_MAX,
    )
    if (root_proof, root_disproof) != (
        root_node["cached_proof"],
        root_node["cached_disproof"],
    ):
        raise PersistentPNDAGCheckpointStoreError(
            "checkpoint root proof cache mismatch"
        )
    if root_proof == 0 and root_disproof == 0:
        raise PersistentPNDAGCheckpointStoreError(
            "checkpoint root cannot be both proven and disproven"
        )
    expected_status = (
        "PROVEN"
        if root_proof == 0
        else "DISPROVEN"
        if root_disproof == 0
        else "UNKNOWN"
    )
    status = payload["status"]
    if type(status) is not str or status != expected_status:
        raise PersistentPNDAGCheckpointStoreError("checkpoint status is invalid")

    try:
        rules_object = Rules.from_dict(payload["rules"])
    except (TypeError, ValueError) as exc:
        raise PersistentPNDAGCheckpointStoreError(
            "checkpoint rules are invalid"
        ) from exc
    rules = payload["rules"]
    if not _exact_json_equal(rules, rules_object.as_dict()):
        raise PersistentPNDAGCheckpointStoreError("checkpoint rules are not type-exact")
    rules_sha256 = _require_sha256(payload["rules_sha256"], "rules hash")
    if sha256_hex(canonical_json_bytes(rules)) != rules_sha256:
        raise PersistentPNDAGCheckpointStoreError(
            "rules hash does not match exact rules"
        )
    threshold2 = _require_int(
        payload["threshold2"],
        "checkpoint threshold",
        minimum=_INT64_MIN,
        maximum=_INT64_MAX,
    )
    run = {
        "algorithm": payload["algorithm"],
        "checkpoint_format": payload["format"],
        "digest_index": payload["digest_index"],
        "history_digest_index": payload["history_digest_index"],
        "history_format": payload["history_format"],
        "move_order": payload["move_order"],
        "proof_arithmetic": payload["proof_arithmetic"],
        "root_state_hex": root_state.hex(),
        "root_state_object_id": root_state_object_id,
        "rules": rules,
        "rules_sha256": rules_sha256,
        "scope": payload["scope"],
        "selection": payload["selection"],
        "state_format": payload["state_format"],
        "symmetry": payload["symmetry"],
        "threshold2": threshold2,
    }
    _validate_run_envelope(run)
    run_sha256 = sha256_hex(canonical_json_bytes(run))
    return _CheckpointMetadata(
        file_sha256=sha256_hex(raw),
        byte_length=len(raw),
        checkpoint_sha256=checkpoint_sha256,
        committed_expansions=committed_expansions,
        graph_sha256=graph_sha256,
        status=status,
        run=run,
        run_sha256=run_sha256,
        payload=payload,
    )


def _validate_checkpoint_extension(
    previous: _CheckpointMetadata,
    newer: _CheckpointMetadata,
) -> None:
    """Require ``newer`` to preserve every exact committed graph fact."""

    if not _exact_json_equal(previous.run, newer.run):
        raise PersistentPNDAGCheckpointStoreError(
            "checkpoint exact run envelope changed within one lineage"
        )
    if newer.committed_expansions <= previous.committed_expansions:
        raise PersistentPNDAGCheckpointStoreError(
            "checkpoint lineage did not strictly increase committed work"
        )
    if previous.status != "UNKNOWN":
        raise PersistentPNDAGCheckpointStoreError(
            "a solved checkpoint is a final generation"
        )
    previous_nodes = previous.payload["nodes"]
    newer_nodes = newer.payload["nodes"]
    if len(newer_nodes) < len(previous_nodes):
        raise PersistentPNDAGCheckpointStoreError(
            "checkpoint lineage dropped exact graph nodes"
        )

    immutable_identity = ("id", "digest", "rank", "state_hex")
    for node_id, previous_node in enumerate(previous_nodes):
        newer_node = newer_nodes[node_id]
        for field in immutable_identity:
            if not _exact_json_equal(previous_node[field], newer_node[field]):
                raise PersistentPNDAGCheckpointStoreError(
                    "checkpoint lineage changed an existing exact node"
                )
        previous_expansion = previous_node["expansion"]
        newer_expansion = newer_node["expansion"]
        if previous_expansion in {"expanded", "terminal"}:
            if previous_expansion != newer_expansion or not _exact_json_equal(
                previous_node["children"], newer_node["children"]
            ):
                raise PersistentPNDAGCheckpointStoreError(
                    "checkpoint lineage dropped or changed committed node expansion"
                )
        elif newer_expansion not in {"unexpanded", "expanded"}:
            raise PersistentPNDAGCheckpointStoreError(
                "checkpoint lineage changed an open node incompatibly"
            )
        elif newer_expansion == "unexpanded" and not _exact_json_equal(
            previous_node["children"], newer_node["children"]
        ):
            raise PersistentPNDAGCheckpointStoreError(
                "checkpoint lineage changed an unexpanded node's edges"
            )


def _checkpoint_entry(metadata: _CheckpointMetadata) -> dict[str, Any]:
    return {
        "byte_length": metadata.byte_length,
        "checkpoint_sha256": metadata.checkpoint_sha256,
        "committed_expansions": metadata.committed_expansions,
        "file": f"{metadata.file_sha256}.json",
        "file_sha256": metadata.file_sha256,
        "graph_sha256": metadata.graph_sha256,
        "status": metadata.status,
    }


def _tip_from_manifest(manifest: dict[str, Any]) -> PersistentPNDAGCheckpointTip:
    checkpoint = manifest["checkpoint"]
    return PersistentPNDAGCheckpointTip(
        generation=manifest["generation"],
        manifest_sha256=manifest["manifest_sha256"],
        checkpoint_file_sha256=checkpoint["file_sha256"],
        checkpoint_sha256=checkpoint["checkpoint_sha256"],
        run_sha256=manifest["run_sha256"],
        graph_sha256=checkpoint["graph_sha256"],
        committed_expansions=checkpoint["committed_expansions"],
    )


class PersistentPNDAGCheckpointStore:
    """Single-writer immutable checkpoint lineage with pinned restart.

    Use :meth:`first_open` only when no ``CURRENT`` generation exists.  Use
    :meth:`resume` for every restart and supply the exact tip returned by the
    last successful :meth:`publish`.  There is no unpinned existing-store mode.
    """

    def __init__(self, root: str | Path, *, _mode: str, _tip: Any = None) -> None:
        self.root = Path(root)
        self.checkpoints_directory = self.root / "checkpoints"
        self.manifests_directory = self.root / "manifests"
        self.pointer_path = self.root / "CURRENT"
        self.snapshot: PersistentPNDAGCheckpointTip | None = None
        self._manifest: dict[str, Any] | None = None

        if _mode == "first":
            if _tip is not None:
                raise TypeError("first open cannot accept an existing tip")
            _mkdir_durable(self.root)
            if self.pointer_path.exists():
                raise PersistentPNDAGCheckpointStoreError(
                    "CURRENT already exists; pinned resume is mandatory"
                )
            _mkdir_durable(self.checkpoints_directory)
            _mkdir_durable(self.manifests_directory)
            if any(self.checkpoints_directory.iterdir()) or any(
                self.manifests_directory.iterdir()
            ):
                raise PersistentPNDAGCheckpointStoreError(
                    "first open found existing checkpoint artifacts; refuse to "
                    "reinterpret a damaged or unpublished lineage as new"
                )
        elif _mode == "resume":
            if not isinstance(_tip, PersistentPNDAGCheckpointTip):
                raise TypeError("resume requires a PersistentPNDAGCheckpointTip")
            if not self.root.is_dir():
                raise PersistentPNDAGCheckpointStoreError(
                    "checkpoint store root is missing or is not a directory"
                )
            if not self.checkpoints_directory.is_dir() or not (
                self.manifests_directory.is_dir()
            ):
                raise PersistentPNDAGCheckpointStoreError(
                    "checkpoint store immutable directories are missing"
                )
            if not self.pointer_path.exists():
                raise PersistentPNDAGCheckpointStoreError(
                    "CURRENT is missing; this is not an existing published store"
                )
            self._load_current(expected_tip=_tip)
        else:
            raise TypeError("use first_open() or resume()")

    @classmethod
    def first_open(cls, root: str | Path) -> "PersistentPNDAGCheckpointStore":
        """Open a directory that has never published ``CURRENT``."""

        return cls(root, _mode="first")

    @classmethod
    def resume(
        cls,
        root: str | Path,
        *,
        expected_tip: PersistentPNDAGCheckpointTip,
    ) -> "PersistentPNDAGCheckpointStore":
        """Open an existing store only if its complete external tip matches."""

        return cls(root, _mode="resume", _tip=expected_tip)

    @classmethod
    def recover_prepared(
        cls,
        root: str | Path,
        *,
        preparation: PersistentPNDAGCheckpointPreparation,
    ) -> "PersistentPNDAGCheckpointStore":
        """Idempotently finish a caller-journaled two-phase publication.

        The preparation must have been retained outside this store before the
        original commit attempt.  No forward generation is inferred from disk.
        """

        if not isinstance(preparation, PersistentPNDAGCheckpointPreparation):
            raise TypeError(
                "preparation must be a PersistentPNDAGCheckpointPreparation"
            )
        obj = cls.__new__(cls)
        obj.root = Path(root)
        obj.checkpoints_directory = obj.root / "checkpoints"
        obj.manifests_directory = obj.root / "manifests"
        obj.pointer_path = obj.root / "CURRENT"
        obj.snapshot = None
        obj._manifest = None
        if not obj.root.is_dir():
            raise PersistentPNDAGCheckpointStoreError(
                "checkpoint store root is missing or is not a directory"
            )
        if not obj.checkpoints_directory.is_dir() or not (
            obj.manifests_directory.is_dir()
        ):
            raise PersistentPNDAGCheckpointStoreError(
                "checkpoint store immutable directories are missing"
            )

        intended_manifest = obj._manifest_for_preparation(preparation)
        if obj.pointer_path.exists():
            _pointer, current_manifest = obj._read_pointer()
            obj._validate_chain(current_manifest)
            current_tip = _tip_from_manifest(current_manifest)
            if current_tip == preparation.intended_tip:
                obj._manifest = intended_manifest
                obj.snapshot = current_tip
                _fsync_file(obj.pointer_path)
                _fsync_directory(obj.root)
                return obj
            if (
                preparation.previous_tip is None
                or current_tip != preparation.previous_tip
            ):
                raise PersistentPNDAGCheckpointStoreError(
                    "CURRENT matches neither prepared predecessor nor intended tip"
                )
            obj._manifest = current_manifest
            obj.snapshot = current_tip
        elif preparation.previous_tip is not None:
            raise PersistentPNDAGCheckpointStoreError(
                "CURRENT is missing for a non-genesis preparation"
            )

        obj.commit_prepared(preparation)
        return obj

    def _read_manifest(self, digest: str) -> dict[str, Any]:
        digest = _require_sha256(digest, "manifest filename hash")
        path = self.manifests_directory / f"{digest}.json"
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise PersistentPNDAGCheckpointStoreError(
                "referenced immutable manifest is missing"
            ) from exc
        manifest = _require_keys(
            _decode_canonical_json(raw, "checkpoint manifest"),
            _MANIFEST_KEYS,
            "checkpoint manifest",
        )
        supplied = _verify_self_hash(manifest, "manifest_sha256", "checkpoint manifest")
        if supplied != digest:
            raise PersistentPNDAGCheckpointStoreError(
                "manifest filename does not match its content hash"
            )
        if manifest["format"] != CHECKPOINT_GENERATION_MANIFEST_FORMAT:
            raise PersistentPNDAGCheckpointStoreError(
                "unsupported checkpoint manifest format"
            )
        if manifest["scope"] != CHECKPOINT_GENERATION_SCOPE:
            raise PersistentPNDAGCheckpointStoreError(
                "checkpoint manifest scope mismatch"
            )
        _require_int(
            manifest["generation"],
            "manifest generation",
            minimum=1,
            maximum=_UINT64_MAX,
        )
        previous = manifest["previous_manifest_sha256"]
        if previous is not None:
            _require_sha256(previous, "previous manifest hash")
        run = _validate_run_envelope(manifest["run"])
        run_sha256 = _require_sha256(manifest["run_sha256"], "run hash")
        if sha256_hex(canonical_json_bytes(run)) != run_sha256:
            raise PersistentPNDAGCheckpointStoreError(
                "run hash does not match the exact run envelope"
            )
        checkpoint = _require_keys(
            manifest["checkpoint"],
            _CHECKPOINT_ENTRY_KEYS,
            "manifest checkpoint entry",
        )
        _require_int(
            checkpoint["byte_length"],
            "checkpoint byte length",
            minimum=1,
            maximum=_UINT64_MAX,
        )
        _require_int(
            checkpoint["committed_expansions"],
            "manifest committed expansions",
            minimum=0,
            maximum=_UINT64_MAX,
        )
        for label, field in (
            ("checkpoint file hash", "file_sha256"),
            ("checkpoint hash", "checkpoint_sha256"),
            ("checkpoint graph hash", "graph_sha256"),
        ):
            _require_sha256(checkpoint[field], label)
        if checkpoint["file"] != f"{checkpoint['file_sha256']}.json":
            raise PersistentPNDAGCheckpointStoreError(
                "checkpoint filename is not derived from its exact file hash"
            )
        if (
            type(checkpoint["status"]) is not str
            or checkpoint["status"] not in _STATUS_VALUES
        ):
            raise PersistentPNDAGCheckpointStoreError(
                "manifest checkpoint status is invalid"
            )
        return manifest

    def _checkpoint_bytes_for_manifest(
        self, manifest: dict[str, Any]
    ) -> tuple[bytes, _CheckpointMetadata]:
        checkpoint = manifest["checkpoint"]
        path = self.checkpoints_directory / checkpoint["file"]
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise PersistentPNDAGCheckpointStoreError(
                "referenced immutable checkpoint is missing"
            ) from exc
        if len(raw) != checkpoint["byte_length"]:
            raise PersistentPNDAGCheckpointStoreError(
                "checkpoint byte length disagrees with its manifest"
            )
        if sha256_hex(raw) != checkpoint["file_sha256"]:
            raise PersistentPNDAGCheckpointStoreError(
                "checkpoint file hash disagrees with its manifest"
            )
        metadata = _checkpoint_metadata(raw)
        if not _exact_json_equal(_checkpoint_entry(metadata), checkpoint):
            raise PersistentPNDAGCheckpointStoreError(
                "checkpoint metadata disagrees with its manifest"
            )
        if not _exact_json_equal(metadata.run, manifest["run"]):
            raise PersistentPNDAGCheckpointStoreError(
                "checkpoint exact run envelope disagrees with its manifest"
            )
        if metadata.run_sha256 != manifest["run_sha256"]:
            raise PersistentPNDAGCheckpointStoreError(
                "checkpoint run hash disagrees with its manifest"
            )
        return raw, metadata

    def _read_pointer(self) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            raw = self.pointer_path.read_bytes()
        except FileNotFoundError as exc:
            raise PersistentPNDAGCheckpointStoreError(
                "published CURRENT pointer is missing"
            ) from exc
        pointer = _require_keys(
            _decode_canonical_json(raw, "CURRENT pointer"),
            _POINTER_KEYS,
            "CURRENT pointer",
        )
        _verify_self_hash(pointer, "pointer_sha256", "CURRENT pointer")
        if pointer["format"] != CHECKPOINT_GENERATION_POINTER_FORMAT:
            raise PersistentPNDAGCheckpointStoreError(
                "unsupported CURRENT pointer format"
            )
        generation = _require_int(
            pointer["generation"],
            "CURRENT generation",
            minimum=1,
            maximum=_UINT64_MAX,
        )
        manifest_sha256 = _require_sha256(
            pointer["manifest_sha256"], "CURRENT manifest hash"
        )
        if pointer["manifest_file"] != f"{manifest_sha256}.json":
            raise PersistentPNDAGCheckpointStoreError(
                "CURRENT manifest filename is not canonical"
            )
        manifest = self._read_manifest(manifest_sha256)
        if manifest["generation"] != generation:
            raise PersistentPNDAGCheckpointStoreError(
                "CURRENT and manifest generations disagree"
            )
        return pointer, manifest

    def _validate_chain(self, current: dict[str, Any]) -> None:
        manifest = current
        seen: set[str] = set()
        current_run_bytes = canonical_json_bytes(current["run"])
        newer_metadata: _CheckpointMetadata | None = None
        expected_generation = current["generation"]
        while True:
            digest = manifest["manifest_sha256"]
            if digest in seen:
                raise PersistentPNDAGCheckpointStoreError(
                    "checkpoint manifest lineage contains a cycle"
                )
            seen.add(digest)
            if manifest["generation"] != expected_generation:
                raise PersistentPNDAGCheckpointStoreError(
                    "checkpoint manifest generations are not contiguous"
                )
            if canonical_json_bytes(manifest["run"]) != current_run_bytes:
                raise PersistentPNDAGCheckpointStoreError(
                    "checkpoint run envelope changed within one lineage"
                )
            _raw, metadata = self._checkpoint_bytes_for_manifest(manifest)
            if newer_metadata is not None:
                _validate_checkpoint_extension(metadata, newer_metadata)
            previous = manifest["previous_manifest_sha256"]
            if expected_generation == 1:
                if previous is not None:
                    raise PersistentPNDAGCheckpointStoreError(
                        "first checkpoint manifest cannot name a predecessor"
                    )
                return
            if previous is None:
                raise PersistentPNDAGCheckpointStoreError(
                    "checkpoint manifest lineage is prematurely truncated"
                )
            newer_metadata = metadata
            expected_generation -= 1
            manifest = self._read_manifest(previous)

    def _load_current(self, *, expected_tip: PersistentPNDAGCheckpointTip) -> None:
        _pointer, manifest = self._read_pointer()
        self._validate_chain(manifest)
        actual_tip = _tip_from_manifest(manifest)
        if actual_tip != expected_tip:
            raise PersistentPNDAGCheckpointStoreError(
                "CURRENT does not match the externally expected checkpoint tip"
            )
        self._manifest = manifest
        self.snapshot = actual_tip

    def _assert_disk_tip_unchanged(self) -> None:
        if self.snapshot is None:
            if self.pointer_path.exists():
                raise PersistentPNDAGCheckpointStoreError(
                    "CURRENT appeared after first open; one-writer discipline failed"
                )
            return
        self._load_current(expected_tip=self.snapshot)

    @staticmethod
    def _serialize_checkpoint(dag: PersistentProofNumberDAG) -> bytes:
        with tempfile.TemporaryDirectory(prefix="ugts-pndag-checkpoint-") as raw_dir:
            path = Path(raw_dir) / "checkpoint.json"
            dag.save_checkpoint(path)
            return path.read_bytes()

    def _manifest_for_preparation(
        self, preparation: PersistentPNDAGCheckpointPreparation
    ) -> dict[str, Any]:
        manifest = self._read_manifest(preparation.intended_tip.manifest_sha256)
        self._validate_chain(manifest)
        if _tip_from_manifest(manifest) != preparation.intended_tip:
            raise PersistentPNDAGCheckpointStoreError(
                "prepared intended tip disagrees with its immutable manifest"
            )
        previous = preparation.previous_tip
        expected_previous_hash = None if previous is None else previous.manifest_sha256
        if manifest["previous_manifest_sha256"] != expected_previous_hash:
            raise PersistentPNDAGCheckpointStoreError(
                "prepared manifest does not extend its exact predecessor"
            )
        if previous is not None:
            previous_manifest = self._read_manifest(previous.manifest_sha256)
            if _tip_from_manifest(previous_manifest) != previous:
                raise PersistentPNDAGCheckpointStoreError(
                    "prepared predecessor tip disagrees with its manifest"
                )
        return manifest

    @staticmethod
    def _pointer_bytes(manifest: dict[str, Any]) -> bytes:
        manifest_sha256 = manifest["manifest_sha256"]
        pointer_without_hash = {
            "format": CHECKPOINT_GENERATION_POINTER_FORMAT,
            "generation": manifest["generation"],
            "manifest_file": f"{manifest_sha256}.json",
            "manifest_sha256": manifest_sha256,
        }
        pointer, _pointer_sha256 = _self_hashed_payload(
            pointer_without_hash, "pointer_sha256"
        )
        return canonical_json_bytes(pointer) + b"\n"

    def prepare(
        self, dag: PersistentProofNumberDAG
    ) -> PersistentPNDAGCheckpointPreparation:
        """Fsync immutable next-generation files without changing ``CURRENT``."""

        if not isinstance(dag, PersistentProofNumberDAG):
            raise TypeError("dag must be a PersistentProofNumberDAG")
        self._assert_disk_tip_unchanged()
        raw = self._serialize_checkpoint(dag)
        metadata = _checkpoint_metadata(raw)

        if self._manifest is not None:
            if not _exact_json_equal(metadata.run, self._manifest["run"]):
                raise PersistentPNDAGCheckpointStoreError(
                    "cannot publish a different root, rules, threshold, or algorithm"
                )
            _previous_raw, previous_metadata = self._checkpoint_bytes_for_manifest(
                self._manifest
            )
            _validate_checkpoint_extension(previous_metadata, metadata)
        previous_hash = None if self.snapshot is None else self.snapshot.manifest_sha256
        generation = 1 if self.snapshot is None else self.snapshot.generation + 1
        if generation > _UINT64_MAX:
            raise OverflowError("checkpoint generation counter exhausted")

        checkpoint_path = self.checkpoints_directory / f"{metadata.file_sha256}.json"
        try:
            _publish_immutable(checkpoint_path, raw)
        except SegmentStoreError as exc:
            raise PersistentPNDAGCheckpointStoreError(str(exc)) from exc

        manifest_without_hash = {
            "checkpoint": _checkpoint_entry(metadata),
            "format": CHECKPOINT_GENERATION_MANIFEST_FORMAT,
            "generation": generation,
            "previous_manifest_sha256": previous_hash,
            "run": metadata.run,
            "run_sha256": metadata.run_sha256,
            "scope": CHECKPOINT_GENERATION_SCOPE,
        }
        manifest, manifest_sha256 = _self_hashed_payload(
            manifest_without_hash, "manifest_sha256"
        )
        manifest_raw = canonical_json_bytes(manifest) + b"\n"
        manifest_path = self.manifests_directory / f"{manifest_sha256}.json"
        try:
            _publish_immutable(manifest_path, manifest_raw)
        except SegmentStoreError as exc:
            raise PersistentPNDAGCheckpointStoreError(str(exc)) from exc
        intended_tip = _tip_from_manifest(manifest)
        preparation = PersistentPNDAGCheckpointPreparation(
            previous_tip=self.snapshot,
            intended_tip=intended_tip,
        )

        # Verify the complete immutable intent before handing it to the caller
        # for durable external journaling.
        self._manifest_for_preparation(preparation)
        self._assert_disk_tip_unchanged()
        return preparation

    def commit_prepared(
        self, preparation: PersistentPNDAGCheckpointPreparation
    ) -> PersistentPNDAGCheckpointTip:
        """Atomically install one externally retained preparation.

        Calling this again after the exact intended generation became current
        is idempotent.  A divergent on-disk generation is never adopted.
        """

        if not isinstance(preparation, PersistentPNDAGCheckpointPreparation):
            raise TypeError(
                "preparation must be a PersistentPNDAGCheckpointPreparation"
            )
        # Validate the complete externally retained record even on an
        # idempotent replay.  Merely matching its intended tip is insufficient:
        # a forged predecessor field must not be silently accepted after that
        # intended generation has already become CURRENT.
        manifest = self._manifest_for_preparation(preparation)
        previous_tip = preparation.previous_tip
        intended_tip = preparation.intended_tip
        if self.snapshot not in {previous_tip, intended_tip}:
            raise PersistentPNDAGCheckpointStoreError(
                "prepared predecessor does not match the open checkpoint tip"
            )

        # A prior call can replace CURRENT and then fail before updating this
        # live object's snapshot.  Inspect the independently validated disk tip
        # and accept only the exact predecessor or exact intended generation.
        # This makes a direct retry genuinely idempotent without adopting any
        # divergent on-disk lineage.
        disk_manifest: dict[str, Any] | None = None
        if self.pointer_path.exists():
            _pointer, disk_manifest = self._read_pointer()
            self._validate_chain(disk_manifest)
            disk_tip: PersistentPNDAGCheckpointTip | None = _tip_from_manifest(
                disk_manifest
            )
        else:
            disk_tip = None
        if disk_tip == intended_tip:
            self._manifest = manifest
            self.snapshot = intended_tip
            try:
                _fsync_file(self.pointer_path)
                _fsync_directory(self.root)
            except Exception as barrier_error:
                raise PersistentPNDAGCheckpointCommitUncertain(
                    preparation
                ) from barrier_error
            return intended_tip
        if disk_tip != previous_tip or self.snapshot != previous_tip:
            raise PersistentPNDAGCheckpointStoreError(
                "CURRENT matches neither prepared predecessor nor intended tip"
            )
        self._manifest = disk_manifest

        pointer_raw = self._pointer_bytes(manifest)

        # Catch a stale writer immediately before the only mutable operation.
        self._assert_disk_tip_unchanged()
        try:
            _atomic_replace_bytes(self.pointer_path, pointer_raw)
        except Exception as publication_error:
            # A rename can succeed and its directory barrier can fail.  If the
            # exact intended tip is already visible, retry both barriers and
            # accept it.  If validation itself fails, report an ordinary
            # pre-publication error only after independently re-confirming the
            # exact predecessor; every other state is commit-uncertain.
            try:
                self._load_current(expected_tip=intended_tip)
            except Exception as intended_validation_error:
                try:
                    self._assert_disk_tip_unchanged()
                except Exception as predecessor_validation_error:
                    raise PersistentPNDAGCheckpointCommitUncertain(
                        preparation
                    ) from predecessor_validation_error
                raise publication_error from intended_validation_error
            try:
                _fsync_file(self.pointer_path)
                _fsync_directory(self.root)
            except Exception as retry_error:
                raise PersistentPNDAGCheckpointCommitUncertain(
                    preparation
                ) from retry_error
            return intended_tip

        try:
            self._load_current(expected_tip=intended_tip)
        except Exception as validation_error:
            # CURRENT may already be durable even if post-replace validation
            # ran out of resources.  Reconcile once; otherwise return an error
            # carrying the already externally journalable preparation.
            try:
                self._load_current(expected_tip=intended_tip)
                _fsync_file(self.pointer_path)
                _fsync_directory(self.root)
            except Exception:
                raise PersistentPNDAGCheckpointCommitUncertain(
                    preparation
                ) from validation_error
        return intended_tip

    def publish(self, dag: PersistentProofNumberDAG) -> PersistentPNDAGCheckpointTip:
        """Convenience prepare+commit for bounded same-process callers.

        A crash-robust campaign must call :meth:`prepare`, durably retain the
        returned record outside this store, and only then call
        :meth:`commit_prepared`.
        """

        return self.commit_prepared(self.prepare(dag))

    def load_dag(
        self,
        *,
        expected_rules: Rules,
        expected_threshold2: int,
        expected_root_state_bytes: bytes,
        digest_fn: DigestFunction | None = None,
        digest_name: str | None = None,
        history_digest_fn: DigestFunction | None = None,
        history_digest_name: str | None = None,
    ) -> PersistentProofNumberDAG:
        """Load the exact verified current checkpoint through the strict DAG loader."""

        if self.snapshot is None or self._manifest is None:
            raise PersistentPNDAGCheckpointStoreError(
                "cannot load before a checkpoint generation is published"
            )
        if not isinstance(expected_rules, Rules):
            raise TypeError("expected_rules must be a Rules instance")
        if type(expected_threshold2) is not int:
            raise TypeError("expected_threshold2 must be an integer")
        if (
            type(expected_root_state_bytes) is not bytes
            or not expected_root_state_bytes
        ):
            raise TypeError("expected_root_state_bytes must be nonempty bytes")

        self._load_current(expected_tip=self.snapshot)
        run = self._manifest["run"]
        if run["rules"] != expected_rules.as_dict():
            raise PersistentPNDAGCheckpointStoreError(
                "manifest rules do not match the exact expected rules"
            )
        if run["threshold2"] != expected_threshold2:
            raise PersistentPNDAGCheckpointStoreError(
                "manifest threshold does not match the expected threshold"
            )
        if _decode_lower_hex(run["root_state_hex"], "manifest root state hex") != (
            expected_root_state_bytes
        ):
            raise PersistentPNDAGCheckpointStoreError(
                "manifest root does not match the exact expected target"
            )

        # Read and verify once, then materialize those exact immutable bytes in
        # a private temporary directory.  The semantic loader never reopens the
        # content-addressed source after its verification.
        raw, _metadata = self._checkpoint_bytes_for_manifest(self._manifest)
        with tempfile.TemporaryDirectory(prefix="ugts-pndag-loader-") as raw_dir:
            path = Path(raw_dir) / "checkpoint.json"
            with path.open("xb") as stream:
                if stream.write(raw) != len(raw):
                    raise OSError("short write while materializing checkpoint")
                stream.flush()
                os.fsync(stream.fileno())
            loaded = PersistentProofNumberDAG.load_checkpoint(
                path,
                expected_rules=expected_rules,
                expected_threshold2=expected_threshold2,
                expected_root_state_bytes=expected_root_state_bytes,
                digest_fn=digest_fn,
                digest_name=digest_name,
                history_digest_fn=history_digest_fn,
                history_digest_name=history_digest_name,
            )
            # The strict loader reopens a pathname.  Re-serialize the returned
            # object and compare exact bytes so a same-user temp-path swap at
            # that boundary cannot silently return a different valid graph.
            if self._serialize_checkpoint(loaded) != raw:
                raise PersistentPNDAGCheckpointStoreError(
                    "semantic loader returned a graph different from verified bytes"
                )
            return loaded


__all__ = [
    "CHECKPOINT_GENERATION_MANIFEST_FORMAT",
    "CHECKPOINT_GENERATION_POINTER_FORMAT",
    "CHECKPOINT_GENERATION_SCOPE",
    "CHECKPOINT_PREPARATION_FORMAT",
    "PersistentPNDAGCheckpointCommitUncertain",
    "PersistentPNDAGCheckpointPreparation",
    "PersistentPNDAGCheckpointStore",
    "PersistentPNDAGCheckpointStoreError",
    "PersistentPNDAGCheckpointTip",
]
