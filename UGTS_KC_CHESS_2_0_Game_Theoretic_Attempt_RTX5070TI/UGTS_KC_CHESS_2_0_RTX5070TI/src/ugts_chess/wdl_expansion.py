"""Bounded deterministic materialisation of exact ProofDAG move edges.

This module grows only the append-only UNKNOWN-state DAG.  It does not assign
WDL values and it never treats local move-edge completeness as a solution of
chess.  One full audited materialisation snapshot seeds an exact in-memory
parent map and heap.  Each verified batch updates that state and its chainable
ordered manifest; one final full replay must match exactly before a report is
returned.

Completeness is defined for an exact ``(parent node, UCI)`` pair, not for one
particular incoming frontier occurrence.  Equivalent duplicate occurrences
therefore do not create more work.  A newly materialised edge is anchored to
the parent's earliest authoritative occurrence, giving interrupted and
uninterrupted runs identical frontier bytes for the same edge sequence.

Limits are cooperative.  Full authority audits and one durable move batch are
indivisible, so a wall-clock limit can be exceeded by either.
Unexpected authority movement is rejected after a fresh audit.  Any durable
edge committed before that rejection remains valid and a new invocation can
resume from it without duplication.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import heapq
import math
import time
from typing import Iterable

from .game_state import HistoryContext, RULE_PROFILE_ID, automatic_status
from .move import Move
from .position import Position
from .proof_dag import (
    DAGEdge,
    DAGMoveAppendRequest,
    DAGNode,
    ProofDAG,
    ProofDAGIntegrityError,
    node_identity_sha256,
)
from .proof_dag_commitment import (
    PROOF_DAG_HEAD_SCHEMA,
    PROOF_DAG_MANIFEST_SCHEMA,
    ProofDAGHead,
    advance_proof_dag_manifest,
    proof_dag_manifest_seed,
)
from .rules import apply_move, legal_moves
from .wdl_fact_journal import FactJournalHead, WDLFactJournal


EXPANSION_SCHEMA = "ugts-chess-deterministic-dag-expansion-1.0"
EXPANSION_HEAD_SCHEMA = PROOF_DAG_HEAD_SCHEMA
EXPANSION_MANIFEST_SCHEMA = PROOF_DAG_MANIFEST_SCHEMA
_MAX_STABLE_SNAPSHOT_ATTEMPTS = 8


def _is_sha256_hex(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_count(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


class ExpansionConcurrentMutationError(RuntimeError):
    """Raised when the DAG moves outside the expansion driver's own append."""


class ExpansionStopReason(str, Enum):
    """Why a bounded expansion invocation returned."""

    LOCAL_ELIGIBLE_EDGE_CLOSURE_NOT_CHESS_SOLVED = (
        "local_eligible_edge_closure_not_chess_solved"
    )
    LOCAL_MATERIALIZED_EDGE_CLOSURE_NOT_CHESS_SOLVED = (
        "local_materialized_edge_closure_not_chess_solved"
    )
    PARENT_LIMIT = "parent_limit"
    EDGE_LIMIT = "edge_limit"
    TIME_LIMIT = "time_limit"


@dataclass(frozen=True, slots=True)
class ExpansionLimits:
    """Cooperative parent, edge, and elapsed-time bounds.

    The safe default expands one parent.  Callers must pass
    ``max_parents=None`` explicitly to request unbounded graph traversal.
    """

    max_parents: int | None = 1
    max_edges: int | None = None
    max_seconds: float | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("max_parents", self.max_parents),
            ("max_edges", self.max_edges),
        ):
            if value is not None:
                _require_count(value, label=label)
        if self.max_seconds is not None:
            value = self.max_seconds
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("max_seconds must be a finite non-negative number")
            try:
                normalized = float(value)
            except OverflowError as exc:
                raise ValueError(
                    "max_seconds must be a finite non-negative number"
                ) from exc
            if not math.isfinite(normalized) or normalized < 0:
                raise ValueError("max_seconds must be a finite non-negative number")
            object.__setattr__(self, "max_seconds", normalized)


ExpansionDAGHead = ProofDAGHead


