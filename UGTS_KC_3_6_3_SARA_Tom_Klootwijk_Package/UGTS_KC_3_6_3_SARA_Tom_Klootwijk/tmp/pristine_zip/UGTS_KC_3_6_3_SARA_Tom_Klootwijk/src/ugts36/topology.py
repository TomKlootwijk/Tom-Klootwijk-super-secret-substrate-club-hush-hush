"""Explicit gluing, hinges and dependency-order operations for UGTS-KC 3.6."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Iterable, Mapping, Sequence, TypeVar

from .geometry import Point2

T = TypeVar("T", bound=Hashable)


class DefinitionCycleError(ValueError):
    pass


def topological_order(nodes: Iterable[T], dependencies: Mapping[T, Iterable[T]]) -> tuple[T, ...]:
    """Return a deterministic dependency order or raise on a cycle.

    Dependencies not listed in *nodes* are rejected instead of silently added.
    """

    node_tuple = tuple(nodes)
    node_set = set(node_tuple)
    incoming: dict[T, set[T]] = {node: set(dependencies.get(node, ())) for node in node_tuple}
    unknown = {dep for deps in incoming.values() for dep in deps if dep not in node_set}
    if unknown:
        raise KeyError(f"unknown dependencies: {sorted(map(str, unknown))}")

    ready = sorted((node for node, deps in incoming.items() if not deps), key=str)
    result: list[T] = []
    while ready:
        node = ready.pop(0)
        result.append(node)
        for other in node_tuple:
            if node in incoming[other]:
                incoming[other].remove(node)
                if not incoming[other] and other not in result and other not in ready:
                    ready.append(other)
                    ready.sort(key=str)
    if len(result) != len(node_tuple):
        cyclic = sorted(str(node) for node, deps in incoming.items() if deps)
        raise DefinitionCycleError("definition cycle: " + ", ".join(cyclic))
    return tuple(result)


@dataclass(frozen=True)
class PermutationHinge:
    """A finite ordered-state hinge.

    ``permutation`` maps output positions to input positions.  For example,
    ``(1, 0)`` swaps a two-component place-order tuple.
    """

    permutation: tuple[int, ...]
    connector: str | None = None

    def apply(self, values: Sequence[object]) -> tuple[object, ...]:
        if len(values) != len(self.permutation):
            raise ValueError("permutation length mismatch")
        if sorted(self.permutation) != list(range(len(values))):
            raise ValueError("not a permutation")
        reordered = tuple(values[index] for index in self.permutation)
        if self.connector is None or len(reordered) < 2:
            return reordered
        out: list[object] = [reordered[0]]
        for item in reordered[1:]:
            out.extend((self.connector, item))
        return tuple(out)


@dataclass(frozen=True)
class MobiusQuotient:
    width: float
    height: float

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be positive")

    def map(self, point: Point2, orientation: int = 1) -> tuple[Point2, int]:
        x, y = point
        wraps = int(x // self.width)
        x_wrapped = x % self.width
        if wraps % 2:
            y = self.height - y
            orientation *= -1
        return ((x_wrapped, y % self.height), orientation)


@dataclass(frozen=True)
class KleinQuotient:
    width: float
    height: float

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be positive")

    def map(self, point: Point2, orientation: int = 1, sheet: int = 0) -> tuple[Point2, int, int]:
        x, y = point
        x_wraps = int(x // self.width)
        x_wrapped = x % self.width
        if x_wraps % 2:
            y = self.height - y
            orientation *= -1
            sheet ^= 1
        y_wrapped = y % self.height
        return ((x_wrapped, y_wrapped), orientation, sheet)


def crossing_time_linear(g0: float, g1: float, t0: float, t1: float, epsilon: float = 1e-12) -> float | None:
    """Return a linearly interpolated guard crossing inside [t0,t1]."""

    if t1 <= t0:
        raise ValueError("t1 must be greater than t0")
    if abs(g0) <= epsilon:
        return t0
    if abs(g1) <= epsilon:
        return t1
    if g0 * g1 > 0:
        return None
    alpha = -g0 / (g1 - g0)
    return t0 + alpha * (t1 - t0)


def hourglass_route(x: float, y: float, parity: int = 0) -> str:
    """Four-sector route with an explicit parity-controlled swap."""

    if x >= 0 and y >= 0:
        route = "A"
    elif x < 0 <= y:
        route = "B"
    elif x < 0 and y < 0:
        route = "C"
    else:
        route = "D"
    if parity & 1:
        route = {"A": "C", "C": "A", "B": "D", "D": "B"}[route]
    return route
