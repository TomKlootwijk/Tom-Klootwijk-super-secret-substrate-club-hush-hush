"""Symmetry-safe opening-frontier generation."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import PASS
from .engine import ordered_children
from .rules import Rules
from .state import State
from .symmetry import canonical_state_key


@dataclass(frozen=True, slots=True)
class FrontierSummary:
    depth: int
    raw_children: int
    canonical_states: int
    pass_included: bool

    def as_dict(self) -> dict:
        return {
            "depth": self.depth,
            "raw_children": self.raw_children,
            "canonical_states": self.canonical_states,
            "pass_included": self.pass_included,
        }


def canonical_frontier(rules: Rules, depth: int = 1) -> tuple[list[State], FrontierSummary]:
    if depth < 0:
        raise ValueError("depth cannot be negative")
    current = [State.initial(rules)]
    raw_children = 0
    for _ in range(depth):
        next_by_key: dict[tuple, State] = {}
        for state in current:
            for _move, child, _priority in ordered_children(state, rules):
                raw_children += 1
                next_by_key.setdefault(canonical_state_key(child, rules), child)
        current = list(next_by_key.values())
    return current, FrontierSummary(
        depth=depth,
        raw_children=raw_children,
        canonical_states=len(current),
        pass_included=True,
    )
