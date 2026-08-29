"""Compact one-hop WDL propagation into the unified v2 fact journal.

Unlike :mod:`ugts_chess.wdl_propagation`, this module never copies a child
certificate graph into its parent.  Each move dependency names one already
audited v2 fact by its exact earlier record index and full record-content
SHA-256.  The journal verifier independently reconstructs every referenced
DAG edge, legal action, draw claim, WDL inversion, and aggregation rule before
the derived fact is made visible.
"""
from __future__ import annotations

from dataclasses import dataclass
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
from .proof_dag import DAGEdge, DAGNode, ProofDAG, node_identity_sha256
from .rules import apply_move, legal_moves
from .wdl import invert_child
from .wdl_fact_journal import (
    FactEntry,
    WDLFactJournal,
    canonical_derivation_evidence_bytes,
)


FACT_PROPAGATION_RESULT_SCHEMA = (
    "ugts-chess-compact-wdl-one-hop-propagation-result-1.0"
)


@dataclass(frozen=True, slots=True)
class FactPropagationResult:
    """Structured outcome of one compact propagation attempt."""

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
    missing_fact_moves: tuple[str, ...] = ()
    ambiguous_moves: tuple[str, ...] = ()
    fact_record_index: int | None = None
    fact_content_sha256: str | None = None
    evidence_sha256: str | None = None
    proof_height: int | None = None

    @property
    def exact(self) -> bool:
        return self.value != WDL.UNKNOWN

    def record(self) -> dict[str, object]:
        return {
            "schema": FACT_PROPAGATION_RESULT_SCHEMA,
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
            "missing_fact_moves": list(self.missing_fact_moves),
            "ambiguous_moves": list(self.ambiguous_moves),
            "fact_record_index": self.fact_record_index,
            "fact_content_sha256": self.fact_content_sha256,
            "evidence_sha256": self.evidence_sha256,
            "proof_height": self.proof_height,
        }


class FactPropagationError(Exception):
    """Raised when an audited authority violates an internal invariant."""


@dataclass(frozen=True, slots=True)
class _ResolvedMove:
    child: DAGNode
    edge: DAGEdge


def _unknown(
    node_sha256: str,
    *,
    reason: str,
    detail: str,
    legal_moves_: tuple[str, ...],
    missing_frontier_moves: tuple[str, ...] = (),
    missing_fact_moves: tuple[str, ...] = (),
    ambiguous_moves: tuple[str, ...] = (),
) -> FactPropagationResult:
    return FactPropagationResult(
        node_sha256=node_sha256,
        value=WDL.UNKNOWN,
        status="unknown",
        reason=reason,
        detail=detail,
        promoted=False,
        legal_moves=legal_moves_,
        missing_frontier_moves=missing_frontier_moves,
        missing_fact_moves=missing_fact_moves,
        ambiguous_moves=ambiguous_moves,
    )


def _result_from_entry(
    entry: FactEntry,
    *,
    appended: bool,
    reason: str,
    detail: str,
    witness_move: str | None = None,
    legal_moves_: tuple[str, ...] = (),
    used_moves: tuple[str, ...] = (),
) -> FactPropagationResult:
    fact = entry.fact
    return FactPropagationResult(
        node_sha256=fact.node_sha256,
        value=fact.claimed_wdl,
        status="promoted" if appended else "already_verified",
        reason=reason if appended else "target_already_verified",
        detail=detail,
        promoted=appended,
        witness_move=witness_move,
        legal_moves=legal_moves_,
        used_moves=used_moves,
        fact_record_index=entry.record_index,
        fact_content_sha256=entry.content_sha256,
        evidence_sha256=fact.evidence_sha256,
        proof_height=fact.proof_height,
    )


def _dependency(
    uci: str,
    resolved: _ResolvedMove,
    fact_entry: FactEntry,
) -> dict[str, object]:
    fact = fact_entry.fact
    return {
        "uci": uci,
        "dag_edge_record_index": resolved.edge.frontier_record_index,
        "dag_edge_content_sha256": resolved.edge.frontier_content_sha256,
        "child_node_sha256": resolved.child.node_sha256,
        "fact_record_index": fact_entry.record_index,
        "fact_content_sha256": fact_entry.content_sha256,
        "child_wdl": fact.claimed_wdl.value,
        "child_proof_height": fact.proof_height,
    }


