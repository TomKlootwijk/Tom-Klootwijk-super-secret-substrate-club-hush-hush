"""Audited, certificate-producing one-hop WDL propagation.

The proof DAG is an immutable collection of exact ``UNKNOWN`` states and
legal-move occurrences.  This module derives at most one new fact from one
audited overlay snapshot, builds a self-contained WDL certificate for it, runs
the independent verifier, and then asks the append-only overlay to persist it.

No frontier occurrence is itself proof authority.  Duplicate occurrences of
the same UCI action are collapsed only after each one independently replays to
the same full child-node identity.  LOSS and DRAW require complete canonical
UCI coverage; WIN requires one exact child LOSS witness.  Draw claims remain
actions owned by the parent player.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

from .game_state import (
    RULE_PROFILE_ID,
    automatic_status,
    current_claim_actions,
    game_state_sha256,
    intended_move_claims,
    validate_history_reachability,
)
from .game_theory import WDL
from .hashing import canonical_json_bytes
from .proof_dag import DAGNode, ProofDAG, node_identity_sha256
from .rules import apply_move, legal_moves, move_to_san
from .verified_overlay import (
    MAX_CERTIFICATE_BYTES,
    VerifiedCertificateBinding,
    VerifiedCertificateOverlay,
)
from .wdl import (
    BUNDLE_SCHEMA,
    NODE_SCHEMA,
    invert_child,
    verify_wdl_certificate,
)


PROPAGATION_RESULT_SCHEMA = "ugts-chess-wdl-one-hop-propagation-result-1.0"


@dataclass(frozen=True, slots=True)
class WDLPropagationResult:
    """Structured result of one conservative propagation attempt."""

    node_sha256: str
    value: WDL
    status: str  # promoted | already_verified | unknown
    reason: str
    detail: str
    promoted: bool
    witness_move: str | None = None
    legal_moves: tuple[str, ...] = ()
    used_moves: tuple[str, ...] = ()
    missing_frontier_moves: tuple[str, ...] = ()
    missing_certificate_moves: tuple[str, ...] = ()
    ambiguous_moves: tuple[str, ...] = ()
    certificate_sha256: str | None = None
    root_certificate_hash: str | None = None

    @property
    def exact(self) -> bool:
        return self.value != WDL.UNKNOWN

    def record(self) -> dict[str, object]:
        return {
            "schema": PROPAGATION_RESULT_SCHEMA,
            "node_sha256": self.node_sha256,
            "value": self.value.value,
            "status": self.status,
            "reason": self.reason,
            "detail": self.detail,
            "promoted": self.promoted,
            "witness_move": self.witness_move,
            "legal_moves": list(self.legal_moves),
            "used_moves": list(self.used_moves),
            "missing_frontier_moves": list(self.missing_frontier_moves),
            "missing_certificate_moves": list(self.missing_certificate_moves),
            "ambiguous_moves": list(self.ambiguous_moves),
            "certificate_sha256": self.certificate_sha256,
            "root_certificate_hash": self.root_certificate_hash,
        }


class WDLPropagationError(Exception):
    """Raised when audited dependencies violate an internal invariant."""


class _CompositionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _ParsedChildBundle:
    binding: VerifiedCertificateBinding
    root_hash: str
    root_depth: int
    reachable: Mapping[str, Mapping[str, object]]


def _unknown(
    node_sha256: str,
    *,
    reason: str,
    detail: str,
    legal_moves_: tuple[str, ...],
    missing_frontier_moves: tuple[str, ...] = (),
    missing_certificate_moves: tuple[str, ...] = (),
    ambiguous_moves: tuple[str, ...] = (),
) -> WDLPropagationResult:
    return WDLPropagationResult(
        node_sha256=node_sha256,
        value=WDL.UNKNOWN,
        status="unknown",
        reason=reason,
        detail=detail,
        promoted=False,
        legal_moves=legal_moves_,
        missing_frontier_moves=missing_frontier_moves,
        missing_certificate_moves=missing_certificate_moves,
        ambiguous_moves=ambiguous_moves,
    )


def _certificate_hash(record: Mapping[str, object]) -> str:
    payload = dict(record)
    payload.pop("certificate_hash", None)
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _composition_reason(error: _CompositionError) -> str:
    detail = str(error)
    if "size cap" in detail or "maximum is" in detail:
        return "certificate_size_limit"
    return "certificate_composition_failed"


def _claim_record(
    code: str,
    *,
    move: str | None = None,
    san: str | None = None,
) -> dict[str, object]:
    suffix = "current" if move is None else move
    return {
        "action_id": f"claim:{code}:{suffix}",
        "kind": "claim",
        "move": move,
        "san": san,
        "claim_code": code,
        "child_state_hash": None,
        "child_value": WDL.DRAW.value,
        "value_for_parent": WDL.DRAW.value,
        "child_certificate_hash": None,
        "exact": True,
    }


def _move_record(
    *,
    uci: str,
    san: str,
    child: DAGNode,
    binding: VerifiedCertificateBinding,
    child_certificate_hash: str,
) -> dict[str, object]:
    return {
        "action_id": f"move:{uci}",
        "kind": "move",
        "move": uci,
        "san": san,
        "claim_code": None,
        "child_state_hash": child.game_state_sha256,
        "child_value": binding.claimed_wdl.value,
        "value_for_parent": invert_child(binding.claimed_wdl).value,
        "child_certificate_hash": child_certificate_hash,
        "exact": True,
    }


def _parse_reachable_bundle(
    binding: VerifiedCertificateBinding,
) -> _ParsedChildBundle:
    """Parse only the root-reachable closure of an already audited binding."""

    try:
        decoded = json.loads(binding.certificate_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _CompositionError(f"audited certificate is no longer JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise _CompositionError("audited certificate bundle is not an object")
    nodes = decoded.get("nodes")
    root_hash = decoded.get("root_certificate_hash")
    if not isinstance(nodes, list) or not isinstance(root_hash, str):
        raise _CompositionError("audited certificate bundle has malformed roots")

    by_hash: dict[str, Mapping[str, object]] = {}
    for raw in nodes:
        if not isinstance(raw, dict):
            raise _CompositionError("audited certificate contains a non-object node")
        certificate_hash = raw.get("certificate_hash")
        if not isinstance(certificate_hash, str) or certificate_hash in by_hash:
            raise _CompositionError("audited certificate contains invalid node hashes")
        by_hash[certificate_hash] = raw
    if root_hash != binding.root_certificate_hash or root_hash not in by_hash:
        raise _CompositionError("audited certificate root binding diverged")

    reachable: dict[str, Mapping[str, object]] = {}
    pending = [root_hash]
    while pending:
        certificate_hash = pending.pop()
        if certificate_hash in reachable:
            continue
        record = by_hash.get(certificate_hash)
        if record is None:
            raise _CompositionError("certificate graph references a missing node")
        reachable[certificate_hash] = record
        children = record.get("children")
        if not isinstance(children, list):
            raise _CompositionError("certificate node has malformed children")
        for child in children:
            if not isinstance(child, dict):
                raise _CompositionError("certificate child is not an object")
            child_hash = child.get("child_certificate_hash")
            if child_hash is not None:
                if not isinstance(child_hash, str):
                    raise _CompositionError("certificate child hash is malformed")
                pending.append(child_hash)

    root_depth = by_hash[root_hash].get("depth_remaining")
    if (
        isinstance(root_depth, bool)
        or not isinstance(root_depth, int)
        or root_depth < 0
    ):
        raise _CompositionError("certificate root depth is malformed")
    return _ParsedChildBundle(binding, root_hash, root_depth, reachable)


def _rebase_bundle(
    parsed: _ParsedChildBundle,
    target_root_depth: int,
) -> tuple[str, dict[str, dict[str, object]]]:
    """Uniformly shift one reachable graph and hash it from leaves upward."""

    shift = target_root_depth - parsed.root_depth
    if shift < 0:
        raise _CompositionError("certificate rebase would create a negative shift")

    ordered: list[tuple[int, str, Mapping[str, object]]] = []
    for certificate_hash, record in parsed.reachable.items():
        depth = record.get("depth_remaining")
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
            raise _CompositionError("certificate node depth is malformed")
        ordered.append((depth, certificate_hash, record))
    ordered.sort(key=lambda item: (item[0], item[1]))

    rewritten_hashes: dict[str, str] = {}
    rewritten_nodes: dict[str, dict[str, object]] = {}
    for depth, old_hash, old_record in ordered:
        record = dict(old_record)
        record["depth_remaining"] = depth + shift
        old_children = old_record.get("children")
        if not isinstance(old_children, list):
            raise _CompositionError("certificate node children are malformed")
        children: list[dict[str, object]] = []
        for old_child in old_children:
            if not isinstance(old_child, dict):
                raise _CompositionError("certificate child is malformed")
            child = dict(old_child)
            old_child_hash = child.get("child_certificate_hash")
            if old_child_hash is not None:
                if not isinstance(old_child_hash, str):
                    raise _CompositionError("certificate child hash is malformed")
                new_child_hash = rewritten_hashes.get(old_child_hash)
                if new_child_hash is None:
                    raise _CompositionError(
                        "certificate graph is cyclic or not depth-decreasing"
                    )
                child["child_certificate_hash"] = new_child_hash
            children.append(child)
        record["children"] = children
        new_hash = _certificate_hash(record)
        record["certificate_hash"] = new_hash
        collision = rewritten_nodes.get(new_hash)
        if collision is not None and collision != record:
            raise _CompositionError("distinct certificate nodes share one SHA-256")
        rewritten_hashes[old_hash] = new_hash
        rewritten_nodes[new_hash] = record

    root_hash = rewritten_hashes.get(parsed.root_hash)
    if root_hash is None:
        raise _CompositionError("rebased certificate root is missing")
    return root_hash, rewritten_nodes


def _compose_bundle(
    *,
    node: DAGNode,
    value: WDL,
    terminal_code: str,
    coverage: str,
    legal_moves_: tuple[str, ...],
    current_claims: tuple[str, ...],
    children: list[dict[str, object]],
    selected_bindings: tuple[VerifiedCertificateBinding, ...],
) -> tuple[bytes, str]:
    if value == WDL.UNKNOWN:
        raise _CompositionError("an UNKNOWN value cannot be composed")

    if sum(binding.certificate_size for binding in selected_bindings) > MAX_CERTIFICATE_BYTES:
        raise _CompositionError("selected child certificates exceed the size cap")

    parsed = tuple(_parse_reachable_bundle(binding) for binding in selected_bindings)
    common_child_depth = max((item.root_depth for item in parsed), default=-1)
    merged: dict[str, dict[str, object]] = {}
    root_hash_by_node: dict[str, str] = {}
    for item in parsed:
        rebased_root, rebased_nodes = _rebase_bundle(item, common_child_depth)
        root_hash_by_node[item.binding.node_sha256] = rebased_root
        for certificate_hash, record in rebased_nodes.items():
            existing = merged.get(certificate_hash)
            if existing is not None and existing != record:
                raise _CompositionError("merged certificate has a SHA-256 collision")
            merged[certificate_hash] = record

    rewritten_children: list[dict[str, object]] = []
    for original in children:
        child = dict(original)
        child_node_sha256 = child.pop("_child_node_sha256", None)
        if child_node_sha256 is not None:
            if not isinstance(child_node_sha256, str):
                raise _CompositionError("internal child node identity is malformed")
            rebased_root = root_hash_by_node.get(child_node_sha256)
            if rebased_root is None:
                raise _CompositionError("selected child bundle root is missing")
            child["child_certificate_hash"] = rebased_root
        rewritten_children.append(child)

    parent_depth = 0 if not parsed else common_child_depth + 1
    parent: dict[str, object] = {
        "schema": NODE_SCHEMA,
        "state_hash": game_state_sha256(node.position, node.history),
        "fen": node.fen,
        "history_counts": node.history.record(),
        "depth_remaining": parent_depth,
        "value": value.value,
        "terminal_code": terminal_code,
        "current_claim_actions": list(current_claims),
        "legal_move_count": len(legal_moves_),
        "coverage": coverage,
        "children": rewritten_children,
        "exact": True,
    }
    parent_hash = _certificate_hash(parent)
    parent["certificate_hash"] = parent_hash
    existing_parent = merged.get(parent_hash)
    if existing_parent is not None and existing_parent != parent:
        raise _CompositionError("parent certificate collides with a child certificate")
    merged[parent_hash] = parent

    bundle: dict[str, object] = {
        "schema": BUNDLE_SCHEMA,
        "rules_profile": RULE_PROFILE_ID,
        "root_certificate_hash": parent_hash,
        "root_state_hash": node.game_state_sha256,
        "root_value": value.value,
        "root_exact": True,
        "max_plies": parent_depth,
        "nodes": [merged[key] for key in sorted(merged)],
    }
    certificate_bytes = canonical_json_bytes(bundle)
    if len(certificate_bytes) > MAX_CERTIFICATE_BYTES:
        raise _CompositionError(
            f"composed certificate is {len(certificate_bytes)} bytes; maximum is "
            f"{MAX_CERTIFICATE_BYTES}"
        )
    try:
        verification = verify_wdl_certificate(bundle, allow_unknown_root=False)
    except (TypeError, ValueError) as exc:
        raise _CompositionError(
            f"independent verification rejected composed proof: {exc}"
        ) from exc
    if (
        verification.get("valid") is not True
        or verification.get("root_exact") is not True
        or verification.get("root_value") != value.value
        or verification.get("root_certificate_hash") != parent_hash
        or verification.get("unreferenced_nodes") != 0
    ):
        raise _CompositionError("independent verification rejected composed proof")
    return certificate_bytes, parent_hash


def propagate_wdl_one_hop(
    dag: ProofDAG,
    overlay: VerifiedCertificateOverlay,
    node_sha256: str,
) -> WDLPropagationResult:
    """Attempt one exact WDL promotion without modifying the base DAG.

    Missing frontier moves, absent child certificates, and ambiguous duplicate
    occurrences return a structured UNKNOWN result.  Integrity failures in the
    DAG or overlay still raise: treating corruption as an ordinary open proof
    obligation would hide a materially different failure mode.
    """

    if not isinstance(dag, ProofDAG) or dag.closed:
        raise TypeError("dag must be an open ProofDAG")
    if not isinstance(overlay, VerifiedCertificateOverlay) or overlay.closed:
        raise TypeError("overlay must be an open VerifiedCertificateOverlay")
    if overlay.dag is not dag:
        raise ValueError("overlay is not bound to the supplied ProofDAG")
    node = dag.get_node(node_sha256)
    if node is None:
        raise ValueError("unknown DAG node")
    if node.rule_profile_id != RULE_PROFILE_ID or node.wdl != WDL.UNKNOWN:
        raise WDLPropagationError("target DAG node is not canonical UNKNOWN")
    validate_history_reachability(node.position, node.history)

    # Exactly one global replay supplies the immutable fact snapshot used for
    # all child decisions.  append_verified_certificate performs its own
    # mandatory replay immediately before committing the newly composed fact.
    binding_snapshot = tuple(overlay.iter_bindings())
    bindings: dict[str, VerifiedCertificateBinding] = {}
    for binding in binding_snapshot:
        if binding.node_sha256 in bindings:
            raise WDLPropagationError("audited overlay contains duplicate node bindings")
        bindings[binding.node_sha256] = binding
    existing = bindings.get(node.node_sha256)
    if existing is not None:
        return WDLPropagationResult(
            node_sha256=node.node_sha256,
            value=existing.claimed_wdl,
            status="already_verified",
            reason="target_already_verified",
            detail="the audited overlay already binds this exact DAG node",
            promoted=False,
            certificate_sha256=existing.certificate_sha256,
            root_certificate_hash=existing.root_certificate_hash,
        )

    moves = sorted(legal_moves(node.position), key=lambda move: move.uci())
    legal_uci = tuple(move.uci() for move in moves)
    legal_by_uci = {move.uci(): move for move in moves}
    automatic = automatic_status(node.position, node.history)
    claims = current_claim_actions(node.position, node.history)

    if automatic.terminal:
        value = WDL.LOSS if automatic.code == "checkmate" else WDL.DRAW
        try:
            certificate_bytes, root_hash = _compose_bundle(
                node=node,
                value=value,
                terminal_code=automatic.code,
                coverage="terminal",
                legal_moves_=(),
                current_claims=claims,
                children=[],
                selected_bindings=(),
            )
        except _CompositionError as exc:
            return _unknown(
                node.node_sha256,
                reason=_composition_reason(exc),
                detail=str(exc),
                legal_moves_=(),
            )
        appended = overlay.append_verified_certificate(
            node.node_sha256,
            certificate_bytes,
        )
        return WDLPropagationResult(
            node_sha256=node.node_sha256,
            value=value,
            status="promoted" if appended.appended else "already_verified",
            reason="terminal_promoted" if appended.appended else "target_already_verified",
            detail=f"automatic terminal status {automatic.code!r} is exact",
            promoted=appended.appended,
            certificate_sha256=hashlib.sha256(certificate_bytes).hexdigest(),
            root_certificate_hash=root_hash,
        )

    candidates: dict[str, dict[str, DAGNode]] = {}
    invalid_moves: set[str] = set()
    unexpected_actions = False
    node_cache: dict[str, DAGNode] = {}
    for edge in dag.outgoing_edges(node.node_sha256):
        action = edge.action
        if (
            not isinstance(action, dict)
            or set(action) != {"kind", "uci"}
            or action.get("kind") != "move"
            or not isinstance(action.get("uci"), str)
        ):
            unexpected_actions = True
            continue
        uci = action["uci"]
        move = legal_by_uci.get(uci)
        if move is None:
            invalid_moves.add(uci)
            continue
        expected_position = apply_move(node.position, move)
        expected_history = node.history.push(expected_position)
        expected_sha256 = node_identity_sha256(
            expected_position,
            expected_history,
            rule_profile_id=node.rule_profile_id,
        )
        child = node_cache.get(edge.child_node_sha256)
        if child is None:
            child = dag.get_node(edge.child_node_sha256)
            if child is None:
                invalid_moves.add(uci)
                continue
            node_cache[child.node_sha256] = child
        if (
            edge.parent_node_sha256 != node.node_sha256
            or child.node_sha256 != expected_sha256
            or child.fen != expected_position.to_fen()
            or child.position != expected_position
            or child.history != expected_history
            or child.rule_profile_id != node.rule_profile_id
            or child.game_state_sha256
            != game_state_sha256(expected_position, expected_history)
        ):
            invalid_moves.add(uci)
            continue
        candidates.setdefault(uci, {})[child.node_sha256] = child

    ambiguous = {
        uci for uci, children_by_sha in candidates.items() if len(children_by_sha) != 1
    }
    ambiguous.update(invalid_moves)
    if unexpected_actions:
        return _unknown(
            node.node_sha256,
            reason="ambiguous_frontier",
            detail="an outgoing occurrence is not one canonical legal-move action",
            legal_moves_=legal_uci,
            ambiguous_moves=tuple(sorted(ambiguous)),
        )
    if ambiguous:
        return _unknown(
            node.node_sha256,
            reason="ambiguous_frontier",
            detail="one or more UCI actions do not identify one exact replayed child",
            legal_moves_=legal_uci,
            ambiguous_moves=tuple(sorted(ambiguous)),
        )

    child_by_move = {
        uci: next(iter(children_by_sha.values()))
        for uci, children_by_sha in candidates.items()
    }
    binding_by_move = {
        uci: bindings.get(child.node_sha256) for uci, child in child_by_move.items()
    }

    # A single exact LOSS for the child side-to-move proves a parent WIN.  No
    # claim or unrelated move record is included in the witness certificate.
    winning_moves = tuple(
        uci
        for uci in legal_uci
        if binding_by_move.get(uci) is not None
        and binding_by_move[uci].claimed_wdl == WDL.LOSS  # type: ignore[union-attr]
    )
    if winning_moves:
        uci = winning_moves[0]
        move = legal_by_uci[uci]
        child = child_by_move[uci]
        binding = binding_by_move[uci]
        assert binding is not None
        child_record = _move_record(
            uci=uci,
            san=move_to_san(node.position, move),
            child=child,
            binding=binding,
            child_certificate_hash=binding.root_certificate_hash,
        )
        child_record["_child_node_sha256"] = child.node_sha256
        try:
            certificate_bytes, root_hash = _compose_bundle(
                node=node,
                value=WDL.WIN,
                terminal_code="winning_move_witness",
                coverage="witness",
                legal_moves_=legal_uci,
                current_claims=claims,
                children=[child_record],
                selected_bindings=(binding,),
            )
        except _CompositionError as exc:
            return _unknown(
                node.node_sha256,
                reason=_composition_reason(exc),
                detail=str(exc),
                legal_moves_=legal_uci,
            )
        appended = overlay.append_verified_certificate(
            node.node_sha256,
            certificate_bytes,
        )
        return WDLPropagationResult(
            node_sha256=node.node_sha256,
            value=WDL.WIN,
            status="promoted" if appended.appended else "already_verified",
            reason="winning_child_loss" if appended.appended else "target_already_verified",
            detail=f"{uci} reaches an exact LOSS for the child side-to-move",
            promoted=appended.appended,
            witness_move=uci,
            legal_moves=legal_uci,
            used_moves=(uci,),
            certificate_sha256=hashlib.sha256(certificate_bytes).hexdigest(),
            root_certificate_hash=root_hash,
        )

    missing_frontier = tuple(uci for uci in legal_uci if uci not in child_by_move)
    if missing_frontier:
        return _unknown(
            node.node_sha256,
            reason="missing_frontier_moves",
            detail="complete LOSS/DRAW propagation requires every canonical legal UCI action",
            legal_moves_=legal_uci,
            missing_frontier_moves=missing_frontier,
        )
    missing_certificates = tuple(
        uci for uci in legal_uci if binding_by_move.get(uci) is None
    )
    if missing_certificates:
        return _unknown(
            node.node_sha256,
            reason="missing_verified_children",
            detail="complete LOSS/DRAW propagation requires one audited fact per legal move",
            legal_moves_=legal_uci,
            missing_certificate_moves=missing_certificates,
        )

    exact_bindings = {
        uci: binding_by_move[uci] for uci in legal_uci
    }
    if any(binding is None for binding in exact_bindings.values()):
        raise WDLPropagationError("complete child-binding map unexpectedly contains None")
    converted = {
        uci: invert_child(exact_bindings[uci].claimed_wdl)  # type: ignore[union-attr]
        for uci in legal_uci
    }

    children: list[dict[str, object]] = [_claim_record(code) for code in claims]
    has_draw_action = bool(claims)
    for uci in legal_uci:
        move = legal_by_uci[uci]
        child = child_by_move[uci]
        child_history = node.history.push(child.position)
        san = move_to_san(node.position, move)
        for code in intended_move_claims(child.position, child_history):
            children.append(_claim_record(code, move=uci, san=san))
            has_draw_action = True
        binding = exact_bindings[uci]
        assert binding is not None
        record = _move_record(
            uci=uci,
            san=san,
            child=child,
            binding=binding,
            child_certificate_hash=binding.root_certificate_hash,
        )
        record["_child_node_sha256"] = child.node_sha256
        children.append(record)

    values = tuple(converted[uci] for uci in legal_uci)
    if values and all(value == WDL.LOSS for value in values) and not has_draw_action:
        value = WDL.LOSS
        reason = "complete_all_moves_lose"
        terminal_code = "all_legal_moves_lose"
    elif values and not any(value == WDL.WIN for value in values) and (
        has_draw_action or any(value == WDL.DRAW for value in values)
    ):
        value = WDL.DRAW
        reason = "complete_draw"
        terminal_code = "draw_action_and_no_winning_move"
    else:
        return _unknown(
            node.node_sha256,
            reason="no_exact_parent_value",
            detail="complete child facts do not satisfy an exact WDL aggregation rule",
            legal_moves_=legal_uci,
        )

    selected_by_node: dict[str, VerifiedCertificateBinding] = {}
    for uci in legal_uci:
        binding = exact_bindings[uci]
        assert binding is not None
        selected_by_node.setdefault(binding.node_sha256, binding)
    selected = tuple(selected_by_node[key] for key in sorted(selected_by_node))
    try:
        certificate_bytes, root_hash = _compose_bundle(
            node=node,
            value=value,
            terminal_code=terminal_code,
            coverage="complete",
            legal_moves_=legal_uci,
            current_claims=claims,
            children=children,
            selected_bindings=selected,
        )
    except _CompositionError as exc:
        return _unknown(
            node.node_sha256,
            reason=_composition_reason(exc),
            detail=str(exc),
            legal_moves_=legal_uci,
        )

    appended = overlay.append_verified_certificate(node.node_sha256, certificate_bytes)
    return WDLPropagationResult(
        node_sha256=node.node_sha256,
        value=value,
        status="promoted" if appended.appended else "already_verified",
        reason=reason if appended.appended else "target_already_verified",
        detail="all canonical legal actions and required draw claims were closed exactly",
        promoted=appended.appended,
        legal_moves=legal_uci,
        used_moves=legal_uci,
        certificate_sha256=hashlib.sha256(certificate_bytes).hexdigest(),
        root_certificate_hash=root_hash,
    )


__all__ = [
    "PROPAGATION_RESULT_SCHEMA",
    "WDLPropagationError",
    "WDLPropagationResult",
    "propagate_wdl_one_hop",
]