@dataclass(frozen=True, slots=True)
class ParentExpansionResult:
    """Exact before/after coverage for one selected non-terminal parent."""

    node_sha256: str
    first_frontier_record_index: int
    parent_frontier_content_sha256: str
    legal_moves: tuple[str, ...]
    existing_moves_before: tuple[str, ...]
    duplicate_existing_occurrences: int
    appended_moves: tuple[str, ...]
    remaining_moves: tuple[str, ...]
    complete_before: bool
    complete_after: bool


@dataclass(frozen=True, slots=True)
class ExpansionReport:
    """Bounded expansion accounting anchored to exact audited DAG heads."""

    stop_reason: ExpansionStopReason
    parents_attempted: int
    parents_completed: int
    edges_appended: int
    elapsed_seconds: float
    parent_results: tuple[ParentExpansionResult, ...]
    incomplete_parent_node_sha256s: tuple[str, ...]
    eligible_incomplete_parent_node_sha256s: tuple[str, ...]
    verified_skipped_node_sha256s: tuple[str, ...]
    terminal_node_sha256s: tuple[str, ...]
    dag_head_before: ExpansionDAGHead
    dag_head_after: ExpansionDAGHead
    fact_head_before: FactJournalHead | None
    fact_head_after: FactJournalHead | None

    @property
    def local_materialized_edge_closure(self) -> bool:
        """Whether every materialised non-terminal has all move edges."""

        return self.all_materialized_nonterminal_parents_complete

    @property
    def eligible_materialized_edge_closure(self) -> bool:
        """Whether no unverified non-terminal is missing a legal move edge."""

        return self.eligible_edge_closure

    @property
    def eligible_edge_closure(self) -> bool:
        """Whether expansion-eligible move-edge work is locally closed."""

        return not self.eligible_incomplete_parent_node_sha256s

    @property
    def all_materialized_nonterminal_parents_complete(self) -> bool:
        """Move-edge completeness only; claim actions are represented elsewhere."""

        return not self.incomplete_parent_node_sha256s

    @property
    def materialized_dag_empty(self) -> bool:
        """True only when the final audited DAG contains no materialised node."""

        return self.dag_head_after.sqlite_node_count == 0

    @property
    def empty_dag(self) -> bool:
        """Short explicit alias for :attr:`materialized_dag_empty`."""

        return self.materialized_dag_empty

    @property
    def chess_solved(self) -> bool:
        """Always false: move materialisation is not a WDL proof."""

        return False


@dataclass(frozen=True, slots=True)
class _ParentState:
    node: DAGNode
    parent_frontier_content_sha256: str
    terminal_code: str | None
    legal_moves: tuple[str, ...]
    existing_moves: tuple[str, ...]
    missing_moves: tuple[str, ...]
    duplicate_existing_occurrences: int

    @property
    def complete(self) -> bool:
        return not self.missing_moves


@dataclass(frozen=True, slots=True)
class _MaterializationSnapshot:
    head: ExpansionDAGHead
    parents: tuple[_ParentState, ...]

    @property
    def incomplete(self) -> tuple[_ParentState, ...]:
        return tuple(
            parent
            for parent in self.parents
            if parent.terminal_code is None and not parent.complete
        )

    @property
    def terminals(self) -> tuple[_ParentState, ...]:
        return tuple(parent for parent in self.parents if parent.terminal_code is not None)


@dataclass(frozen=True, slots=True)
class _FactSnapshot:
    head: FactJournalHead
    verified_node_sha256s: frozenset[str]


def _move_uci(edge: DAGEdge) -> str:
    action = edge.action
    if (
        not isinstance(action, dict)
        or set(action) != {"kind", "uci"}
        or action.get("kind") != "move"
        or not isinstance(action.get("uci"), str)
    ):
        raise ProofDAGIntegrityError(
            "outgoing expansion edge does not carry one canonical move action"
        )
    return action["uci"]


def _derive_child_identity(
    node: DAGNode,
    move: Move,
) -> tuple[Position, HistoryContext, str]:
    child_position = apply_move(node.position, move)
    child_history = node.history.push(child_position)
    child_sha256 = node_identity_sha256(
        child_position,
        child_history,
        rule_profile_id=node.rule_profile_id,
    )
    return child_position, child_history, child_sha256


