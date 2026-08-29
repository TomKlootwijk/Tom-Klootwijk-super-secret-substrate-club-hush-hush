"""Bounded proof-number search for score-threshold propositions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import monotonic

from .constants import BLACK
from .engine import ordered_children
from .rules import Rules
from .score import area_score2
from .state import State

INF = 1 << 60


@dataclass(slots=True)
class PNSNode:
    state: State
    parent: "PNSNode | None" = None
    move: int | None = None
    children: list["PNSNode"] = field(default_factory=list)
    expanded: bool = False
    proof: int = 1
    disproof: int = 1

    @property
    def is_or(self) -> bool:
        # Proposition: Black can force final score2 >= threshold.
        return self.state.to_play == BLACK


@dataclass(slots=True)
class PNSResult:
    status: str
    threshold2: int
    proof_number: int
    disproof_number: int
    expanded_nodes: int
    generated_nodes: int
    max_ply: int
    elapsed_seconds: float

    def as_dict(self) -> dict:
        return asdict(self)


def _sat_add(values: list[int]) -> int:
    total = 0
    for value in values:
        total += value
        if total >= INF:
            return INF
    return total


class ProofNumberSearch:
    """Simple exact PNS kernel with an explicit node budget.

    It is intentionally transparent and has no board-only transposition trick.
    The CUDA/C++ campaign is expected to replace the storage/scheduling layer,
    while preserving these proof-number semantics.
    """

    def __init__(self, rules: Rules, threshold2: int, node_budget: int = 10_000):
        if node_budget < 1:
            raise ValueError("node_budget must be positive")
        if rules.superko not in {"positional_superko", "situational_superko"}:
            raise ValueError(
                "ProofNumberSearch requires a finite superko profile; "
                "infinite-play utility is undefined for none/simple_ko"
            )
        self.rules = rules
        self.threshold2 = threshold2
        self.node_budget = node_budget
        self.expanded_nodes = 0
        self.generated_nodes = 1
        self.max_ply = 0

    def _initialize(self, node: PNSNode) -> None:
        if node.state.is_terminal(self.rules):
            if area_score2(node.state.board, self.rules) >= self.threshold2:
                node.proof, node.disproof = 0, INF
            else:
                node.proof, node.disproof = INF, 0
        else:
            node.proof = node.disproof = 1

    def _recompute(self, node: PNSNode) -> None:
        if not node.expanded or not node.children:
            self._initialize(node)
            return
        if node.is_or:
            node.proof = min(child.proof for child in node.children)
            node.disproof = _sat_add([child.disproof for child in node.children])
        else:
            node.proof = _sat_add([child.proof for child in node.children])
            node.disproof = min(child.disproof for child in node.children)

    def _select_most_proving(self, root: PNSNode) -> PNSNode:
        node = root
        while node.expanded and node.children and node.proof and node.disproof:
            if node.is_or:
                node = min(
                    node.children,
                    key=lambda child: (child.proof, child.disproof, child.move or -1),
                )
            else:
                node = min(
                    node.children,
                    key=lambda child: (child.disproof, child.proof, child.move or -1),
                )
        return node

    def _expand(self, node: PNSNode) -> None:
        if node.state.is_terminal(self.rules):
            self._initialize(node)
            node.expanded = True
            return
        children: list[PNSNode] = []
        for move, child_state, _priority in ordered_children(node.state, self.rules):
            child = PNSNode(state=child_state, parent=node, move=move)
            self._initialize(child)
            children.append(child)
            self.max_ply = max(self.max_ply, child_state.ply)
        node.children = children
        node.expanded = True
        self.expanded_nodes += 1
        self.generated_nodes += len(children)
        self._recompute(node)

    def _update_ancestors(self, node: PNSNode) -> None:
        current: PNSNode | None = node
        while current is not None:
            self._recompute(current)
            current = current.parent

    def run(self, state: State | None = None) -> PNSResult:
        self.expanded_nodes = 0
        self.generated_nodes = 1
        self.max_ply = 0
        root = PNSNode(state=state if state is not None else State.initial(self.rules))
        root.state.validate(self.rules)
        self._initialize(root)
        start = monotonic()
        root_ply = root.state.ply
        self.max_ply = root_ply
        while root.proof and root.disproof and self.expanded_nodes < self.node_budget:
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
        return PNSResult(
            status=status,
            threshold2=self.threshold2,
            proof_number=root.proof,
            disproof_number=root.disproof,
            expanded_nodes=self.expanded_nodes,
            generated_nodes=self.generated_nodes,
            max_ply=self.max_ply - root_ply,
            elapsed_seconds=elapsed,
        )