def _resolve_moves(
    dag: ProofDAG,
    node: DAGNode,
    legal_by_uci: Mapping[str, object],
) -> tuple[dict[str, _ResolvedMove], tuple[str, ...], bool]:
    """Replay all outgoing occurrences and choose each earliest exact edge."""

    candidates: dict[str, dict[str, list[tuple[DAGEdge, DAGNode]]]] = {}
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
        expected_position = apply_move(node.position, move)  # type: ignore[arg-type]
        expected_history = node.history.push(expected_position)
        expected_node_sha256 = node_identity_sha256(
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
            or child.node_sha256 != expected_node_sha256
            or child.fen != expected_position.to_fen()
            or child.position != expected_position
            or child.history != expected_history
            or child.rule_profile_id != node.rule_profile_id
            or child.game_state_sha256
            != game_state_sha256(expected_position, expected_history)
        ):
            invalid_moves.add(uci)
            continue
        candidates.setdefault(uci, {}).setdefault(child.node_sha256, []).append(
            (edge, child)
        )

    ambiguous = {
        uci for uci, children_by_sha in candidates.items() if len(children_by_sha) != 1
    }
    ambiguous.update(invalid_moves)
    resolved: dict[str, _ResolvedMove] = {}
    for uci, children_by_sha in candidates.items():
        if uci in ambiguous:
            continue
        occurrences = next(iter(children_by_sha.values()))
        edge, child = min(
            occurrences,
            key=lambda item: (
                item[0].frontier_record_index,
                item[0].frontier_content_sha256,
            ),
        )
        resolved[uci] = _ResolvedMove(child, edge)
    return resolved, tuple(sorted(ambiguous)), unexpected_actions