def _build_parent_states(
    nodes: Iterable[DAGNode],
    edges: Iterable[DAGEdge],
) -> tuple[_ParentState, ...]:
    node_by_sha256 = {node.node_sha256: node for node in nodes}
    incoming: dict[str, list[DAGEdge]] = {node_sha256: [] for node_sha256 in node_by_sha256}
    outgoing: dict[str, list[DAGEdge]] = {node_sha256: [] for node_sha256 in node_by_sha256}
    for edge in edges:
        if edge.child_node_sha256 not in incoming:
            raise ProofDAGIntegrityError("frontier occurrence names a missing child node")
        incoming[edge.child_node_sha256].append(edge)
        if edge.parent_node_sha256 is not None:
            if edge.parent_node_sha256 not in outgoing:
                raise ProofDAGIntegrityError("frontier occurrence names a missing parent node")
            outgoing[edge.parent_node_sha256].append(edge)

    states: list[_ParentState] = []
    for node in sorted(
        node_by_sha256.values(),
        key=lambda item: (item.first_frontier_record_index, item.node_sha256),
    ):
        occurrences = sorted(
            incoming[node.node_sha256],
            key=lambda edge: (edge.frontier_record_index, edge.frontier_content_sha256),
        )
        if not occurrences:
            raise ProofDAGIntegrityError("materialised DAG node has no frontier occurrence")
        first = occurrences[0]
        if first.frontier_record_index != node.first_frontier_record_index:
            raise ProofDAGIntegrityError(
                "node first frontier occurrence differs from ordered authority"
            )

        status = automatic_status(node.position, node.history)
        moves = tuple(sorted(legal_moves(node.position), key=lambda move: move.uci()))
        legal_uci = tuple(move.uci() for move in moves)
        if len(set(legal_uci)) != len(legal_uci):
            raise ProofDAGIntegrityError("legal-move oracle returned duplicate canonical UCI")
        if status.terminal:
            if outgoing[node.node_sha256]:
                raise ProofDAGIntegrityError("automatic terminal node has outgoing move edges")
            states.append(
                _ParentState(
                    node=node,
                    parent_frontier_content_sha256=first.frontier_content_sha256,
                    terminal_code=status.code,
                    legal_moves=(),
                    existing_moves=(),
                    missing_moves=(),
                    duplicate_existing_occurrences=0,
                )
            )
            continue

        expected_children: dict[str, str] = {}
        for move in moves:
            _, _, child_sha256 = _derive_child_identity(node, move)
            expected_children[move.uci()] = child_sha256

        occurrence_counts: dict[str, int] = {}
        for edge in sorted(
            outgoing[node.node_sha256],
            key=lambda item: (item.frontier_record_index, item.frontier_content_sha256),
        ):
            uci = _move_uci(edge)
            expected_child = expected_children.get(uci)
            if expected_child is None:
                raise ProofDAGIntegrityError(
                    "outgoing edge action is not legal in its exact parent state"
                )
            if edge.child_node_sha256 != expected_child:
                raise ProofDAGIntegrityError(
                    "outgoing edge child differs from exact position/history transition"
                )
            occurrence_counts[uci] = occurrence_counts.get(uci, 0) + 1

        existing = tuple(uci for uci in legal_uci if uci in occurrence_counts)
        missing = tuple(uci for uci in legal_uci if uci not in occurrence_counts)
        duplicates = sum(count - 1 for count in occurrence_counts.values())
        states.append(
            _ParentState(
                node=node,
                parent_frontier_content_sha256=first.frontier_content_sha256,
                terminal_code=None,
                legal_moves=legal_uci,
                existing_moves=existing,
                missing_moves=missing,
                duplicate_existing_occurrences=duplicates,
            )
        )
    return tuple(states)


