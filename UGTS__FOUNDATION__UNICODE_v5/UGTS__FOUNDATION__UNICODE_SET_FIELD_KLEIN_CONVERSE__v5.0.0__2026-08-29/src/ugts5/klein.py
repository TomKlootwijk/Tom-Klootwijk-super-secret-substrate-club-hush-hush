"""Klein-converse involution over Unicode relation cells."""

from __future__ import annotations

from dataclasses import dataclass
from math import pi
from typing import Any

CONVERSE: dict[str, str] = {
    "∈": "∋", "∋": "∈",
    "∉": "∌", "∌": "∉",
    "⊂": "⊃", "⊃": "⊂",
    "⊆": "⊇", "⊇": "⊆",
    "⊄": "⊅", "⊅": "⊄",
    "⊈": "⊉", "⊉": "⊈",
    "⊊": "⊋", "⊋": "⊊",
}


@dataclass(frozen=True)
class KleinState:
    literal: str
    left: Any
    right: Any
    theta: float
    kappa: int
    orientation: int = 1
    winding: int = 0

    def __post_init__(self) -> None:
        if self.kappa not in (0, 1):
            raise ValueError("kappa must be 0 or 1")
        if self.orientation not in (-1, 1):
            raise ValueError("orientation must be -1 or +1")


def reflect_theta(theta: float) -> float:
    return (pi - theta) % (2.0 * pi)


def reflect_theta8(theta_code: int) -> int:
    if not 0 <= theta_code <= 255:
        raise ValueError("theta_code must be in [0,255]")
    return (128 - theta_code) & 0xFF


def reflect_delta_theta8(delta_code: int) -> int:
    if not 0 <= delta_code <= 255:
        raise ValueError("delta_code must be in [0,255]")
    return (-delta_code) & 0xFF


def apply_klein_converse(state: KleinState) -> KleinState:
    try:
        converse = CONVERSE[state.literal]
    except KeyError as exc:
        raise KeyError(f"literal {state.literal!r} has no registered converse") from exc
    return KleinState(
        literal=converse,
        left=state.right,
        right=state.left,
        theta=reflect_theta(state.theta),
        kappa=state.kappa ^ 1,
        orientation=-state.orientation,
        winding=state.winding + 1,
    )