def propagate_wdl_fact_one_hop(
    dag: ProofDAG,
    journal: WDLFactJournal,
    node_sha256: str,
) -> FactPropagationResult:
    """Attempt one exact compact promotion without mutating the proof DAG.

    Ordinary incompleteness returns ``UNKNOWN``.  Corrupt DAG/journal state and
    durable-append failures still raise, because silently treating corruption
    as an open proof obligation would be unsound.
    """

    if not isinstance(dag, ProofDAG) or dag.closed:
        raise TypeError("dag must be an open ProofDAG")
    if not isinstance(journal, WDLFactJournal) or journal.closed:
        raise TypeError("journal must be an open WDLFactJournal")
    if journal.dag is not dag:
        raise ValueError("fact journal is not bound to the supplied ProofDAG")

    node = dag.get_node(node_sha256)
    if node is None:
        raise ValueError("unknown DAG node")
    if node.rule_profile_id != RULE_PROFILE_ID or node.wdl != WDL.UNKNOWN:
        raise FactPropagationError("target DAG node is not canonical UNKNOWN")
    validate_history_reachability(node.position, node.history)

    entries = tuple(journal.iter_entries())
    by_node: dict[str, FactEntry] = {}
    for entry in entries:
        if entry.fact.node_sha256 in by_node:
            raise FactPropagationError("audited fact journal contains duplicate nodes")
        by_node[entry.fact.node_sha256] = entry
    existing = by_node.get(node.node_sha256)
    if existing is not None:
        return _result_from_entry(
            existing,
            appended=False,
            reason="target_already_verified",
            detail="the audited v2 journal already binds this exact DAG node",
        )

    moves = sorted(legal_moves(node.position), key=lambda move: move.uci())
    legal_uci = tuple(move.uci() for move in moves)
    legal_by_uci = {move.uci(): move for move in moves}
    automatic = automatic_status(node.position, node.history)
    claims = current_claim_actions(node.position, node.history)

    if automatic.terminal:
        value = WDL.LOSS if automatic.code == "checkmate" else WDL.DRAW
        evidence = canonical_derivation_evidence_bytes(
            root_value=value,
            proof_height=0,
            derivation_code=automatic.code,
            move_dependencies=(),
        )
        appended = journal.append_derivation(node.node_sha256, evidence)
        return _result_from_entry(
            appended.entry,
            appended=appended.appended,
            reason="terminal_promoted",
            detail=f"automatic terminal status {automatic.code!r} is exact",
        )

    resolved, ambiguous, unexpected_actions = _resolve_moves(
        dag,
        node,
        legal_by_uci,
    )
    if unexpected_actions:
        return _unknown(
            node.node_sha256,
            reason="ambiguous_frontier",
            detail="an outgoing occurrence is not one canonical legal-move action",
            legal_moves_=legal_uci,
            ambiguous_moves=ambiguous,
        )
    if ambiguous:
        return _unknown(
            node.node_sha256,
            reason="ambiguous_frontier",
            detail="one or more UCI actions do not identify one exact replayed child",
            legal_moves_=legal_uci,
            ambiguous_moves=ambiguous,
        )

    fact_by_move = {
        uci: by_node.get(item.child.node_sha256) for uci, item in resolved.items()
    }
    winning_moves = tuple(
        uci
        for uci in legal_uci
        if fact_by_move.get(uci) is not None
        and fact_by_move[uci].fact.claimed_wdl == WDL.LOSS  # type: ignore[union-attr]
    )
    if winning_moves:
        witness = winning_moves[0]
        child_fact = fact_by_move[witness]
        assert child_fact is not None
        dependency = _dependency(witness, resolved[witness], child_fact)
        proof_height = child_fact.fact.proof_height + 1
        evidence = canonical_derivation_evidence_bytes(
            root_value=WDL.WIN,
            proof_height=proof_height,
            derivation_code="winning_move_witness",
            move_dependencies=(dependency,),
        )
        appended = journal.append_derivation(node.node_sha256, evidence)
        return _result_from_entry(
            appended.entry,
            appended=appended.appended,
            reason="winning_child_loss",
            detail=f"{witness} reaches an exact LOSS for the child side-to-move",
            witness_move=witness,
            legal_moves_=legal_uci,
            used_moves=(witness,),
        )

    missing_frontier = tuple(uci for uci in legal_uci if uci not in resolved)
    if missing_frontier:
        return _unknown(
            node.node_sha256,
            reason="missing_frontier_moves",
            detail="complete LOSS/DRAW propagation requires every canonical legal UCI action",
            legal_moves_=legal_uci,
            missing_frontier_moves=missing_frontier,
        )
    missing_facts = tuple(uci for uci in legal_uci if fact_by_move.get(uci) is None)
    if missing_facts:
        return _unknown(
            node.node_sha256,
            reason="missing_verified_children",
            detail="complete LOSS/DRAW propagation requires one audited fact per legal move",
            legal_moves_=legal_uci,
            missing_fact_moves=missing_facts,
        )

    exact_entries: dict[str, FactEntry] = {}
    for uci in legal_uci:
        entry = fact_by_move[uci]
        if entry is None:
            raise FactPropagationError("complete child-fact map unexpectedly contains None")
        exact_entries[uci] = entry
    values = {
        uci: invert_child(exact_entries[uci].fact.claimed_wdl) for uci in legal_uci
    }
    has_draw_action = bool(claims)
    for uci in legal_uci:
        child = resolved[uci].child
        if intended_move_claims(child.position, node.history.push(child.position)):
            has_draw_action = True
    has_draw_action = has_draw_action or any(
        value == WDL.DRAW for value in values.values()
    )

    converted = tuple(values[uci] for uci in legal_uci)
    if converted and all(value == WDL.LOSS for value in converted) and not has_draw_action:
        value = WDL.LOSS
        reason = "complete_all_moves_lose"
        code = "all_legal_moves_lose"
    elif converted and not any(value == WDL.WIN for value in converted) and has_draw_action:
        value = WDL.DRAW
        reason = "complete_draw"
        code = "draw_action_and_no_winning_move"
    else:
        return _unknown(
            node.node_sha256,
            reason="no_exact_parent_value",
            detail="complete child facts do not satisfy an exact WDL aggregation rule",
            legal_moves_=legal_uci,
        )

    dependencies = tuple(
        _dependency(uci, resolved[uci], exact_entries[uci]) for uci in legal_uci
    )
    proof_height = 1 + max(entry.fact.proof_height for entry in exact_entries.values())
    evidence = canonical_derivation_evidence_bytes(
        root_value=value,
        proof_height=proof_height,
        derivation_code=code,
        move_dependencies=dependencies,
    )
    appended = journal.append_derivation(node.node_sha256, evidence)
    return _result_from_entry(
        appended.entry,
        appended=appended.appended,
        reason=reason,
        detail="all canonical legal actions and required draw claims were closed exactly",
        legal_moves_=legal_uci,
        used_moves=legal_uci,
    )


__all__ = [
    "FACT_PROPAGATION_RESULT_SCHEMA",
    "FactPropagationError",
    "FactPropagationResult",
    "propagate_wdl_fact_one_hop",
]