def _materialization_snapshot(dag: ProofDAG) -> _MaterializationSnapshot:
    """Perform one stable full DAG audit/materialisation operation.

    One edge scan supplies both the ordered manifest and parent coverage.  The
    complete audits before and after that scan reject a growing or otherwise
    unstable live boundary.  ProofDAG's retained writer/index locks exclude a
    coordinated external rewrite of an equal-size prefix.
    """

    for _ in range(_MAX_STABLE_SNAPSHOT_ATTEMPTS):
        before = dag.audit().require_valid()
        nodes = tuple(dag.iter_nodes())
        edges = tuple(dag.iter_edges())
        after = dag.audit().require_valid()
        if before != after:
            continue
        if (
            len(nodes) != after.sqlite_node_count
            or len(edges) != after.sqlite_edge_count
            or len(edges) != after.frontier_record_count
        ):
            continue

        manifest = proof_dag_manifest_seed()
        last_sha256: str | None = None
        last_end = 0
        for ordinal, edge in enumerate(edges):
            if edge.frontier_record_index != ordinal:
                raise ProofDAGIntegrityError(
                    "frontier edge ordinals are not contiguous from zero"
                )
            manifest = advance_proof_dag_manifest(manifest, edge)
            last_sha256 = edge.frontier_content_sha256
            last_end = edge.frame_end_offset
        if edges and last_end != after.frontier_size:
            raise ProofDAGIntegrityError(
                "last frontier edge does not end at the audited DAG boundary"
            )
        head = ExpansionDAGHead(
            rule_profile_id=dag.rule_profile_id,
            frontier_record_count=after.frontier_record_count,
            sqlite_edge_count=after.sqlite_edge_count,
            sqlite_node_count=after.sqlite_node_count,
            frontier_size=after.frontier_size,
            last_frontier_content_sha256=last_sha256,
            frontier_manifest_sha256=manifest.hex(),
        )
        return _MaterializationSnapshot(
            head=head,
            parents=_build_parent_states(nodes, edges),
        )
    raise ExpansionConcurrentMutationError(
        "proof DAG changed repeatedly while reconstructing expansion coverage"
    )


def _fact_snapshot(journal: WDLFactJournal) -> _FactSnapshot:
    """Capture one complete validated fact prefix from the retained handle."""

    report = journal.audit().require_valid()
    entries = tuple(report.entries)
    if len(entries) != report.record_count:
        raise ExpansionConcurrentMutationError(
            "fact journal replay count differs from its audited boundary"
        )
    verified = frozenset(entry.fact.node_sha256 for entry in entries)
    if len(verified) != len(entries):
        raise ExpansionConcurrentMutationError(
            "fact journal replay contains duplicate exact node facts"
        )
    return _FactSnapshot(
        head=FactJournalHead(
            rule_profile_id=RULE_PROFILE_ID,
            record_count=report.record_count,
            head_content_sha256=(
                None if not entries else entries[-1].content_sha256
            ),
            file_size=report.file_size,
        ),
        verified_node_sha256s=verified,
    )


def _new_parent_state(node: DAGNode, first_edge: DAGEdge) -> _ParentState:
    """Build exact zero-outgoing-edge state for a newly materialised node."""

    if first_edge.child_node_sha256 != node.node_sha256:
        raise ProofDAGIntegrityError("new node occurrence names a different child")
    if first_edge.frontier_record_index != node.first_frontier_record_index:
        raise ProofDAGIntegrityError("new node first occurrence index is inconsistent")
    status = automatic_status(node.position, node.history)
    if status.terminal:
        return _ParentState(
            node=node,
            parent_frontier_content_sha256=first_edge.frontier_content_sha256,
            terminal_code=status.code,
            legal_moves=(),
            existing_moves=(),
            missing_moves=(),
            duplicate_existing_occurrences=0,
        )
    legal_uci = tuple(
        move.uci() for move in sorted(legal_moves(node.position), key=lambda item: item.uci())
    )
    if len(set(legal_uci)) != len(legal_uci):
        raise ProofDAGIntegrityError(
            "legal-move oracle returned noncanonical or duplicate UCI order"
        )
    return _ParentState(
        node=node,
        parent_frontier_content_sha256=first_edge.frontier_content_sha256,
        terminal_code=None,
        legal_moves=legal_uci,
        existing_moves=(),
        missing_moves=legal_uci,
        duplicate_existing_occurrences=0,
    )


def _state_priority(state: _ParentState) -> tuple[int, str]:
    return state.node.first_frontier_record_index, state.node.node_sha256


def _eligible(state: _ParentState, verified: frozenset[str]) -> bool:
    return (
        state.terminal_code is None
        and not state.complete
        and state.node.node_sha256 not in verified
    )


