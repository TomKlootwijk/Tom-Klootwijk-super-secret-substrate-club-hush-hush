"""Collision-free exhaustive alpha-beta reference solver for small boards."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from time import monotonic

from .constants import BLACK, PASS, move_to_coord
from .engine import ordered_children
from .rules import Rules
from .score import area_score2
from .state import State
from .symmetry import canonical_state_key

NEG_INF = -10**9
POS_INF = 10**9


class SearchBudgetExceeded(RuntimeError):
    pass


@dataclass(slots=True)
class SearchStats:
    nodes: int = 0
    terminals: int = 0
    cutoffs: int = 0
    tt_hits: int = 0
    tt_entries: int = 0
    max_ply: int = 0
    elapsed_seconds: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TTEntry:
    value: int
    flag: str  # exact, lower, upper


@dataclass(frozen=True, slots=True)
class ExactResult:
    value2: int
    best_move: int
    principal_variation: tuple[int, ...]
    principal_variation_complete: bool
    stats: SearchStats

    def as_dict(self, rules: Rules) -> dict:
        return {
            "value2": self.value2,
            "value_points": self.value2 / 2.0,
            "winner": "black" if self.value2 > 0 else "white" if self.value2 < 0 else "draw",
            "best_move": self.best_move,
            "best_move_coord": move_to_coord(self.best_move, rules.size),
            "principal_variation": list(self.principal_variation),
            "principal_variation_coords": [
                move_to_coord(move, rules.size) for move in self.principal_variation
            ],
            "principal_variation_complete": self.principal_variation_complete,
            "stats": self.stats.as_dict(),
        }


class ExactSolver:
    """Exhaustive solver with exact history in every transposition key.

    This implementation is deliberately correctness-first. It is suitable for
    regression fixtures and tiny boards, not an unrestricted 19x19 solve.
    """

    def __init__(
        self,
        rules: Rules,
        *,
        node_budget: int | None = None,
        time_budget_seconds: float | None = None,
        use_symmetry: bool = False,
        pass_first: bool = True,
    ) -> None:
        if rules.superko not in {"positional_superko", "situational_superko"}:
            raise ValueError(
                "ExactSolver requires a finite superko profile; infinite-play "
                "utility is undefined for none/simple_ko"
            )
        self.rules = rules
        self.node_budget = node_budget
        self.time_budget_seconds = time_budget_seconds
        self.use_symmetry = use_symmetry
        self.pass_first = pass_first
        self.stats = SearchStats()
        self._tt: dict[tuple, TTEntry] = {}
        self._start = 0.0
        self._root_ply = 0

    def _key(self, state: State) -> tuple:
        if self.use_symmetry:
            return canonical_state_key(state, self.rules)
        return state.exact_key()

    def _check_budget(self) -> None:
        if self.node_budget is not None and self.stats.nodes > self.node_budget:
            raise SearchBudgetExceeded(f"node budget {self.node_budget} exceeded")
        if (
            self.time_budget_seconds is not None
            and monotonic() - self._start > self.time_budget_seconds
        ):
            raise SearchBudgetExceeded(
                f"time budget {self.time_budget_seconds:.3f}s exceeded"
            )

    def _ordered_children(self, state: State) -> list[tuple[int, State, int]]:
        """Return the shared exact children with an optional pass-first baseline.

        A pass is normally last in the engine-wide tactical ordering.  Exploring
        it first in full-width alpha-beta establishes a terminal score quickly,
        which sharply improves pruning on tiny exact games without changing the
        legal child set or any returned value.  Keep an off switch so the
        optimization can be checked differentially.
        """
        children = ordered_children(state, self.rules)
        if self.pass_first and children and children[-1][0] == PASS:
            return children[-1:] + children[:-1]
        return children

    def solve(self, state: State | None = None) -> ExactResult:
        root = state if state is not None else State.initial(self.rules)
        root.validate(self.rules)
        self.stats = SearchStats()
        self._tt.clear()
        self._start = monotonic()
        self._root_ply = root.ply
        value, best_move = self._value(root, NEG_INF, POS_INF)
        pv, pv_complete = self._principal_variation(root)
        self.stats.elapsed_seconds = monotonic() - self._start
        self.stats.tt_entries = len(self._tt)
        return ExactResult(value, best_move, tuple(pv), pv_complete, self.stats)

    def _value(self, state: State, alpha: int, beta: int) -> tuple[int, int]:
        self.stats.nodes += 1
        self.stats.max_ply = max(self.stats.max_ply, state.ply - self._root_ply)
        self._check_budget()

        if state.is_terminal(self.rules):
            self.stats.terminals += 1
            return area_score2(state.board, self.rules), PASS

        key = self._key(state)
        original_alpha, original_beta = alpha, beta
        entry = self._tt.get(key)
        if entry is not None:
            self.stats.tt_hits += 1
            if entry.flag == "exact":
                return entry.value, PASS
            if entry.flag == "lower":
                alpha = max(alpha, entry.value)
            elif entry.flag == "upper":
                beta = min(beta, entry.value)
            if alpha >= beta:
                return entry.value, PASS

        best_move = PASS
        if state.to_play == BLACK:
            best_value = NEG_INF
            for move, child, _priority in self._ordered_children(state):
                child_value, _ = self._value(child, alpha, beta)
                # A fail-soft child can return only a bound equal to the
                # current alpha.  It must not replace the already exact best
                # move on a tie.
                if child_value > best_value:
                    best_value, best_move = child_value, move
                alpha = max(alpha, best_value)
                if alpha >= beta:
                    self.stats.cutoffs += 1
                    break
        else:
            best_value = POS_INF
            for move, child, _priority in self._ordered_children(state):
                child_value, _ = self._value(child, alpha, beta)
                if child_value < best_value:
                    best_value, best_move = child_value, move
                beta = min(beta, best_value)
                if alpha >= beta:
                    self.stats.cutoffs += 1
                    break

        if best_value <= original_alpha:
            flag = "upper"
        elif best_value >= original_beta:
            flag = "lower"
        else:
            flag = "exact"
        self._tt[key] = TTEntry(best_value, flag)
        return best_value, best_move

    def _principal_variation(
        self, root: State, max_length: int = 256
    ) -> tuple[list[int], bool]:
        # Re-search each PV state with a full window. This avoids storing moves in
        # symmetry-canonical TT coordinates and keeps the correctness contract simple.
        pv: list[int] = []
        state = root
        for _ in range(max_length):
            if state.is_terminal(self.rules):
                return pv, True
            best_value = NEG_INF if state.to_play == BLACK else POS_INF
            best_move = PASS
            best_child = None
            try:
                for move, child, _priority in self._ordered_children(state):
                    value, _ = self._value(child, NEG_INF, POS_INF)
                    better = (
                        value > best_value
                        if state.to_play == BLACK
                        else value < best_value
                    )
                    if better or (value == best_value and move < best_move):
                        best_value, best_move, best_child = value, move, child
            except SearchBudgetExceeded:
                return pv, False
            if best_child is None:
                return pv, False
            pv.append(best_move)
            state = best_child
        return pv, state.is_terminal(self.rules)
