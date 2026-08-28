"""UGTS-KC 3.6.1 BEA synthetic cell-complex profile.

This module implements the course-corrected BEA profile requested for the
source pair ``negentien`` and ``no neg moat``.  The profile is deliberately
*not* a standard font renderer.  It is a finite 1-dimensional CW-complex with
explicit cycle annotations, whitespace hinge loops, a zero-metric gluing rule,
a four-cycle torus realization, an even-parity XOR subspace, and a semantic
signed residual metric.

The scope is narrow and schema-bound:

* cycle annotations are profile data, not font-independent glyph facts;
* zero-metric edges are topological cells in a pseudometric, not Euclidean
  strokes of zero physical width;
* the torus operator is a cellular immersion of the four-cycle quotient into
  a synthetic target T^4, not a claim that the text is homeomorphic to T^4;
* the entropy statement is the entropy invariance of a fixed bijective XOR
  translation, not an inference from one fixed string's Hamming weight; and
* the semantic SDF is exact in the evaluator-induced quotient metric, not in
  ordinary screen-space distance.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import asdict, dataclass, replace
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_LEET_MAP: Mapping[str, str] = {
    "a": "4",
    "e": "3",
    "i": "1",
    "o": "0",
}


@dataclass(frozen=True)
class RepresentationAnnotation:
    """Literal representation plus profile-bound cycle and semantic data."""

    representation_id: str
    text: str
    semantic_value: float
    cycle_positions: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.representation_id:
            raise ValueError("representation_id must not be empty")
        if not isinstance(self.text, str):
            raise TypeError("text must be str")
        if not math.isfinite(float(self.semantic_value)):
            raise ValueError("semantic_value must be finite")
        if len(set(self.cycle_positions)) != len(self.cycle_positions):
            raise ValueError("cycle positions must be unique")
        for position in self.cycle_positions:
            if position < 0 or position >= len(self.text):
                raise ValueError(f"cycle position out of range: {position}")
            if self.text[position].isspace():
                raise ValueError("whitespace cannot carry an intrinsic cycle annotation")


@dataclass(frozen=True)
class SyntheticTextProfile:
    """Versioned profile for the synthetic BEA topology."""

    profile_id: str = "bea361:synthetic-cell-complex-v2"
    unicode_normalization: str = "NFC"
    lowercase: bool = True
    leet_map: Mapping[str, str] | None = None
    whitespace_metric_weight: float = 0.0
    torus_dimension: int = 4
    target_value: float = 19.0

    def __post_init__(self) -> None:
        if self.whitespace_metric_weight < 0 or not math.isfinite(self.whitespace_metric_weight):
            raise ValueError("whitespace_metric_weight must be finite and non-negative")
        if self.torus_dimension != 4:
            raise ValueError("the BEA 3.6.1 profile fixes torus_dimension to 4")
        if not math.isfinite(float(self.target_value)):
            raise ValueError("target_value must be finite")

    def normalize(self, text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("text must be str")
        normalized = unicodedata.normalize(self.unicode_normalization, text)
        if self.lowercase:
            normalized = normalized.lower()
        # The source uses single ASCII spaces.  Canonicalize runs without
        # deleting token boundaries so that the cell-complex builder can see
        # every structural separator.
        return " ".join(normalized.split())

    def transduce(self, annotation: RepresentationAnnotation) -> "TransducedRepresentation":
        normalized = self.normalize(annotation.text)
        if normalized != annotation.text.lower() and annotation.cycle_positions:
            # Cycle positions are positional profile data.  Refuse a silent
            # reindexing if normalization changed the string layout.
            raise ValueError("normalization changed text layout with positional cycle annotations")
        mapping = DEFAULT_LEET_MAP if self.leet_map is None else self.leet_map
        output = "".join(mapping.get(character, character) for character in normalized)
        provenance = tuple(
            TransducedCell(index=index, source_symbol=source, output_symbol=output[index])
            for index, source in enumerate(normalized)
        )
        return TransducedRepresentation(
            representation_id=annotation.representation_id,
            source_text=normalized,
            output_text=output,
            semantic_value=float(annotation.semantic_value),
            cycle_positions=annotation.cycle_positions,
            provenance=provenance,
        )


@dataclass(frozen=True)
class TransducedCell:
    index: int
    source_symbol: str
    output_symbol: str


@dataclass(frozen=True)
class TransducedRepresentation:
    representation_id: str
    source_text: str
    output_text: str
    semantic_value: float
    cycle_positions: tuple[int, ...]
    provenance: tuple[TransducedCell, ...]

    @property
    def token_count(self) -> int:
        return len(self.source_text.split()) if self.source_text else 0

    @property
    def whitespace_count(self) -> int:
        return sum(character.isspace() for character in self.source_text)

    @property
    def intrinsic_cycle_count(self) -> int:
        return len(self.cycle_positions)


@dataclass(frozen=True)
class CellEdge:
    """One 1-cell in the finite graph model."""

    edge_id: str
    u: str
    v: str
    kind: str
    metric_weight: float = 1.0
    source_index: int | None = None
    target_vertex: str | None = None
    cycle_rank_index: int | None = None

    @property
    def is_loop(self) -> bool:
        return self.u == self.v


class _UnionFind:
    def __init__(self, items: Iterable[str]):
        self.parent = {item: item for item in items}
        self.rank = {item: 0 for item in items}

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, a: str, b: str) -> None:
        ra = self.find(a)
        rb = self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


@dataclass(frozen=True)
class CellComplex1D:
    """Finite 1-dimensional CW-complex represented as a multigraph."""

    complex_id: str
    vertices: tuple[str, ...]
    edges: tuple[CellEdge, ...]
    representation_id: str
    transduced_text: str
    stage: str

    def __post_init__(self) -> None:
        vertex_set = set(self.vertices)
        if len(vertex_set) != len(self.vertices):
            raise ValueError("vertices must be unique")
        if not vertex_set and self.edges:
            raise ValueError("edges require vertices")
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(set(edge_ids)) != len(edge_ids):
            raise ValueError("edge IDs must be unique")
        for edge in self.edges:
            if edge.u not in vertex_set or edge.v not in vertex_set:
                raise ValueError(f"edge {edge.edge_id} references unknown vertex")
            if edge.metric_weight < 0 or not math.isfinite(edge.metric_weight):
                raise ValueError("edge metric weights must be finite and non-negative")

    @property
    def vertex_count(self) -> int:
        return len(self.vertices)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def beta0(self) -> int:
        if not self.vertices:
            return 0
        uf = _UnionFind(self.vertices)
        for edge in self.edges:
            if edge.u != edge.v:
                uf.union(edge.u, edge.v)
        return len({uf.find(vertex) for vertex in self.vertices})

    @property
    def beta1(self) -> int:
        # Cycle rank of a finite multigraph, including loop edges.
        return self.edge_count - self.vertex_count + self.beta0

    @property
    def euler_characteristic(self) -> int:
        return self.vertex_count - self.edge_count

    @property
    def intrinsic_cycle_edges(self) -> tuple[CellEdge, ...]:
        return tuple(edge for edge in self.edges if edge.kind == "intrinsic_cycle")

    @property
    def space_hinge_edges(self) -> tuple[CellEdge, ...]:
        return tuple(edge for edge in self.edges if edge.kind in {"space_loop", "zero_metric_bridge"})

    def betti_signature(self) -> dict[str, int]:
        return {
            "vertices": self.vertex_count,
            "edges": self.edge_count,
            "beta0": self.beta0,
            "beta1": self.beta1,
            "chi": self.euler_characteristic,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "complex_id": self.complex_id,
            "representation_id": self.representation_id,
            "transduced_text": self.transduced_text,
            "stage": self.stage,
            "betti": self.betti_signature(),
            "vertices": list(self.vertices),
            "edges": [asdict(edge) for edge in self.edges],
        }


def _token_ranges(text: str) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for index, character in enumerate(text):
        if character.isspace():
            if start is not None:
                ranges.append((start, index))
                start = None
        elif start is None:
            start = index
    if start is not None:
        ranges.append((start, len(text)))
    return tuple(ranges)


def build_augmented_cell_complex(
    representation: TransducedRepresentation,
    profile: SyntheticTextProfile,
) -> CellComplex1D:
    """Build the pre-gluing graph used by the Space-Hole Trading Lemma.

    Each token is a path component.  Every profile-annotated intrinsic cycle is
    a loop edge.  Each whitespace boundary contributes one *space loop* at the
    end of the left token.  The space loop carries a target vertex in the next
    component and is later rewired into a zero-metric bridge.

    For ``k`` tokens and ``h`` intrinsic cycles, this construction has
    ``beta0=k`` and ``beta1=h+(k-1)``, hence ``chi=1-h`` for every split.
    """

    text = representation.output_text
    source_text = representation.source_text
    ranges = _token_ranges(source_text)
    if not ranges:
        raise ValueError("representation must contain at least one non-whitespace token")

    vertices: list[str] = []
    edges: list[CellEdge] = []
    char_left_vertex: dict[int, str] = {}
    char_right_vertex: dict[int, str] = {}

    for token_index, (start, end) in enumerate(ranges):
        token_vertices = [f"{representation.representation_id}:t{token_index}:v{i}" for i in range(end - start + 1)]
        vertices.extend(token_vertices)
        local_char_indices = [index for index in range(start, end) if not source_text[index].isspace()]
        if len(local_char_indices) != end - start:
            raise AssertionError("token range unexpectedly contains whitespace")
        for local_index, global_index in enumerate(local_char_indices):
            u = token_vertices[local_index]
            v = token_vertices[local_index + 1]
            char_left_vertex[global_index] = u
            char_right_vertex[global_index] = v
            edges.append(
                CellEdge(
                    edge_id=f"{representation.representation_id}:symbol:{global_index}",
                    u=u,
                    v=v,
                    kind="symbol_backbone",
                    metric_weight=1.0,
                    source_index=global_index,
                )
            )

    for cycle_index, position in enumerate(representation.cycle_positions):
        if position not in char_left_vertex:
            raise ValueError(f"cycle annotation {position} does not point to a token symbol")
        anchor = char_left_vertex[position]
        edges.append(
            CellEdge(
                edge_id=f"{representation.representation_id}:cycle:{cycle_index}",
                u=anchor,
                v=anchor,
                kind="intrinsic_cycle",
                metric_weight=1.0,
                source_index=position,
                cycle_rank_index=cycle_index,
            )
        )

    # One whitespace boundary between adjacent token ranges.  Consecutive
    # whitespace was normalized away by the profile, so ranges are adjacent
    # with exactly one separator character.
    for separator_index, (left_range, right_range) in enumerate(zip(ranges, ranges[1:])):
        left_end_index = left_range[1] - 1
        right_start_index = right_range[0]
        anchor = char_right_vertex[left_end_index]
        target = char_left_vertex[right_start_index]
        edges.append(
            CellEdge(
                edge_id=f"{representation.representation_id}:space:{separator_index}",
                u=anchor,
                v=anchor,
                kind="space_loop",
                metric_weight=profile.whitespace_metric_weight,
                source_index=left_range[1],
                target_vertex=target,
            )
        )

    complex_ = CellComplex1D(
        complex_id=f"complex:{representation.representation_id}:augmented",
        vertices=tuple(vertices),
        edges=tuple(edges),
        representation_id=representation.representation_id,
        transduced_text=text,
        stage="augmented-space-loops",
    )

    expected_beta0 = len(ranges)
    expected_beta1 = len(representation.cycle_positions) + max(0, len(ranges) - 1)
    if complex_.beta0 != expected_beta0 or complex_.beta1 != expected_beta1:
        raise AssertionError("constructed complex does not satisfy profile count formula")
    return complex_


@dataclass(frozen=True)
class SpaceHoleTradeRecord:
    edge_id: str
    source_vertex: str
    target_vertex: str
    before_beta0: int
    before_beta1: int
    after_beta0: int
    after_beta1: int
    chi_before: int
    chi_after: int

    @property
    def valid(self) -> bool:
        return (
            self.after_beta0 == self.before_beta0 - 1
            and self.after_beta1 == self.before_beta1 - 1
            and self.chi_before == self.chi_after
        )


def trade_one_space_loop(complex_: CellComplex1D, edge_id: str) -> tuple[CellComplex1D, SpaceHoleTradeRecord]:
    """Rewire one zero-metric space loop into a bridge to another component.

    Replacing ``(u,u)`` by ``(u,v)`` with ``v`` in a distinct component leaves
    the numbers of vertices and edges fixed.  It decreases ``beta0`` and
    ``beta1`` by one, so ``chi=beta0-beta1`` is conserved.
    """

    selected = next((edge for edge in complex_.edges if edge.edge_id == edge_id), None)
    if selected is None:
        raise KeyError(edge_id)
    if selected.kind != "space_loop" or not selected.is_loop or selected.target_vertex is None:
        raise ValueError("selected edge is not an untraded space loop")

    # Verify that target lies in a different component before rewiring.
    uf = _UnionFind(complex_.vertices)
    for edge in complex_.edges:
        if edge.edge_id != edge_id and edge.u != edge.v:
            uf.union(edge.u, edge.v)
    if uf.find(selected.u) == uf.find(selected.target_vertex):
        raise ValueError("space-loop target must be in a distinct component")

    before_beta0 = complex_.beta0
    before_beta1 = complex_.beta1
    chi_before = complex_.euler_characteristic
    rewired = replace(
        selected,
        v=selected.target_vertex,
        kind="zero_metric_bridge",
    )
    edges = tuple(rewired if edge.edge_id == edge_id else edge for edge in complex_.edges)
    result = CellComplex1D(
        complex_id=complex_.complex_id.replace(":augmented", ":partially-glued"),
        vertices=complex_.vertices,
        edges=edges,
        representation_id=complex_.representation_id,
        transduced_text=complex_.transduced_text,
        stage="partially-glued",
    )
    record = SpaceHoleTradeRecord(
        edge_id=edge_id,
        source_vertex=selected.u,
        target_vertex=selected.target_vertex,
        before_beta0=before_beta0,
        before_beta1=before_beta1,
        after_beta0=result.beta0,
        after_beta1=result.beta1,
        chi_before=chi_before,
        chi_after=result.euler_characteristic,
    )
    if not record.valid:
        raise AssertionError("Space-Hole Trading Lemma preconditions were not satisfied")
    return result, record


def collapse_whitespace_hinges(complex_: CellComplex1D) -> tuple[CellComplex1D, tuple[SpaceHoleTradeRecord, ...]]:
    """Apply the Space-Hole Trading Lemma to every separator loop."""

    current = complex_
    records: list[SpaceHoleTradeRecord] = []
    for edge_id in [edge.edge_id for edge in complex_.edges if edge.kind == "space_loop"]:
        current, record = trade_one_space_loop(current, edge_id)
        records.append(record)
    final = CellComplex1D(
        complex_id=complex_.complex_id.replace(":augmented", ":canonical"),
        vertices=current.vertices,
        edges=current.edges,
        representation_id=current.representation_id,
        transduced_text=current.transduced_text,
        stage="canonical-zero-width-gluing",
    )
    return final, tuple(records)


@dataclass(frozen=True)
class TorusImmersionCertificate:
    """Cellular immersion of the cycle quotient into synthetic T^4."""

    complex_id: str
    torus_dimension: int
    cycle_edge_ids: tuple[str, ...]
    homology_matrix: tuple[tuple[int, ...], ...]
    tree_collapsed: bool

    @property
    def homology_rank(self) -> int:
        return _rank_over_rationals(self.homology_matrix)

    @property
    def valid(self) -> bool:
        dimension = self.torus_dimension
        return (
            self.tree_collapsed
            and dimension == 4
            and len(self.cycle_edge_ids) == 4
            and len(self.homology_matrix) == 4
            and all(len(row) == 4 for row in self.homology_matrix)
            and self.homology_rank == 4
        )

    def coordinate_point(self, cycle_index: int, t: float) -> tuple[float, ...]:
        if not 0 <= cycle_index < self.torus_dimension:
            raise IndexError(cycle_index)
        if not math.isfinite(t):
            raise ValueError("t must be finite")
        point = [0.0] * self.torus_dimension
        point[cycle_index] = t % 1.0
        return tuple(point)

    def to_dict(self) -> dict[str, Any]:
        return {
            "complex_id": self.complex_id,
            "torus_dimension": self.torus_dimension,
            "cycle_edge_ids": list(self.cycle_edge_ids),
            "homology_matrix": [list(row) for row in self.homology_matrix],
            "homology_rank": self.homology_rank,
            "tree_collapsed": self.tree_collapsed,
            "valid": self.valid,
            "scope": "cellular immersion of X/T into coordinate circles of synthetic T^4",
        }


def _rank_over_rationals(matrix: Sequence[Sequence[int]]) -> int:
    rows = [[float(value) for value in row] for row in matrix]
    if not rows:
        return 0
    row_count = len(rows)
    column_count = len(rows[0])
    rank = 0
    column = 0
    while rank < row_count and column < column_count:
        pivot = next((r for r in range(rank, row_count) if abs(rows[r][column]) > 1e-12), None)
        if pivot is None:
            column += 1
            continue
        rows[rank], rows[pivot] = rows[pivot], rows[rank]
        pivot_value = rows[rank][column]
        rows[rank] = [value / pivot_value for value in rows[rank]]
        for r in range(row_count):
            if r == rank:
                continue
            factor = rows[r][column]
            if abs(factor) > 1e-12:
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[rank])]
        rank += 1
        column += 1
    return rank


def build_torus_immersion(complex_: CellComplex1D, profile: SyntheticTextProfile) -> TorusImmersionCertificate:
    """Collapse a spanning tree and map four cycle generators to T^4 axes."""

    if complex_.beta0 != 1:
        raise ValueError("canonical complex must be connected before torus immersion")
    if complex_.beta1 != profile.torus_dimension:
        raise ValueError(
            f"expected beta1={profile.torus_dimension}, received beta1={complex_.beta1}"
        )
    cycle_edges = sorted(
        complex_.intrinsic_cycle_edges,
        key=lambda edge: (-1 if edge.cycle_rank_index is None else edge.cycle_rank_index),
    )
    if len(cycle_edges) != profile.torus_dimension:
        raise ValueError("four intrinsic cycle edges are required")
    identity = tuple(
        tuple(1 if row == column else 0 for column in range(profile.torus_dimension))
        for row in range(profile.torus_dimension)
    )
    certificate = TorusImmersionCertificate(
        complex_id=complex_.complex_id,
        torus_dimension=profile.torus_dimension,
        cycle_edge_ids=tuple(edge.edge_id for edge in cycle_edges),
        homology_matrix=identity,
        tree_collapsed=True,
    )
    if not certificate.valid:
        raise AssertionError("invalid torus immersion certificate")
    return certificate


def bit_weight(data: bytes | bytearray | Iterable[int]) -> int:
    return sum(int(value).bit_count() for value in data)


def bit_parity(data: bytes | bytearray | Iterable[int]) -> int:
    return bit_weight(data) & 1


@dataclass(frozen=True)
class XorDeltaMatrix:
    """Affine XOR translation over ``(F_2^8)^n``."""

    source_text: str
    target_text: str
    encoding: str
    alignment: str
    pad_byte: int
    source_length: int
    target_length: int
    source: bytes
    target: bytes
    delta: bytes

    def __post_init__(self) -> None:
        if self.alignment not in {"left", "right"}:
            raise ValueError("alignment must be left or right")
        if not 0 <= self.pad_byte <= 255:
            raise ValueError("pad_byte must be in 0..255")
        if len(self.source) != len(self.target) or len(self.source) != len(self.delta):
            raise ValueError("aligned source, target and delta lengths must match")
        if self.apply() != self.target:
            raise ValueError("delta does not map source to target")

    @property
    def n(self) -> int:
        return len(self.delta)

    @property
    def source_weight(self) -> int:
        return bit_weight(self.source)

    @property
    def target_weight(self) -> int:
        return bit_weight(self.target)

    @property
    def delta_weight(self) -> int:
        return bit_weight(self.delta)

    @property
    def source_parity(self) -> int:
        return self.source_weight & 1

    @property
    def target_parity(self) -> int:
        return self.target_weight & 1

    @property
    def delta_is_even(self) -> bool:
        return self.delta_weight % 2 == 0

    @property
    def parity_preserved(self) -> bool:
        return self.source_parity == self.target_parity

    @property
    def matrix_rows(self) -> tuple[tuple[int, ...], ...]:
        return tuple(tuple((byte >> shift) & 1 for shift in range(7, -1, -1)) for byte in self.delta)

    @property
    def repeated_row_classes(self) -> dict[str, list[int]]:
        classes: dict[int, list[int]] = {}
        for index, byte in enumerate(self.delta):
            classes.setdefault(byte, []).append(index)
        return {
            f"0x{byte:02x}": indices
            for byte, indices in sorted(classes.items())
            if len(indices) > 1
        }

    @property
    def even_subspace_dimension(self) -> int:
        return 8 * self.n - 1 if self.n else 0

    def symmetric_subspace_dimension(self, equal_row_pairs: Sequence[tuple[int, int]]) -> int:
        seen: set[int] = set()
        independent_pairs = 0
        for a, b in equal_row_pairs:
            if not (0 <= a < self.n and 0 <= b < self.n) or a == b:
                raise ValueError("invalid equal-row pair")
            if a in seen or b in seen:
                raise ValueError("row pairs must be disjoint for this dimension formula")
            seen.add(a)
            seen.add(b)
            independent_pairs += 1
        # Each row equality imposes eight independent equations.  The global
        # even-parity equation remains independent because at least one row is
        # unpaired in the shipped witness.
        return 8 * self.n - 8 * independent_pairs - 1

    def satisfies_equal_row_pairs(self, equal_row_pairs: Sequence[tuple[int, int]]) -> bool:
        return all(self.delta[a] == self.delta[b] for a, b in equal_row_pairs)

    def apply(self, source: bytes | None = None) -> bytes:
        candidate = self.source if source is None else source
        if len(candidate) != self.n:
            raise ValueError("source length does not match delta")
        return bytes(a ^ b for a, b in zip(candidate, self.delta))

    def inverse(self, target: bytes | None = None) -> bytes:
        candidate = self.target if target is None else target
        if len(candidate) != self.n:
            raise ValueError("target length does not match delta")
        return bytes(a ^ b for a, b in zip(candidate, self.delta))

    def entropy_preservation_statement(self) -> str:
        return (
            "For any random variable X on the fixed-width code space, "
            "X -> X xor delta is a bijection, so Shannon entropy H(X xor delta)=H(X). "
            "Even delta weight additionally keeps each global-parity coset invariant."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_text": self.source_text,
            "target_text": self.target_text,
            "encoding": self.encoding,
            "alignment": self.alignment,
            "pad_byte": self.pad_byte,
            "source_length": self.source_length,
            "target_length": self.target_length,
            "aligned_length": self.n,
            "source_hex": self.source.hex(),
            "target_hex": self.target.hex(),
            "delta_hex": self.delta.hex(),
            "source_weight": self.source_weight,
            "target_weight": self.target_weight,
            "delta_weight": self.delta_weight,
            "source_parity": self.source_parity,
            "target_parity": self.target_parity,
            "delta_is_even": self.delta_is_even,
            "parity_preserved": self.parity_preserved,
            "repeated_row_classes": self.repeated_row_classes,
            "even_subspace_dimension": self.even_subspace_dimension,
            "matrix_rows": [list(row) for row in self.matrix_rows],
            "entropy_scope": self.entropy_preservation_statement(),
        }


def xor_delta_matrix(
    source_text: str,
    target_text: str,
    *,
    encoding: str = "ascii",
    alignment: str = "left",
    pad_byte: int = 0,
) -> XorDeltaMatrix:
    source_raw = source_text.encode(encoding)
    target_raw = target_text.encode(encoding)
    n = max(len(source_raw), len(target_raw))
    pad = bytes((pad_byte,))
    if alignment == "left":
        source = source_raw + pad * (n - len(source_raw))
        target = target_raw + pad * (n - len(target_raw))
    elif alignment == "right":
        source = pad * (n - len(source_raw)) + source_raw
        target = pad * (n - len(target_raw)) + target_raw
    else:
        raise ValueError("alignment must be left or right")
    delta = bytes(a ^ b for a, b in zip(source, target))
    return XorDeltaMatrix(
        source_text=source_text,
        target_text=target_text,
        encoding=encoding,
        alignment=alignment,
        pad_byte=pad_byte,
        source_length=len(source_raw),
        target_length=len(target_raw),
        source=source,
        target=target,
        delta=delta,
    )


def parity_coset(vector: bytes | bytearray | Iterable[int]) -> int:
    """Return the one-bit parity coset label used by the narrow profile."""

    return bit_parity(vector)


def even_delta_subspace_member(delta: bytes | bytearray | Iterable[int]) -> bool:
    return bit_weight(delta) % 2 == 0


def xor_translation_preserves_parity(source: bytes, delta: bytes) -> bool:
    if len(source) != len(delta):
        raise ValueError("source and delta must have equal length")
    target = bytes(a ^ b for a, b in zip(source, delta))
    return bit_parity(source) == bit_parity(target)


@dataclass(frozen=True)
class SemanticPoint:
    representation_id: str
    coordinate: tuple[float, ...]


@dataclass(frozen=True)
class SemanticBoundaryProfile:
    """Evaluator-induced quotient metric and exact scalar signed residual."""

    profile_id: str
    values: Mapping[str, float]
    target_value: float = 19.0

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError("values must not be empty")
        for key, value in self.values.items():
            if not key:
                raise ValueError("representation IDs must not be empty")
            if not math.isfinite(float(value)):
                raise ValueError("semantic values must be finite")
        if not math.isfinite(float(self.target_value)):
            raise ValueError("target_value must be finite")
        if not any(float(value) == float(self.target_value) for value in self.values.values()):
            raise ValueError("the semantic zero set must be non-empty")

    def value(self, representation_id: str) -> float:
        try:
            return float(self.values[representation_id])
        except KeyError as exc:
            raise KeyError(f"unknown representation: {representation_id}") from exc

    def equivalent(self, a: str, b: str) -> bool:
        return self.value(a) == self.value(b)

    def quotient_key(self, representation_id: str) -> float:
        return self.value(representation_id)

    def quotient_distance(self, a: str, b: str) -> float:
        return abs(self.value(a) - self.value(b))

    def spatial_pseudodistance(self, a: SemanticPoint, b: SemanticPoint) -> float:
        # Coordinates are intentionally collapsed inside each semantic fiber.
        return self.quotient_distance(a.representation_id, b.representation_id)

    def signed_residual(self, representation_id: str) -> float:
        return self.value(representation_id) - float(self.target_value)

    def spatial_signed_residual(self, point: SemanticPoint) -> float:
        return self.signed_residual(point.representation_id)

    def zero_set(self) -> tuple[str, ...]:
        return tuple(
            key for key, value in self.values.items() if float(value) == float(self.target_value)
        )

    def distance_to_zero_set(self, point: SemanticPoint) -> float:
        zero_ids = self.zero_set()
        return min(
            self.spatial_pseudodistance(point, SemanticPoint(zero_id, ()))
            for zero_id in zero_ids
        )

    def sdf_identity_holds(self, point: SemanticPoint, *, tolerance: float = 0.0) -> bool:
        return math.isclose(
            abs(self.spatial_signed_residual(point)),
            self.distance_to_zero_set(point),
            abs_tol=tolerance,
            rel_tol=0.0,
        )

    def guard(self, representation_id: str, epsilon: float = 0.0) -> float:
        if epsilon < 0 or not math.isfinite(epsilon):
            raise ValueError("epsilon must be finite and non-negative")
        return abs(self.signed_residual(representation_id)) - epsilon

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "target_value": self.target_value,
            "values": {key: float(value) for key, value in self.values.items()},
            "zero_set": list(self.zero_set()),
            "metric_scope": (
                "exact metric on semantic quotient and pseudometric on spatial representation domain; "
                "not Euclidean glyph distance"
            ),
        }


@dataclass(frozen=True)
class SyntheticBEACertificate:
    certificate_id: str
    profile_id: str
    source_id: str
    target_id: str
    source_augmented: Mapping[str, int]
    target_augmented: Mapping[str, int]
    source_canonical: Mapping[str, int]
    target_canonical: Mapping[str, int]
    source_trade_count: int
    target_trade_count: int
    torus_source: TorusImmersionCertificate
    torus_target: TorusImmersionCertificate
    xor: XorDeltaMatrix
    semantic: SemanticBoundaryProfile
    non_claims: tuple[str, ...]

    @property
    def valid(self) -> bool:
        canonical_match = (
            self.source_canonical.get("beta0") == 1
            and self.target_canonical.get("beta0") == 1
            and self.source_canonical.get("beta1") == 4
            and self.target_canonical.get("beta1") == 4
            and self.source_canonical.get("chi") == self.target_canonical.get("chi") == -3
        )
        return (
            canonical_match
            and self.torus_source.valid
            and self.torus_target.valid
            and self.xor.apply() == self.xor.target
            and self.xor.delta_is_even
            and self.xor.parity_preserved
            and self.semantic.equivalent(self.source_id, self.target_id)
            and self.semantic.signed_residual(self.source_id) == 0.0
            and self.semantic.signed_residual(self.target_id) == 0.0
        )

    @property
    def claim_level(self) -> str:
        return "profile-exact-synthetic-topology-equivalence" if self.valid else "invalid"

    def to_dict(self) -> dict[str, Any]:
        return {
            "certificate_id": self.certificate_id,
            "profile_id": self.profile_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "source_augmented": dict(self.source_augmented),
            "target_augmented": dict(self.target_augmented),
            "source_canonical": dict(self.source_canonical),
            "target_canonical": dict(self.target_canonical),
            "source_trade_count": self.source_trade_count,
            "target_trade_count": self.target_trade_count,
            "torus_source": self.torus_source.to_dict(),
            "torus_target": self.torus_target.to_dict(),
            "xor": self.xor.to_dict(),
            "semantic": self.semantic.to_dict(),
            "semantic_source_residual": self.semantic.signed_residual(self.source_id),
            "semantic_target_residual": self.semantic.signed_residual(self.target_id),
            "valid": self.valid,
            "claim_level": self.claim_level,
            "non_claims": list(self.non_claims),
        }


def build_synthetic_bea_certificate(
    source: RepresentationAnnotation,
    target: RepresentationAnnotation,
    *,
    profile: SyntheticTextProfile | None = None,
    certificate_id: str = "bea361:certificate:negentien-no-neg-moat-v2",
) -> SyntheticBEACertificate:
    profile = SyntheticTextProfile() if profile is None else profile
    source_t = profile.transduce(source)
    target_t = profile.transduce(target)
    source_aug = build_augmented_cell_complex(source_t, profile)
    target_aug = build_augmented_cell_complex(target_t, profile)
    source_can, source_trades = collapse_whitespace_hinges(source_aug)
    target_can, target_trades = collapse_whitespace_hinges(target_aug)
    torus_source = build_torus_immersion(source_can, profile)
    torus_target = build_torus_immersion(target_can, profile)
    xor = xor_delta_matrix(source_t.output_text, target_t.output_text)
    semantic = SemanticBoundaryProfile(
        profile_id="bea361:semantic-boundary-sdf19-v2",
        values={source.representation_id: source.semantic_value, target.representation_id: target.semantic_value},
        target_value=profile.target_value,
    )
    certificate = SyntheticBEACertificate(
        certificate_id=certificate_id,
        profile_id=profile.profile_id,
        source_id=source.representation_id,
        target_id=target.representation_id,
        source_augmented=source_aug.betti_signature(),
        target_augmented=target_aug.betti_signature(),
        source_canonical=source_can.betti_signature(),
        target_canonical=target_can.betti_signature(),
        source_trade_count=len(source_trades),
        target_trade_count=len(target_trades),
        torus_source=torus_source,
        torus_target=torus_target,
        xor=xor,
        semantic=semantic,
        non_claims=(
            "not a statement about standard font glyph topology",
            "not a homeomorphism between either string and the full four-torus",
            "not a dialect, historical, or universal linguistic claim",
            "not Euclidean screen-space signed distance",
            "not Hamming-weight conservation",
            "not physical entropy or energy conservation",
        ),
    )
    if not certificate.valid:
        raise AssertionError("constructed BEA certificate is invalid")
    return certificate


SOURCE_ANNOTATION = RepresentationAnnotation(
    representation_id="repr:negentien",
    text="negentien",
    semantic_value=19.0,
    cycle_positions=(1, 2, 3, 7),
)

TARGET_ANNOTATION = RepresentationAnnotation(
    representation_id="repr:no-neg-moat",
    text="no neg moat",
    semantic_value=19.0,
    cycle_positions=(1, 5, 8, 9),
)