def _lineage(node_sha256: str, uci: str) -> dict[str, str]:
    return {
        "kind": "deterministic_wdl_expansion",
        "schema": EXPANSION_SCHEMA,
        "parent_node_sha256": node_sha256,
        "uci": uci,
    }


def _result_for_parent(
    before: _ParentState,
    after: _ParentState,
    appended_moves: tuple[str, ...],
) -> ParentExpansionResult:
    if before.node.node_sha256 != after.node.node_sha256:
        raise ProofDAGIntegrityError("parent identity changed during expansion")
    return ParentExpansionResult(
        node_sha256=before.node.node_sha256,
        first_frontier_record_index=before.node.first_frontier_record_index,
        parent_frontier_content_sha256=before.parent_frontier_content_sha256,
        legal_moves=before.legal_moves,
        existing_moves_before=before.existing_moves,
        duplicate_existing_occurrences=before.duplicate_existing_occurrences,
        appended_moves=appended_moves,
        remaining_moves=after.missing_moves,
        complete_before=before.complete,
        complete_after=after.complete,
    )


def _make_report(
    *,
    final: _MaterializationSnapshot,
    expected_head: ExpansionDAGHead,
    initial_head: ExpansionDAGHead,
    verified_node_sha256s: frozenset[str],
    fact_head_before: FactJournalHead | None,
    fact_head_after: FactJournalHead | None,
    stop_reason: ExpansionStopReason,
    started: float,
    parents_attempted: int,
    parents_completed: int,
    edges_appended: int,
    parent_results: list[ParentExpansionResult],
) -> ExpansionReport:
    if final.head != expected_head:
        raise ExpansionConcurrentMutationError(
            "proof DAG authority moved before expansion reporting completed"
        )
    incomplete = tuple(parent.node.node_sha256 for parent in final.incomplete)
    eligible_incomplete = tuple(
        node_sha256
        for node_sha256 in incomplete
        if node_sha256 not in verified_node_sha256s
    )
    verified_skipped = tuple(
        node_sha256
        for node_sha256 in incomplete
        if node_sha256 in verified_node_sha256s
    )
    terminals = tuple(parent.node.node_sha256 for parent in final.terminals)
    reached_eligible_closure = stop_reason in {
        ExpansionStopReason.LOCAL_ELIGIBLE_EDGE_CLOSURE_NOT_CHESS_SOLVED,
        ExpansionStopReason.LOCAL_MATERIALIZED_EDGE_CLOSURE_NOT_CHESS_SOLVED,
    }
    if reached_eligible_closure == bool(eligible_incomplete):
        raise ProofDAGIntegrityError(
            "eligible edge-closure reason disagrees with final parent coverage"
        )
    if set(incomplete) != set(eligible_incomplete).union(verified_skipped):
        raise ProofDAGIntegrityError(
            "raw incomplete parents do not partition into eligible and verified-skipped"
        )
    if len(parent_results) != parents_attempted:
        raise ProofDAGIntegrityError("parent result count differs from attempted count")
    if sum(len(result.appended_moves) for result in parent_results) != edges_appended:
        raise ProofDAGIntegrityError("parent result edge accounting is inconsistent")
    completed_transitions = sum(
        not result.complete_before and result.complete_after
        for result in parent_results
    )
    if parents_completed != completed_transitions:
        raise ProofDAGIntegrityError("completed-parent accounting is inconsistent")
    if (
        final.head.frontier_record_count - initial_head.frontier_record_count
        != edges_appended
    ):
        raise ProofDAGIntegrityError("DAG head delta differs from appended-edge count")
    for result in parent_results:
        legal = result.legal_moves
        if tuple(sorted(legal)) != legal or len(set(legal)) != len(legal):
            raise ProofDAGIntegrityError("parent result legal moves are not canonical")
        existing_set = set(result.existing_moves_before)
        appended_set = set(result.appended_moves)
        remaining_set = set(result.remaining_moves)
        if (
            existing_set.intersection(appended_set)
            or existing_set.intersection(remaining_set)
            or appended_set.intersection(remaining_set)
            or existing_set.union(appended_set, remaining_set) != set(legal)
            or result.existing_moves_before
            != tuple(uci for uci in legal if uci in existing_set)
            or result.appended_moves
            != tuple(uci for uci in legal if uci in appended_set)
            or result.remaining_moves
            != tuple(uci for uci in legal if uci in remaining_set)
            or result.complete_before != (not appended_set and not remaining_set)
            or result.complete_after != (not remaining_set)
        ):
            raise ProofDAGIntegrityError("parent result does not partition legal moves")
    return ExpansionReport(
        stop_reason=stop_reason,
        parents_attempted=parents_attempted,
        parents_completed=parents_completed,
        edges_appended=edges_appended,
        elapsed_seconds=max(0.0, time.monotonic() - started),
        parent_results=tuple(parent_results),
        incomplete_parent_node_sha256s=incomplete,
        eligible_incomplete_parent_node_sha256s=eligible_incomplete,
        verified_skipped_node_sha256s=verified_skipped,
        terminal_node_sha256s=terminals,
        dag_head_before=initial_head,
        dag_head_after=final.head,
        fact_head_before=fact_head_before,
        fact_head_after=fact_head_after,
    )


