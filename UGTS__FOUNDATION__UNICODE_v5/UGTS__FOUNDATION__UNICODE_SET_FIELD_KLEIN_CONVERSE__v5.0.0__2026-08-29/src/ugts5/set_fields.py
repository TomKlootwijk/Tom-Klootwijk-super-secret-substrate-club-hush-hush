"""Signed set-field algebra and finite exact relation kernels.

Sign convention:
    value < 0 : inside the represented set
    value = 0 : declared boundary / indeterminate boundary cell
    value > 0 : outside the represented set

Min/max algebra preserves the set sign for union, intersection, complement,
difference and symmetric difference. A composed value is not automatically an
exact Euclidean distance; callers retain the capability class separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import inf
from typing import Callable, Generic, Hashable, Iterable, Mapping, Sequence, TypeVar

T = TypeVar("T", bound=Hashable)
P = TypeVar("P")


class FieldCapability(str, Enum):
    EXACT_SDF = "exact_sdf"
    METRIC_SIGNED_SET_FIELD = "metric_signed_set_field"
    CONSERVATIVE_DISTANCE_BOUND = "conservative_distance_bound"
    IMPLICIT_SIGNED_RESIDUAL = "implicit_signed_residual"
    SIGNED_MEMBERSHIP_FIELD = "signed_membership_field"
    SYMBOLIC_MEMBERSHIP_ORACLE = "symbolic_membership_oracle"


def union_value(a: float, b: float) -> float:
    return min(a, b)


def intersection_value(a: float, b: float) -> float:
    return max(a, b)


def complement_value(a: float) -> float:
    return -a


def difference_value(a: float, b: float) -> float:
    return max(a, -b)


def symmetric_difference_value(a: float, b: float) -> float:
    return max(min(a, b), -max(a, b))


def inside(value: float, *, boundary_inclusive: bool = True) -> bool:
    return value <= 0.0 if boundary_inclusive else value < 0.0


@dataclass(frozen=True)
class FiniteSetField(Generic[T]):
    """Exact signed characteristic field over a declared finite universe."""

    universe: tuple[T, ...]
    members: frozenset[T]
    capability: FieldCapability = FieldCapability.SIGNED_MEMBERSHIP_FIELD
    label: str = "finite-set"

    def __post_init__(self) -> None:
        universe_set = set(self.universe)
        if len(universe_set) != len(self.universe):
            raise ValueError("universe must not contain duplicates")
        if not self.members.issubset(universe_set):
            missing = sorted(map(repr, self.members.difference(universe_set)))
            raise ValueError(f"members outside universe: {missing}")

    @classmethod
    def from_members(
        cls,
        universe: Iterable[T],
        members: Iterable[T],
        *,
        label: str = "finite-set",
    ) -> "FiniteSetField[T]":
        return cls(tuple(universe), frozenset(members), label=label)

    def value(self, element: T) -> float:
        if element not in set(self.universe):
            raise KeyError(f"element {element!r} not in declared universe")
        return -1.0 if element in self.members else 1.0

    def contains(self, element: T) -> bool:
        return inside(self.value(element))

    def is_empty(self) -> bool:
        return not self.members

    def subset_of(self, other: "FiniteSetField[T]") -> bool:
        self._require_same_universe(other)
        return self.members.issubset(other.members)

    def proper_subset_of(self, other: "FiniteSetField[T]") -> bool:
        self._require_same_universe(other)
        return self.members < other.members

    def equals(self, other: "FiniteSetField[T]") -> bool:
        self._require_same_universe(other)
        return self.members == other.members

    def union(self, other: "FiniteSetField[T]", *, label: str | None = None) -> "FiniteSetField[T]":
        self._require_same_universe(other)
        return FiniteSetField(self.universe, self.members | other.members, label=label or f"({self.label} union {other.label})")

    def intersection(self, other: "FiniteSetField[T]", *, label: str | None = None) -> "FiniteSetField[T]":
        self._require_same_universe(other)
        return FiniteSetField(self.universe, self.members & other.members, label=label or f"({self.label} intersection {other.label})")

    def complement(self, *, label: str | None = None) -> "FiniteSetField[T]":
        return FiniteSetField(self.universe, frozenset(self.universe).difference(self.members), label=label or f"complement({self.label})")

    def difference(self, other: "FiniteSetField[T]", *, label: str | None = None) -> "FiniteSetField[T]":
        self._require_same_universe(other)
        return FiniteSetField(self.universe, self.members - other.members, label=label or f"({self.label} minus {other.label})")

    def symmetric_difference(self, other: "FiniteSetField[T]", *, label: str | None = None) -> "FiniteSetField[T]":
        self._require_same_universe(other)
        return FiniteSetField(self.universe, self.members ^ other.members, label=label or f"({self.label} xor {other.label})")

    def _require_same_universe(self, other: "FiniteSetField[T]") -> None:
        if self.universe != other.universe:
            raise ValueError("finite exact relation requires identical ordered universes")


def metric_signed_set_field(
    point: P,
    set_samples: Sequence[P],
    complement_samples: Sequence[P],
    distance: Callable[[P, P], float],
) -> float:
    """Evaluate d(point,A) - d(point,X\\A) from declared sample supports.

    This is exact only if the provided supports and distance oracle exactly represent the
    declared metric space. For sampled continuous domains it is generally a bounded or
    approximate field and must be labelled accordingly by the caller.
    """

    if not set_samples or not complement_samples:
        raise ValueError("both set and complement supports are required")
    da = min(distance(point, q) for q in set_samples)
    dc = min(distance(point, q) for q in complement_samples)
    return da - dc


def evaluate_relation(literal: str, left: object, right: object) -> bool:
    """Evaluate the implemented set-relation subset of the Unicode atlas.

    Direct and converse spellings share one canonical kernel. `left` and `right`
    must match the surface order of the selected literal.
    """

    if literal in {"∈", "∉"}:
        element, container = left, right
        if not isinstance(container, FiniteSetField):
            raise TypeError("membership requires FiniteSetField as right operand")
        result = container.contains(element)
        return result if literal == "∈" else not result
    if literal in {"∋", "∌"}:
        container, element = left, right
        if not isinstance(container, FiniteSetField):
            raise TypeError("contains-as-member requires FiniteSetField as left operand")
        result = container.contains(element)
        return result if literal == "∋" else not result

    if not isinstance(left, FiniteSetField) or not isinstance(right, FiniteSetField):
        raise TypeError("set inclusion relation requires FiniteSetField operands")

    if literal in {"⊂", "⊊"}:
        return left.proper_subset_of(right)
    if literal in {"⊃", "⊋"}:
        return right.proper_subset_of(left)
    if literal == "⊆":
        return left.subset_of(right)
    if literal == "⊇":
        return right.subset_of(left)
    if literal == "⊄":
        return not left.proper_subset_of(right)
    if literal == "⊅":
        return not right.proper_subset_of(left)
    if literal == "⊈":
        return not left.subset_of(right)
    if literal == "⊉":
        return not right.subset_of(left)
    raise KeyError(f"unsupported relation literal: {literal!r}")


def field_truth_table(a: float, b: float) -> Mapping[str, bool]:
    return {
        "A": inside(a),
        "B": inside(b),
        "union": inside(union_value(a, b)),
        "intersection": inside(intersection_value(a, b)),
        "A_minus_B": inside(difference_value(a, b)),
        "symmetric_difference": inside(symmetric_difference_value(a, b)),
    }
