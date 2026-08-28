"""Discrete topology, basic homology and bounded persistence helpers."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import atan2, pi
from typing import Dict, Iterable, List, Mapping, MutableMapping, Sequence, Set, Tuple

from .math3 import cross, distance, dot, norm, sub

Simplex = Tuple[int, ...]


def winding_number(path: Sequence[Sequence[float]], point: Sequence[float] = (0.0, 0.0)) -> int:
    if len(point) != 2 or len(path) < 3 or any(len(p) != 2 for p in path):
        raise ValueError("winding_number requires a planar closed path with at least three points")
    total = 0.0
    for i in range(len(path)):
        a = (path[i][0] - point[0], path[i][1] - point[1])
        b = (path[(i + 1) % len(path)][0] - point[0], path[(i + 1) % len(path)][1] - point[1])
        total += atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1])
    return int(round(total / (2.0 * pi)))


def lift_periodic(value: float, period: float) -> Tuple[float, int]:
    if period <= 0.0:
        raise ValueError("period must be positive")
    sheet = int(value // period)
    wrapped = value - sheet * period
    if wrapped < 0.0:
        wrapped += period
        sheet -= 1
    if wrapped >= period:
        wrapped -= period
        sheet += 1
    return wrapped, sheet


def _inverse_token(token: str) -> str:
    if token.startswith("-"):
        return token[1:]
    if token.endswith("^-1"):
        return token[:-3]
    if len(token) == 1 and token.isalpha():
        return token.swapcase()
    return "-" + token


def reduce_word(tokens: Sequence[str]) -> Tuple[str, ...]:
    stack: List[str] = []
    for token in tokens:
        if stack and _inverse_token(token) == stack[-1]:
            stack.pop()
        else:
            stack.append(token)
    return tuple(stack)


def oriented_boundary(simplex: Sequence[int]) -> List[Tuple[int, Simplex]]:
    if len(simplex) < 2 or len(set(simplex)) != len(simplex):
        raise ValueError("simplex must contain distinct vertices and dimension at least 1")
    s = tuple(simplex)
    return [((-1) ** i, s[:i] + s[i + 1 :]) for i in range(len(s))]


@dataclass
class SimplicialComplex:
    simplices: Set[Simplex]

    def __init__(self, simplices: Iterable[Sequence[int]] = ()) -> None:
        self.simplices = set()
        for simplex in simplices:
            self.add(simplex)

    def add(self, simplex: Sequence[int]) -> None:
        if not simplex or len(set(simplex)) != len(simplex):
            raise ValueError("simplex must contain distinct vertices")
        s = tuple(sorted(int(v) for v in simplex))
        for k in range(1, len(s) + 1):
            for face in combinations(s, k):
                self.simplices.add(tuple(face))

    @property
    def max_dimension(self) -> int:
        return max((len(s) - 1 for s in self.simplices), default=-1)

    def by_dimension(self, dimension: int) -> List[Simplex]:
        return sorted(s for s in self.simplices if len(s) == dimension + 1)


def boundary_matrix(complex_: SimplicialComplex, dimension: int, mod2: bool = True) -> List[List[int]]:
    if dimension < 1:
        return []
    cols = complex_.by_dimension(dimension)
    rows = complex_.by_dimension(dimension - 1)
    row_index = {s: i for i, s in enumerate(rows)}
    matrix = [[0 for _ in cols] for _ in rows]
    for j, simplex in enumerate(cols):
        for sign, face in oriented_boundary(simplex):
            i = row_index[tuple(sorted(face))]
            matrix[i][j] = 1 if mod2 else sign
    return matrix


def boundary_squared_zero(complex_: SimplicialComplex) -> bool:
    for k in range(2, complex_.max_dimension + 1):
        b_k = boundary_matrix(complex_, k, mod2=False)
        b_km1 = boundary_matrix(complex_, k - 1, mod2=False)
        if not b_k or not b_km1:
            continue
        product = [[sum(b_km1[i][m] * b_k[m][j] for m in range(len(b_k))) for j in range(len(b_k[0]))] for i in range(len(b_km1))]
        if any(value != 0 for row in product for value in row):
            return False
    return True


def rank_mod2(matrix: Sequence[Sequence[int]]) -> int:
    if not matrix:
        return 0
    a = [[int(v) & 1 for v in row] for row in matrix]
    rows, cols = len(a), len(a[0])
    if any(len(row) != cols for row in a):
        raise ValueError("ragged matrix")
    rank = 0
    col = 0
    while rank < rows and col < cols:
        pivot = next((r for r in range(rank, rows) if a[r][col]), None)
        if pivot is None:
            col += 1
            continue
        a[rank], a[pivot] = a[pivot], a[rank]
        for r in range(rows):
            if r != rank and a[r][col]:
                a[r] = [x ^ y for x, y in zip(a[r], a[rank])]
        rank += 1
        col += 1
    return rank


def betti_numbers(complex_: SimplicialComplex) -> Tuple[int, ...]:
    maxdim = complex_.max_dimension
    if maxdim < 0:
        return tuple()
    ranks = {k: rank_mod2(boundary_matrix(complex_, k, mod2=True)) for k in range(1, maxdim + 2)}
    betti = []
    for k in range(maxdim + 1):
        n_k = len(complex_.by_dimension(k))
        rank_bk = ranks.get(k, 0)
        rank_bkp1 = ranks.get(k + 1, 0)
        betti.append(n_k - rank_bk - rank_bkp1)
    return tuple(betti)


def euler_characteristic(complex_: SimplicialComplex) -> int:
    return sum(((-1) ** d) * len(complex_.by_dimension(d)) for d in range(complex_.max_dimension + 1))


class UnionFind:
    def __init__(self, items: Iterable[int]):
        self.parent = {i: i for i in items}
        self.rank = {i: 0 for i in self.parent}

    def find(self, x: int) -> int:
        p = self.parent[x]
        if p != x:
            self.parent[x] = self.find(p)
        return self.parent[x]

    def union(self, a: int, b: int, preferred_root: int | None = None) -> int:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return ra
        if preferred_root is not None:
            if preferred_root not in (ra, rb):
                raise ValueError("preferred_root must be one of the current roots")
            other = rb if preferred_root == ra else ra
            self.parent[other] = preferred_root
            return preferred_root
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1
        return ra


@dataclass(frozen=True)
class PersistenceInterval:
    birth: float
    death: float | None
    dimension: int = 0
    representative: str | None = None
    confidence: float = 1.0

    @property
    def lifetime(self) -> float:
        return float("inf") if self.death is None else self.death - self.birth


def persistence_h0(vertex_births: Mapping[int, float], edges: Sequence[Tuple[int, int, float]]) -> List[PersistenceInterval]:
    vertices = sorted(vertex_births)
    uf = UnionFind(vertices)
    root_birth = {v: float(vertex_births[v]) for v in vertices}
    root_rep = {v: v for v in vertices}
    intervals: List[PersistenceInterval] = []
    for u, v, time in sorted(edges, key=lambda e: (e[2], min(e[0], e[1]), max(e[0], e[1]))):
        if u not in uf.parent or v not in uf.parent:
            raise ValueError("edge references unknown vertex")
        ru, rv = uf.find(u), uf.find(v)
        if ru == rv:
            continue
        bu, bv = root_birth[ru], root_birth[rv]
        # Elder rule: lower birth survives; tie breaks by representative ID.
        survive, die = (ru, rv) if (bu, root_rep[ru]) <= (bv, root_rep[rv]) else (rv, ru)
        intervals.append(PersistenceInterval(root_birth[die], float(time), 0, str(root_rep[die])))
        newroot = uf.union(ru, rv, preferred_root=survive)
        root_birth[newroot] = root_birth[survive]
        root_rep[newroot] = root_rep[survive]
    roots = sorted({uf.find(v) for v in vertices}, key=lambda r: (root_birth[r], root_rep[r]))
    intervals.extend(PersistenceInterval(root_birth[r], None, 0, str(root_rep[r])) for r in roots)
    return sorted(intervals, key=lambda x: (x.birth, float("inf") if x.death is None else x.death, x.representative or ""))


def _interval_point_distance(a: PersistenceInterval, b: PersistenceInterval, cap: float) -> float:
    da = cap if a.death is None else a.death
    db = cap if b.death is None else b.death
    return max(abs(a.birth - b.birth), abs(da - db))


def greedy_diagram_distance(a: Sequence[PersistenceInterval], b: Sequence[PersistenceInterval]) -> float:
    if not a and not b:
        return 0.0
    finite_deaths = [x.death for x in list(a) + list(b) if x.death is not None]
    cap = (max(finite_deaths) if finite_deaths else 0.0) + 1.0
    remaining = list(b)
    worst = 0.0
    for item in sorted(a, key=lambda x: (x.dimension, x.birth, x.death is None)):
        candidates = [x for x in remaining if x.dimension == item.dimension]
        if not candidates:
            death = cap if item.death is None else item.death
            worst = max(worst, 0.5 * abs(death - item.birth))
            continue
        match = min(candidates, key=lambda x: _interval_point_distance(item, x, cap))
        worst = max(worst, _interval_point_distance(item, match, cap))
        remaining.remove(match)
    for item in remaining:
        death = cap if item.death is None else item.death
        worst = max(worst, 0.5 * abs(death - item.birth))
    return worst


def vietoris_rips_complex(points: Sequence[Sequence[float]], epsilon: float, max_dimension: int = 2) -> SimplicialComplex:
    if epsilon < 0.0 or max_dimension < 0:
        raise ValueError("invalid Rips parameters")
    n = len(points)
    complex_ = SimplicialComplex((i,) for i in range(n))
    edges = set()
    for i, j in combinations(range(n), 2):
        if distance(points[i], points[j]) <= epsilon:
            complex_.add((i, j)); edges.add((i, j))
    if max_dimension >= 2:
        for i, j, k in combinations(range(n), 3):
            if all(tuple(sorted(e)) in edges for e in ((i, j), (i, k), (j, k))):
                complex_.add((i, j, k))
    return complex_


def cubical_lower_star_order(values: Sequence[Sequence[float]]) -> List[Dict[str, object]]:
    if not values or not values[0] or any(len(row) != len(values[0]) for row in values):
        raise ValueError("rectangular nonempty grid required")
    rows, cols = len(values), len(values[0])
    cells: List[Dict[str, object]] = []
    for i in range(rows):
        for j in range(cols):
            cells.append({"dimension": 0, "vertices": ((i, j),), "value": float(values[i][j])})
    for i in range(rows):
        for j in range(cols - 1):
            verts = ((i, j), (i, j + 1))
            cells.append({"dimension": 1, "vertices": verts, "value": max(values[i][j], values[i][j + 1])})
    for i in range(rows - 1):
        for j in range(cols):
            verts = ((i, j), (i + 1, j))
            cells.append({"dimension": 1, "vertices": verts, "value": max(values[i][j], values[i + 1][j])})
    for i in range(rows - 1):
        for j in range(cols - 1):
            verts = ((i, j), (i, j + 1), (i + 1, j), (i + 1, j + 1))
            cells.append({"dimension": 2, "vertices": verts, "value": max(values[a][b] for a, b in verts)})
    cells.sort(key=lambda c: (float(c["value"]), int(c["dimension"]), c["vertices"]))
    return cells


def hodge_laplacian_0(vertex_count: int, edges: Sequence[Tuple[int, int]]) -> List[List[float]]:
    if vertex_count < 0:
        raise ValueError("vertex_count must be nonnegative")
    l = [[0.0 for _ in range(vertex_count)] for _ in range(vertex_count)]
    for u, v in edges:
        if not (0 <= u < vertex_count and 0 <= v < vertex_count) or u == v:
            raise ValueError("invalid edge")
        l[u][u] += 1.0; l[v][v] += 1.0
        l[u][v] -= 1.0; l[v][u] -= 1.0
    return l


def gauss_linking_number(curve_a: Sequence[Sequence[float]], curve_b: Sequence[Sequence[float]], eps: float = 1e-12) -> float:
    if len(curve_a) < 3 or len(curve_b) < 3 or any(len(p) != 3 for p in list(curve_a) + list(curve_b)):
        raise ValueError("closed 3D polylines required")
    total = 0.0
    for i in range(len(curve_a)):
        a0, a1 = curve_a[i], curve_a[(i + 1) % len(curve_a)]
        da = sub(a1, a0)
        ma = tuple((a0[k] + a1[k]) * 0.5 for k in range(3))
        for j in range(len(curve_b)):
            b0, b1 = curve_b[j], curve_b[(j + 1) % len(curve_b)]
            db = sub(b1, b0)
            mb = tuple((b0[k] + b1[k]) * 0.5 for k in range(3))
            r = sub(ma, mb)
            rn = norm(r)
            if rn <= eps:
                raise ValueError("curves intersect or are too close for linking estimate")
            total += dot(r, cross(da, db)) / (rn**3)
    return total / (4.0 * pi)


@dataclass(frozen=True)
class GroupPresentation:
    generators: Tuple[str, ...]
    relations: Tuple[Tuple[str, ...], ...] = tuple()

    def __post_init__(self) -> None:
        if len(set(self.generators)) != len(self.generators):
            raise ValueError("generators must be unique")

    def reduce(self, word: Sequence[str], max_passes: int = 32) -> Tuple[str, ...]:
        current = reduce_word(word)
        relation_set = {tuple(r) for r in self.relations}
        relation_set |= {tuple(reversed([_inverse_token(x) for x in r])) for r in self.relations}
        for _ in range(max_passes):
            changed = False
            for relation in sorted(relation_set, key=len, reverse=True):
                n = len(relation)
                for i in range(len(current) - n + 1):
                    if tuple(current[i : i + n]) == relation:
                        current = reduce_word(current[:i] + current[i + n :])
                        changed = True
                        break
                if changed:
                    break
            if not changed:
                return current
        return current


def apply_monodromy(sheet: int, loop_generators: Sequence[str], permutations: Mapping[str, Sequence[int]]) -> int:
    current = sheet
    for generator in loop_generators:
        inverse = generator.startswith("-") or generator.endswith("^-1") or (len(generator) == 1 and generator.isupper())
        base = generator[1:] if generator.startswith("-") else generator[:-3] if generator.endswith("^-1") else generator.lower() if len(generator) == 1 else generator
        if base not in permutations:
            raise ValueError(f"missing permutation for generator {base}")
        perm = list(permutations[base])
        if not 0 <= current < len(perm) or sorted(perm) != list(range(len(perm))):
            raise ValueError("invalid sheet or permutation")
        if inverse:
            inv = [0] * len(perm)
            for i, p in enumerate(perm):
                inv[p] = i
            current = inv[current]
        else:
            current = perm[current]
    return current


def persistence_threshold_events(intervals: Sequence[PersistenceInterval], min_lifetime: float,
                                 dimension: int | None = None) -> List[Dict[str, object]]:
    if min_lifetime < 0.0:
        raise ValueError("min_lifetime must be nonnegative")
    events = []
    for interval in intervals:
        if dimension is not None and interval.dimension != dimension:
            continue
        if interval.death is not None and interval.lifetime >= min_lifetime:
            events.append({
                "type": "persistence_threshold",
                "dimension": interval.dimension,
                "birth": interval.birth,
                "death": interval.death,
                "lifetime": interval.lifetime,
                "representative": interval.representative,
                "confidence": interval.confidence,
            })
    return events