def expand_proof_dag(
    dag: ProofDAG,
    limits: ExpansionLimits | None = None,
    *,
    journal: WDLFactJournal | None = None,
) -> ExpansionReport:
    """Materialise missing exact legal-move edges under cooperative bounds.

    The selected parent is always the least incomplete exact node by
    ``(first_frontier_record_index, node_sha256)``.  All of that parent's
    missing moves are attempted in canonical UCI order unless an edge or time
    bound interrupts it.  Newly materialised nodes participate in subsequent
    scheduling decisions during the same invocation.
    """

    if not isinstance(dag, ProofDAG) or dag.closed:
        raise TypeError("dag must be an open ProofDAG")
    if limits is None:
        limits = ExpansionLimits()
    if not isinstance(limits, ExpansionLimits):
        raise TypeError("limits must be an ExpansionLimits instance or None")
    if journal is not None:
        if not isinstance(journal, WDLFactJournal) or journal.closed:
            raise TypeError("journal must be an open WDLFactJournal or None")
        if journal.dag is not dag:
            raise ValueError("journal must be bound to the exact ProofDAG handle")

    started = time.monotonic()
    initial = _materialization_snapshot(dag)
    initial_head = initial.head
    expected_head = initial_head
    initial_fact = None if journal is None else _fact_snapshot(journal)
    verified_node_sha256s = (
        frozenset()
        if initial_fact is None
        else initial_fact.verified_node_sha256s
    )
    parent_by_sha256 = {
        parent.node.node_sha256: parent for parent in initial.parents
    }
    if len(parent_by_sha256) != len(initial.parents):
        raise ProofDAGIntegrityError(
            "audited materialisation contains duplicate exact node identities"
        )
    unknown_verified = verified_node_sha256s.difference(parent_by_sha256)
    if unknown_verified:
        raise ExpansionConcurrentMutationError(
            "fact journal names nodes absent from the initial audited DAG snapshot"
        )
    eligible_heap = [
        _state_priority(parent)
        for parent in initial.parents
        if _eligible(parent, verified_node_sha256s)
    ]
    heapq.heapify(eligible_heap)
    parents_attempted = 0
    parents_completed = 0
    edges_appended = 0
    parent_results: list[ParentExpansionResult] = []
    stop_reason: ExpansionStopReason

    while True:
        if not eligible_heap:
            raw_incomplete_remains = any(
                parent.terminal_code is None and not parent.complete
                for parent in parent_by_sha256.values()
            )
            stop_reason = (
                ExpansionStopReason.LOCAL_ELIGIBLE_EDGE_CLOSURE_NOT_CHESS_SOLVED
                if raw_incomplete_remains
                else ExpansionStopReason.LOCAL_MATERIALIZED_EDGE_CLOSURE_NOT_CHESS_SOLVED
            )
            break
        if limits.max_parents is not None and parents_attempted >= limits.max_parents:
            stop_reason = ExpansionStopReason.PARENT_LIMIT
            break
        if limits.max_edges is not None and edges_appended >= limits.max_edges:
            stop_reason = ExpansionStopReason.EDGE_LIMIT
            break
        if (
            limits.max_seconds is not None
            and time.monotonic() - started >= limits.max_seconds
        ):
            stop_reason = ExpansionStopReason.TIME_LIMIT
            break

        priority = heapq.heappop(eligible_heap)
        parent_before = parent_by_sha256.get(priority[1])
        if (
            parent_before is None
            or _state_priority(parent_before) != priority
            or not _eligible(parent_before, verified_node_sha256s)
        ):
            raise ProofDAGIntegrityError(
                "in-memory eligible-parent heap diverged from exact materialisation"
            )
        parents_attempted += 1
        remaining_edge_budget = (
            None
            if limits.max_edges is None
            else limits.max_edges - edges_appended
        )
        if remaining_edge_budget is None:
            selected_uci = parent_before.missing_moves
        else:
            selected_uci = parent_before.missing_moves[:remaining_edge_budget]
        interrupted = (
            ExpansionStopReason.EDGE_LIMIT
            if len(selected_uci) < len(parent_before.missing_moves)
            else None
        )

        move_by_uci = {
            move.uci(): move for move in legal_moves(parent_before.node.position)
        }
        requests: list[DAGMoveAppendRequest] = []
        expected_children: list[str] = []
        for uci in selected_uci:
            move = move_by_uci.get(uci)
            if move is None:
                raise ProofDAGIntegrityError(
                    "a planned legal move disappeared from the exact parent state"
                )
            child_position, child_history, expected_child_sha256 = _derive_child_identity(
                parent_before.node,
                move,
            )
            requests.append(
                DAGMoveAppendRequest(
                    child_position=child_position,
                    child_history=child_history,
                    parent_frontier_content_sha256=(
                        parent_before.parent_frontier_content_sha256
                    ),
                    uci=uci,
                    lineage=_lineage(parent_before.node.node_sha256, uci),
                )
            )
            expected_children.append(expected_child_sha256)

        batch_result = dag.append_moves_batch(requests)

        expected_manifest = bytes.fromhex(expected_head.frontier_manifest_sha256)
        next_record_index = expected_head.frontier_record_count
        next_frame_offset = expected_head.frontier_size
        if (
            batch_result.request_count != len(requests)
            or batch_result.appended_count != len(requests)
            or batch_result.frontier_record_count_before
            != expected_head.frontier_record_count
            or batch_result.frontier_size_before != expected_head.frontier_size
        ):
            raise ExpansionConcurrentMutationError(
                "move batch began from an unexpected proof DAG boundary"
            )
        for uci, child_sha256, request, result in zip(
            selected_uci,
            expected_children,
            requests,
            batch_result.results,
            strict=True,
        ):
            edge = result.edge
            expected_lineage = _lineage(parent_before.node.node_sha256, uci)
            if (
                not result.appended
                or edge.frontier_record_index != next_record_index
                or edge.frame_offset != next_frame_offset
                or edge.frame_end_offset <= edge.frame_offset
                or not _is_sha256_hex(edge.frontier_content_sha256)
                or edge.parent_frontier_content_sha256
                != parent_before.parent_frontier_content_sha256
                or edge.parent_node_sha256 != parent_before.node.node_sha256
                or edge.child_node_sha256 != child_sha256
                or result.node.node_sha256 != child_sha256
                or result.node.position != request.child_position
                or result.node.history != request.child_history
                or result.node.rule_profile_id != RULE_PROFILE_ID
                or _move_uci(edge) != uci
                or edge.lineage != expected_lineage
            ):
                raise ExpansionConcurrentMutationError(
                    "move batch returned a noncontiguous or substituted edge"
                )
            expected_manifest = advance_proof_dag_manifest(
                expected_manifest,
                edge,
            )
            next_record_index += 1
            next_frame_offset = edge.frame_end_offset
        if (
            batch_result.frontier_record_count_after != next_record_index
            or batch_result.frontier_size_after != next_frame_offset
        ):
            raise ExpansionConcurrentMutationError(
                "proof DAG authority moved while reconciling a move batch"
            )

        selected_set = frozenset(selected_uci)
        existing_after = tuple(
            uci
            for uci in parent_before.legal_moves
            if uci in parent_before.existing_moves or uci in selected_set
        )
        remaining_after = tuple(
            uci
            for uci in parent_before.legal_moves
            if uci not in parent_before.existing_moves and uci not in selected_set
        )
        parent_after = _ParentState(
            node=parent_before.node,
            parent_frontier_content_sha256=(
                parent_before.parent_frontier_content_sha256
            ),
            terminal_code=None,
            legal_moves=parent_before.legal_moves,
            existing_moves=existing_after,
            missing_moves=remaining_after,
            duplicate_existing_occurrences=(
                parent_before.duplicate_existing_occurrences
            ),
        )
        parent_by_sha256[parent_before.node.node_sha256] = parent_after

        new_node_count = 0
        for child_sha256, result in zip(
            expected_children,
            batch_result.results,
            strict=True,
        ):
            existing_child = parent_by_sha256.get(child_sha256)
            if existing_child is None:
                child_state = _new_parent_state(result.node, result.edge)
                parent_by_sha256[child_sha256] = child_state
                new_node_count += 1
                if _eligible(child_state, verified_node_sha256s):
                    heapq.heappush(eligible_heap, _state_priority(child_state))
            elif existing_child.node != result.node:
                raise ExpansionConcurrentMutationError(
                    "move batch returned a substituted exact child node"
                )
        expected_head = ExpansionDAGHead(
            rule_profile_id=RULE_PROFILE_ID,
            frontier_record_count=next_record_index,
            sqlite_edge_count=next_record_index,
            sqlite_node_count=expected_head.sqlite_node_count + new_node_count,
            frontier_size=next_frame_offset,
            last_frontier_content_sha256=(
                expected_head.last_frontier_content_sha256
                if not batch_result.results
                else batch_result.results[-1].edge.frontier_content_sha256
            ),
            frontier_manifest_sha256=expected_manifest.hex(),
        )
        edges_appended += len(requests)
        parent_result = _result_for_parent(
            parent_before,
            parent_after,
            selected_uci,
        )
        parent_results.append(parent_result)
        if parent_result.complete_after:
            parents_completed += 1

        if interrupted is not None:
            if _eligible(parent_after, verified_node_sha256s):
                heapq.heappush(eligible_heap, _state_priority(parent_after))
            stop_reason = interrupted
            break

    expected_heap = sorted(
        _state_priority(parent)
        for parent in parent_by_sha256.values()
        if _eligible(parent, verified_node_sha256s)
    )
    if sorted(eligible_heap) != expected_heap:
        raise ProofDAGIntegrityError(
            "in-memory eligible-parent heap does not match exact parent state"
        )

    final_fact = None if journal is None else _fact_snapshot(journal)
    if initial_fact is not None and final_fact != initial_fact:
        raise ExpansionConcurrentMutationError(
            "WDL fact-journal authority moved during deterministic expansion"
        )

    final = _materialization_snapshot(dag)
    if final.head != expected_head:
        raise ExpansionConcurrentMutationError(
            "proof DAG authority moved before expansion reporting completed"
        )
    expected_parents = tuple(
        sorted(parent_by_sha256.values(), key=_state_priority)
    )
    if final.parents != expected_parents:
        raise ExpansionConcurrentMutationError(
            "final audited DAG replay differs from incremental expansion state"
        )

    return _make_report(
        final=final,
        expected_head=expected_head,
        initial_head=initial_head,
        verified_node_sha256s=verified_node_sha256s,
        fact_head_before=None if initial_fact is None else initial_fact.head,
        fact_head_after=None if final_fact is None else final_fact.head,
        stop_reason=stop_reason,
        started=started,
        parents_attempted=parents_attempted,
        parents_completed=parents_completed,
        edges_appended=edges_appended,
        parent_results=parent_results,
    )


__all__ = [
    "EXPANSION_HEAD_SCHEMA",
    "EXPANSION_MANIFEST_SCHEMA",
    "EXPANSION_SCHEMA",
    "ExpansionConcurrentMutationError",
    "ExpansionDAGHead",
    "ExpansionLimits",
    "ExpansionReport",
    "ExpansionStopReason",
    "ParentExpansionResult",
    "expand_proof_dag",
]
