"""Bounded proof-number search over immutable positional-superko roots.

This module is a deliberately small host-RAM integration slice.  It consumes
``PersistentState`` values directly and asks ``PersistentHistory`` for exact
membership through :mod:`ugts_go19.persistent_engine`; it never converts a
history root to a flat ``frozenset``.  The implementation is a tree PNS for
1x1 and 2x2 validation fixtures.  It is not production DFPN, a checkpoint
format, or evidence that 19x19 Go is solved.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import monotonic
from typing import Iterable

from .constants import BLACK
from .persistent_engine import (
    PersistentState,
    initial_state,
    ordered_children,
)
from .persistent_history import PersistentHistory
from .rules import Rules
from .score import area_score2


INF = (1 << 64) - 1
PROOF_ARITHMETIC = {
    "bits": 64,
    "endianness": "little",
    "infinity": str(INF),
    "kind": "saturating_uint64",
}


def _sat_add(values: Iterable[int]) -> int:
    """Add proof numbers with the proof-format's unsigned-64 saturation."""

    total = 0
    for value in values:
        if type(value) is not int or not 0 <= value <= INF:
            raise ValueError("proof number is outside uint64")
        if total > INF - value:
            return INF
        total += value
    return total


@dataclass(slots=True)
class PersistentPNSNode:
    """One tree-PNS node retaining its immutable full-history root."""

    state: PersistentState
    parent: "PersistentPNSNode | None" = None
    move: int | None = None
    children: list["PersistentPNSNode"] = field(default_factory=list)
    expanded: bool = False
    proof: int = 1
    disproof: int = 1

    @property
    def is_or(self) -> bool:
        # Proposition: Black can force final score2 >= threshold2.
        return self.state.to_play == BLACK


@dataclass(frozen=True, slots=True)
class PersistentPNSResult:
    """Outcome of one bounded run; an unfinished frontier is ``UNKNOWN``."""

    status: str
    threshold2: int
    proof_number: int
    disproof_number: int
    expanded_nodes: int
    generated_nodes: int
    max_ply: int
    elapsed_seconds: float

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = asdict(self)
        payload["proof_arithmetic"] = dict(PROOF_ARITHMETIC)
        payload["scope"] = "bounded-host-ram-psk-1x1-2x2"
        return payload


