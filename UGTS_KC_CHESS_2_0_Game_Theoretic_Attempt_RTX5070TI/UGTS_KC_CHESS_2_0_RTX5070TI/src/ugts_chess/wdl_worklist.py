"""Deterministic monotone closure over an audited proof DAG and WDL facts.

The worklist is deliberately reconstructible rather than persistent.  A
restart scans the exact durable authorities and seeds two classes of work:

* every automatic terminal without a verified fact; and
* every unverified exact parent of every verified fact.

Candidates are deduplicated and ordered by the node's first frontier
occurrence followed by its full node SHA-256.  An open candidate is removed
after one attempt.  It becomes eligible again only when a newly committed
child fact enqueues it, or when an unexpected authority-head change causes a
full rebuild.

``local_quiescence_not_chess_solved`` means only that this finite, currently
materialised DAG/fact prefix has no further one-hop promotion available.  It
is explicitly *not* a claim that chess, a root, or even every DAG node is
solved.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import heapq
import math
import time
from typing import Callable

from .game_state import RULE_PROFILE_ID, automatic_status
from .hashing import canonical_json_bytes
from .proof_dag import (
    DAGAuditReport,
    DAGNode,
    ProofDAG,
    ProofDAGIntegrityError,
)
from .wdl_fact_journal import FactEntry, FactJournalHead, WDLFactJournal
from .wdl_fact_propagation import (
    FactPropagationResult,
    propagate_wdl_fact_one_hop,
)


WORKLIST_SCHEMA = "ugts-chess-deterministic-wdl-worklist-1.0"
DAG_MANIFEST_SCHEMA = "ugts-chess-proof-dag-ordered-manifest-1.0"
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


@dataclass(frozen=True, slots=True)
class DAGHead:
    """Strict identity for one fully audited, materialised ProofDAG prefix.

    Frontier payload hashes are not themselves chained.  The manifest digest
    therefore commits to every ordered occurrence and its validated graph
    identities; count, size, and last-record hash alone would not bind an
    earlier same-size rewrite.
    """

    rule_profile_id: str
    frontier_record_count: int
    sqlite_edge_count: int
    sqlite_node_count: int
    frontier_size: int
    last_frontier_content_sha256: str | None
    frontier_manifest_sha256: str

    def __post_init__(self) -> None:
        if self.rule_profile_id != RULE_PROFILE_ID:
            raise ValueError("DAG head rule profile is not canonical")
        record_count = _require_count(
            self.frontier_record_count,
            label="frontier_record_count",
        )
        edge_count = _require_count(self.sqlite_edge_count, label="sqlite_edge_count")
        node_count = _require_count(self.sqlite_node_count, label="sqlite_node_count")
        frontier_size = _require_count(self.frontier_size, label="frontier_size")
        if record_count != edge_count:
            raise ValueError("DAG head frontier and SQLite edge counts differ")
        if node_count > edge_count:
            raise ValueError("DAG head has more nodes than frontier occurrences")
        if frontier_size == 0:
            raise ValueError("DAG head frontier size must include its header")
        if record_count == 0:
            if self.last_frontier_content_sha256 is not None:
                raise ValueError("empty DAG head may not name a last frontier record")
        elif not _is_sha256_hex(self.last_frontier_content_sha256):
            raise ValueError("non-empty DAG head needs a lowercase SHA-256 record id")
        if not _is_sha256_hex(self.frontier_manifest_sha256):
            raise ValueError("DAG head needs a lowercase SHA-256 manifest id")

    def record(self) -> dict[str, object]:
        return {
            "schema": WORKLIST_SCHEMA,
            "rule_profile_id": self.rule_profile_id,
            "frontier_record_count": self.frontier_record_count,
            "sqlite_edge_count": self.sqlite_edge_count,
            "sqlite_node_count": self.sqlite_node_count,
            "frontier_size": self.frontier_size,
            "last_frontier_content_sha256": self.last_frontier_content_sha256,
            "frontier_manifest_sha256": self.frontier_manifest_sha256,
        }


@dataclass(frozen=True, slots=True)
class WorklistLimits:
    """Optional cooperative bounds checked between complete audited steps.

    ``None`` means unbounded for that dimension.  A head audit, rebuild, or
    propagation already in progress is never interrupted to meet a wall-clock
    deadline, so ``max_seconds`` is not a hard real-time bound.
    """

    max_attempts: int | None = None
    max_promotions: int | None = None
    max_seconds: float | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("max_attempts", self.max_attempts),
            ("max_promotions", self.max_promotions),
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


class WorklistStepStatus(str, Enum):
    """Outcome of one driver step."""

    PROMOTED = "promoted"
    OPEN = "open"
    ALREADY_VERIFIED = "already_verified"
    HEAD_CHANGE_REBUILT = "head_change_rebuilt"
    EMPTY = "empty"


class WorklistStopReason(str, Enum):
    """Why a bounded closure run returned to its caller."""

    LOCAL_QUIESCENCE_NOT_CHESS_SOLVED = "local_quiescence_not_chess_solved"
    ATTEMPT_LIMIT = "attempt_limit"
    PROMOTION_LIMIT = "promotion_limit"
    TIME_LIMIT = "time_limit"


@dataclass(frozen=True, slots=True)
class WorklistStepResult:
    """Structured result for an attempt, empty check, or safe rebuild."""

    status: WorklistStepStatus
    node_sha256: str | None
    first_frontier_record_index: int | None
    propagation: FactPropagationResult | None
    enqueued_parent_node_sha256s: tuple[str, ...]
    pending_count: int
    dag_head_before: DAGHead
    dag_head_after: DAGHead
    fact_head_before: FactJournalHead
    fact_head_after: FactJournalHead
    rebuilt: bool
    detail: str
    observer_error: str | None = None

    @property
    def attempted(self) -> bool:
        return self.propagation is not None

    @property
    def promoted(self) -> bool:
        return self.propagation is not None and self.propagation.promoted


@dataclass(frozen=True, slots=True)
class WorklistRunReport:
    """Bounded-run accounting anchored to exact observed authority heads."""

    stop_reason: WorklistStopReason
    attempts: int
    promotions: int
    open_attempts: int
    already_verified_attempts: int
    steps: int
    rebuilds: int
    elapsed_seconds: float
    pending_count: int
    initial_dag_head: DAGHead
    final_dag_head: DAGHead
    initial_fact_head: FactJournalHead
    final_fact_head: FactJournalHead
    last_step: WorklistStepResult | None
    observer_errors: tuple[str, ...] = ()

    @property
    def local_quiescence(self) -> bool:
        return (
            self.stop_reason
            == WorklistStopReason.LOCAL_QUIESCENCE_NOT_CHESS_SOLVED
        )

    @property
    def chess_solved(self) -> bool:
        """Always false: this driver proves only local monotone closure."""

        return False


WorklistObserver = Callable[[WorklistStepResult], None]


class WorklistConcurrentMutationError(RuntimeError):
    """Raised when a coherent authority snapshot cannot be obtained."""


class WorklistReentrancyError(RuntimeError):
    """Raised when an observer tries to drive its own active worklist."""


def _head_from_audit(
    dag: ProofDAG,
    audit: DAGAuditReport,
    *,
    last_frontier_content_sha256: str | None,
    frontier_manifest_sha256: str,
) -> DAGHead:
    audit.require_valid()
    return DAGHead(
        rule_profile_id=dag.rule_profile_id,
        frontier_record_count=audit.frontier_record_count,
        sqlite_edge_count=audit.sqlite_edge_count,
        sqlite_node_count=audit.sqlite_node_count,
        frontier_size=audit.frontier_size,
        last_frontier_content_sha256=last_frontier_content_sha256,
        frontier_manifest_sha256=frontier_manifest_sha256,
    )


def _snapshot_dag_head(dag: ProofDAG) -> DAGHead:
    """Obtain one stable audited DAG head without relying on private SQLite."""

    for _ in range(_MAX_STABLE_SNAPSHOT_ATTEMPTS):
        before = dag.audit().require_valid()
        last_sha256: str | None = None
        edge_count = 0
        last_frame_end = 0
        manifest = hashlib.sha256()
        manifest.update(DAG_MANIFEST_SCHEMA.encode("ascii") + b"\x00")
        for edge in dag.iter_edges():
            if edge.frontier_record_index != edge_count:
                raise ProofDAGIntegrityError(
                    "frontier edge ordinals are not contiguous from zero"
                )
            manifest_record = canonical_json_bytes(
                {
                    "frontier_record_index": edge.frontier_record_index,
                    "frontier_content_sha256": edge.frontier_content_sha256,
                    "parent_frontier_content_sha256": (
                        edge.parent_frontier_content_sha256
                    ),
                    "parent_node_sha256": edge.parent_node_sha256,
                    "child_node_sha256": edge.child_node_sha256,
                }
            )
            manifest.update(len(manifest_record).to_bytes(8, "big"))
            manifest.update(manifest_record)
            edge_count += 1
            last_sha256 = edge.frontier_content_sha256
            last_frame_end = edge.frame_end_offset
        after = dag.audit().require_valid()
        if before != after or edge_count != after.frontier_record_count:
            continue
        if edge_count and last_frame_end != after.frontier_size:
            raise ProofDAGIntegrityError(
                "last frontier edge does not end at the audited DAG boundary"
            )
        return _head_from_audit(
            dag,
            after,
            last_frontier_content_sha256=last_sha256,
            frontier_manifest_sha256=manifest.hexdigest(),
        )
    raise WorklistConcurrentMutationError(
        "proof DAG changed repeatedly while capturing an audited head"
    )


def _stable_fact_snapshot(
    journal: WDLFactJournal,
) -> tuple[FactJournalHead, tuple[FactEntry, ...]]:
    """Return one coherent fact head and entry tuple under the public API."""

    for _ in range(_MAX_STABLE_SNAPSHOT_ATTEMPTS):
        before = journal.head_snapshot()
        entries = tuple(journal.iter_entries())
        after = journal.head_snapshot()
        if before == after and len(entries) == after.record_count:
            return after, entries
    raise WorklistConcurrentMutationError(
        "WDL fact journal changed repeatedly while capturing a replayed prefix"
    )


class DeterministicWDLWorklist:
    """Restart-reconstructible deterministic one-hop WDL closure driver."""

    def __init__(self, dag: ProofDAG, journal: WDLFactJournal) -> None:
        if not isinstance(dag, ProofDAG) or dag.closed:
            raise TypeError("dag must be an open ProofDAG")
        if not isinstance(journal, WDLFactJournal) or journal.closed:
            raise TypeError("journal must be an open WDLFactJournal")
        if journal.dag is not dag:
            raise ValueError("fact journal is not bound to the supplied ProofDAG")
        self.dag = dag
        self.journal = journal
        self._heap: list[tuple[int, str]] = []
        self._queued: set[str] = set()
        self._fact_nodes: set[str] = set()
        self._dag_head: DAGHead | None = None
        self._fact_head: FactJournalHead | None = None
        self._generation = 0
        self._observer_active = False

    @property
    def built(self) -> bool:
        return self._dag_head is not None and self._fact_head is not None

    @property
    def pending_count(self) -> int:
        return len(self._heap)

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def dag_head(self) -> DAGHead | None:
        return self._dag_head

    @property
    def fact_head(self) -> FactJournalHead | None:
        return self._fact_head

    def _invalidate_reconstructible_state(self) -> None:
        """Discard non-authoritative scheduling state after an interrupted step."""

        self._heap.clear()
        self._queued.clear()
        self._fact_nodes.clear()
        self._dag_head = None
        self._fact_head = None

    def _enqueue_node(self, node: DAGNode) -> bool:
        if node.node_sha256 in self._fact_nodes or node.node_sha256 in self._queued:
            return False
        key = (node.first_frontier_record_index, node.node_sha256)
        heapq.heappush(self._heap, key)
        self._queued.add(node.node_sha256)
        return True

    def _exact_parent_nodes(self, child_node_sha256: str) -> tuple[DAGNode, ...]:
        parents: dict[str, DAGNode] = {}
        for edge in self.dag.incoming_edges(child_node_sha256):
            if edge.child_node_sha256 != child_node_sha256:
                raise ProofDAGIntegrityError(
                    "incoming-edge query returned a different child node"
                )
            parent_sha256 = edge.parent_node_sha256
            if parent_sha256 is None or parent_sha256 in parents:
                continue
            parent = self.dag.get_node(parent_sha256)
            if parent is None:
                raise ProofDAGIntegrityError(
                    "incoming frontier edge names a missing parent node"
                )
            parents[parent_sha256] = parent
        return tuple(
            sorted(
                parents.values(),
                key=lambda node: (
                    node.first_frontier_record_index,
                    node.node_sha256,
                ),
            )
        )

    def _enqueue_exact_parents(self, child_node_sha256: str) -> tuple[str, ...]:
        enqueued: list[str] = []
        for parent in self._exact_parent_nodes(child_node_sha256):
            if self._enqueue_node(parent):
                enqueued.append(parent.node_sha256)
        return tuple(enqueued)

    def rebuild(self) -> int:
        """Reconstruct all currently eligible work from durable authorities."""

        if self._observer_active:
            raise WorklistReentrancyError(
                "an observer may not rebuild its active WDL worklist"
            )
        if self.dag.closed:
            raise TypeError("dag must be an open ProofDAG")
        if self.journal.closed:
            raise TypeError("journal must be an open WDLFactJournal")

        for _ in range(_MAX_STABLE_SNAPSHOT_ATTEMPTS):
            dag_before = _snapshot_dag_head(self.dag)
            fact_head, entries = _stable_fact_snapshot(self.journal)
            fact_nodes = {entry.fact.node_sha256 for entry in entries}

            heap: list[tuple[int, str]] = []
            queued: set[str] = set()

            def enqueue(node: DAGNode) -> None:
                if node.node_sha256 in fact_nodes or node.node_sha256 in queued:
                    return
                heapq.heappush(
                    heap,
                    (node.first_frontier_record_index, node.node_sha256),
                )
                queued.add(node.node_sha256)

            for node in self.dag.iter_nodes():
                if (
                    node.node_sha256 not in fact_nodes
                    and automatic_status(node.position, node.history).terminal
                ):
                    enqueue(node)

            for entry in entries:
                child_sha256 = entry.fact.node_sha256
                for parent in self._exact_parent_nodes(child_sha256):
                    enqueue(parent)

            dag_after = _snapshot_dag_head(self.dag)
            fact_after = self.journal.head_snapshot()
            if dag_before != dag_after or fact_head != fact_after:
                continue

            self._heap = heap
            self._queued = queued
            self._fact_nodes = fact_nodes
            self._dag_head = dag_after
            self._fact_head = fact_after
            self._generation += 1
            return len(heap)

        raise WorklistConcurrentMutationError(
            "authorities changed repeatedly while rebuilding the WDL worklist"
        )

    def _heads(self) -> tuple[DAGHead, FactJournalHead]:
        return _snapshot_dag_head(self.dag), self.journal.head_snapshot()

    def _notify(
        self,
        result: WorklistStepResult,
        observer: WorklistObserver | None,
    ) -> WorklistStepResult:
        if observer is None:
            return result
        try:
            self._observer_active = True
            observer(result)
        except Exception as exc:  # callback failures are reporting failures only
            return replace(
                result,
                observer_error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            self._observer_active = False
        return result

    def _head_change_result(
        self,
        *,
        old_dag_head: DAGHead,
        old_fact_head: FactJournalHead,
        detail: str,
    ) -> WorklistStepResult:
        self.rebuild()
        assert self._dag_head is not None
        assert self._fact_head is not None
        return WorklistStepResult(
            status=WorklistStepStatus.HEAD_CHANGE_REBUILT,
            node_sha256=None,
            first_frontier_record_index=None,
            propagation=None,
            enqueued_parent_node_sha256s=(),
            pending_count=self.pending_count,
            dag_head_before=old_dag_head,
            dag_head_after=self._dag_head,
            fact_head_before=old_fact_head,
            fact_head_after=self._fact_head,
            rebuilt=True,
            detail=detail,
        )

    def step(
        self,
        *,
        observer: WorklistObserver | None = None,
    ) -> WorklistStepResult:
        """Attempt the deterministic minimum candidate, or report no work."""

        if self._observer_active:
            raise WorklistReentrancyError(
                "an observer may not step its active WDL worklist"
            )
        if not self.built:
            self.rebuild()
        assert self._dag_head is not None
        assert self._fact_head is not None
        anchored_dag = self._dag_head
        anchored_fact = self._fact_head
        current_dag, current_fact = self._heads()
        if current_dag != anchored_dag or current_fact != anchored_fact:
            return self._notify(
                self._head_change_result(
                    old_dag_head=anchored_dag,
                    old_fact_head=anchored_fact,
                    detail="an authority head changed before the next worklist step",
                ),
                observer,
            )

        if not self._heap:
            return self._notify(
                WorklistStepResult(
                    status=WorklistStepStatus.EMPTY,
                    node_sha256=None,
                    first_frontier_record_index=None,
                    propagation=None,
                    enqueued_parent_node_sha256s=(),
                    pending_count=0,
                    dag_head_before=anchored_dag,
                    dag_head_after=current_dag,
                    fact_head_before=anchored_fact,
                    fact_head_after=current_fact,
                    rebuilt=False,
                    detail="the reconstructed local candidate heap is empty",
                ),
                observer,
            )

        first_index, node_sha256 = heapq.heappop(self._heap)
        self._queued.remove(node_sha256)
        try:
            propagation = propagate_wdl_fact_one_hop(
                self.dag,
                self.journal,
                node_sha256,
            )
        except BaseException:
            # The call may have failed before *or* after a durable fact commit.
            # Reconstruct from both authorities on the next entry rather than
            # treating the popped node as open or guessing whether to requeue it.
            self._invalidate_reconstructible_state()
            raise

        try:
            dag_after, fact_after = self._heads()
            expected_fact_change = (
                propagation.promoted
                and propagation.fact_record_index == anchored_fact.record_count
                and propagation.fact_content_sha256 == fact_after.head_content_sha256
                and fact_after.record_count == anchored_fact.record_count + 1
            )
            unchanged_fact = not propagation.promoted and fact_after == anchored_fact
            unexpected_change = dag_after != anchored_dag or not (
                expected_fact_change or unchanged_fact
            )

            enqueued_parents: tuple[str, ...] = ()
            rebuilt = False
            detail_suffix = ""
            if unexpected_change:
                self.rebuild()
                assert self._dag_head is not None
                assert self._fact_head is not None
                dag_after = self._dag_head
                fact_after = self._fact_head
                rebuilt = True
                detail_suffix = "; authority movement required a safe full rebuild"
            elif propagation.promoted:
                self._dag_head = dag_after
                self._fact_head = fact_after
                self._fact_nodes.add(node_sha256)
                enqueued_parents = self._enqueue_exact_parents(node_sha256)
        except BaseException:
            # Parent scheduling and head reconciliation are part of the same
            # logical step as propagation.  A durable child fact without its
            # parents queued must force a full restart reconstruction.
            self._invalidate_reconstructible_state()
            raise

        if propagation.promoted:
            status = WorklistStepStatus.PROMOTED
        elif propagation.status == "already_verified":
            status = WorklistStepStatus.ALREADY_VERIFIED
        else:
            status = WorklistStepStatus.OPEN

        result = WorklistStepResult(
            status=status,
            node_sha256=node_sha256,
            first_frontier_record_index=first_index,
            propagation=propagation,
            enqueued_parent_node_sha256s=enqueued_parents,
            pending_count=self.pending_count,
            dag_head_before=anchored_dag,
            dag_head_after=dag_after,
            fact_head_before=anchored_fact,
            fact_head_after=fact_after,
            rebuilt=rebuilt,
            detail=propagation.detail + detail_suffix,
        )
        return self._notify(result, observer)

    def run(
        self,
        limits: WorklistLimits | None = None,
        *,
        observer: WorklistObserver | None = None,
    ) -> WorklistRunReport:
        """Run bounded monotone closure over the currently materialised DAG."""

        if self._observer_active:
            raise WorklistReentrancyError(
                "an observer may not run its active WDL worklist"
            )
        if limits is None:
            limits = WorklistLimits()
        if not isinstance(limits, WorklistLimits):
            raise TypeError("limits must be a WorklistLimits instance or None")

        started = time.monotonic()
        rebuilds = 0
        if not self.built:
            self.rebuild()
            rebuilds += 1
        else:
            assert self._dag_head is not None
            assert self._fact_head is not None
            current_dag, current_fact = self._heads()
            if current_dag != self._dag_head or current_fact != self._fact_head:
                self.rebuild()
                rebuilds += 1
        assert self._dag_head is not None
        assert self._fact_head is not None
        initial_dag_head = self._dag_head
        initial_fact_head = self._fact_head

        attempts = 0
        promotions = 0
        open_attempts = 0
        already_verified_attempts = 0
        steps = 0
        last_step: WorklistStepResult | None = None
        observer_errors: list[str] = []

        while True:
            anchored_dag = self._dag_head
            anchored_fact = self._fact_head
            assert anchored_dag is not None
            assert anchored_fact is not None
            current_dag, current_fact = self._heads()
            if current_dag != anchored_dag or current_fact != anchored_fact:
                self.rebuild()
                rebuilds += 1
                continue

            if not self._heap:
                stop_reason = (
                    WorklistStopReason.LOCAL_QUIESCENCE_NOT_CHESS_SOLVED
                )
                break

            if limits.max_attempts is not None and attempts >= limits.max_attempts:
                stop_reason = WorklistStopReason.ATTEMPT_LIMIT
                break
            if (
                limits.max_promotions is not None
                and promotions >= limits.max_promotions
            ):
                stop_reason = WorklistStopReason.PROMOTION_LIMIT
                break
            if (
                limits.max_seconds is not None
                and time.monotonic() - started >= limits.max_seconds
            ):
                stop_reason = WorklistStopReason.TIME_LIMIT
                break

            result = self.step(observer=observer)
            last_step = result
            steps += 1
            if result.rebuilt:
                rebuilds += 1
            if result.observer_error is not None:
                observer_errors.append(result.observer_error)
            if result.attempted:
                attempts += 1
            if result.promoted:
                promotions += 1
            elif result.status == WorklistStepStatus.OPEN:
                open_attempts += 1
            elif result.status == WorklistStepStatus.ALREADY_VERIFIED:
                already_verified_attempts += 1

        assert self._dag_head is not None
        assert self._fact_head is not None
        return WorklistRunReport(
            stop_reason=stop_reason,
            attempts=attempts,
            promotions=promotions,
            open_attempts=open_attempts,
            already_verified_attempts=already_verified_attempts,
            steps=steps,
            rebuilds=rebuilds,
            elapsed_seconds=time.monotonic() - started,
            pending_count=self.pending_count,
            initial_dag_head=initial_dag_head,
            final_dag_head=self._dag_head,
            initial_fact_head=initial_fact_head,
            final_fact_head=self._fact_head,
            last_step=last_step,
            observer_errors=tuple(observer_errors),
        )


def run_wdl_worklist(
    dag: ProofDAG,
    journal: WDLFactJournal,
    limits: WorklistLimits | None = None,
    *,
    observer: WorklistObserver | None = None,
) -> WorklistRunReport:
    """Construct, rebuild, and run one deterministic local closure driver."""

    worklist = DeterministicWDLWorklist(dag, journal)
    return worklist.run(limits, observer=observer)


__all__ = [
    "DAG_MANIFEST_SCHEMA",
    "DAGHead",
    "DeterministicWDLWorklist",
    "WORKLIST_SCHEMA",
    "WorklistConcurrentMutationError",
    "WorklistLimits",
    "WorklistObserver",
    "WorklistReentrancyError",
    "WorklistRunReport",
    "WorklistStepResult",
    "WorklistStepStatus",
    "WorklistStopReason",
    "run_wdl_worklist",
]