class PersistentProofNumberSearch:
    """Exact bounded PNS using persistent roots instead of flat history sets.

    The search deliberately has no transposition table: every node owns the
    complete proof-authoritative state through its immutable ``history_root``.
    The supplied history store may use an injected index digest; exact board
    bytes still decide positional-superko membership.
    """

    def __init__(
        self,
        rules: Rules,
        threshold2: int,
        history: PersistentHistory,
        node_budget: int = 10_000,
    ) -> None:
        if not isinstance(rules, Rules):
            raise TypeError("rules must be a Rules instance")
        if rules.superko != "positional_superko":
            raise ValueError(
                "persistent proof-number search requires positional superko"
            )
        if rules.size not in (1, 2):
            raise ValueError(
                "bounded persistent proof-number search supports only 1x1 and 2x2"
            )
        if not isinstance(history, PersistentHistory):
            raise TypeError("history must be a PersistentHistory")
        if history.board_size != rules.size:
            raise ValueError("history board size does not match rules")
        if type(threshold2) is not int:
            raise TypeError("threshold2 must be an integer")
        if type(node_budget) is not int:
            raise TypeError("node_budget must be an integer")
        if node_budget < 1:
            raise ValueError("node_budget must be positive")

        self.rules = rules
        self.threshold2 = threshold2
        self.history = history
        self.node_budget = node_budget
        self.expanded_nodes = 0
        self.generated_nodes = 1
        self.max_ply = 0
        self._last_root: PersistentPNSNode | None = None

    @property
    def last_root(self) -> PersistentPNSNode | None:
        """Return the most recent in-memory tree root for bounded inspection."""

        return self._last_root

    def _initialize(self, node: PersistentPNSNode) -> None:
        if node.state.is_terminal(self.rules):
            if area_score2(node.state.board, self.rules) >= self.threshold2:
                node.proof, node.disproof = 0, INF
            else:
                node.proof, node.disproof = INF, 0
        else:
            node.proof = node.disproof = 1

    def _recompute(self, node: PersistentPNSNode) -> None:
        if not node.expanded or not node.children:
            self._initialize(node)
            return
        if node.is_or:
            node.proof = min(child.proof for child in node.children)
            node.disproof = _sat_add(child.disproof for child in node.children)
        else:
            node.proof = _sat_add(child.proof for child in node.children)
            node.disproof = min(child.disproof for child in node.children)

    def _select_most_proving(
        self, root: PersistentPNSNode
    ) -> PersistentPNSNode:
        node = root
        while node.expanded and node.children and node.proof and node.disproof:
            unresolved = [
                child
                for child in node.children
                if child.proof > 0 and child.disproof > 0
            ]
            if not unresolved:
                raise AssertionError(
                    "an unresolved parent has no unresolved child"
                )
            if node.is_or:
                node = min(
                    unresolved,
                    key=lambda child: (
                        child.proof,
                        child.disproof,
                        child.move if child.move is not None else -2,
                    ),
                )
            else:
                node = min(
                    unresolved,
                    key=lambda child: (
                        child.disproof,
                        child.proof,
                        child.move if child.move is not None else -2,
                    ),
                )
        return node

    def _expand(self, node: PersistentPNSNode) -> None:
        if node.expanded:
            raise AssertionError("most-proving selection returned an expanded node")
        if node.state.is_terminal(self.rules):
            self._initialize(node)
            node.expanded = True
            return

        children: list[PersistentPNSNode] = []
        for move, child_state, _priority in ordered_children(
            node.state, self.rules, self.history
        ):
            child = PersistentPNSNode(state=child_state, parent=node, move=move)
            self._initialize(child)
            children.append(child)
            self.max_ply = max(self.max_ply, child_state.ply)
        node.children = children
        node.expanded = True
        self.expanded_nodes += 1
        self.generated_nodes += len(children)
        self._recompute(node)

    def _update_ancestors(self, node: PersistentPNSNode) -> None:
        current: PersistentPNSNode | None = node
        while current is not None:
            self._recompute(current)
            current = current.parent

    def run(
        self, state: PersistentState | None = None
    ) -> PersistentPNSResult:
        """Run until truth is established or the expansion budget is spent."""

        self.expanded_nodes = 0
        self.generated_nodes = 1
        self.max_ply = 0
        root_state = (
            state if state is not None else initial_state(self.rules, self.history)
        )
        if not isinstance(root_state, PersistentState):
            raise TypeError("state must be a PersistentState")
        root_state.validate(self.rules, self.history)
        root = PersistentPNSNode(state=root_state)
        self._last_root = root
        self._initialize(root)
        start = monotonic()
        root_ply = root.state.ply
        self.max_ply = root_ply

        while (
            root.proof
            and root.disproof
            and self.expanded_nodes < self.node_budget
        ):
            leaf = self._select_most_proving(root)
            self._expand(leaf)
            self._update_ancestors(leaf)

        elapsed = monotonic() - start
        if root.proof == 0:
            status = "PROVEN"
        elif root.disproof == 0:
            status = "DISPROVEN"
        else:
            status = "UNKNOWN"
        return PersistentPNSResult(
            status=status,
            threshold2=self.threshold2,
            proof_number=root.proof,
            disproof_number=root.disproof,
            expanded_nodes=self.expanded_nodes,
            generated_nodes=self.generated_nodes,
            max_ply=self.max_ply - root_ply,
            elapsed_seconds=elapsed,
        )


__all__ = [
    "INF",
    "PROOF_ARITHMETIC",
    "PersistentPNSNode",
    "PersistentPNSResult",
    "PersistentProofNumberSearch",
]
