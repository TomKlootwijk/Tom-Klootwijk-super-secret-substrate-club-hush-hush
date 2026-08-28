"""Multiscale, symmetry, sampling and spatial-index patterns."""
from __future__ import annotations

from itertools import combinations
from math import floor, sqrt
import random
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from .math3 import Vec2, distance
from .topology import SimplicialComplex


def wallpaper_p4m_transforms(point: Vec2, translations: int = 1) -> List[Vec2]:
    if translations < 0:
        raise ValueError("translations must be nonnegative")
    x, y = point
    d4 = [
        (x, y), (-y, x), (-x, -y), (y, -x),
        (-x, y), (x, -y), (y, x), (-y, -x),
    ]
    out: Set[Vec2] = set()
    for i in range(-translations, translations + 1):
        for j in range(-translations, translations + 1):
            for a, b in d4:
                out.add((a + i, b + j))
    return sorted(out)


def frieze_p11g_transforms(point: Vec2, periods: int = 2, period: float = 1.0) -> List[Vec2]:
    if periods < 0 or period <= 0.0:
        raise ValueError("invalid frieze parameters")
    x, y = point
    out: Set[Vec2] = set()
    for k in range(-periods, periods + 1):
        out.add((x + k * period, y))
        out.add((x + (k + 0.5) * period, -y))
    return sorted(out)


def penrose_count_substitution(depth: int, thick: int = 1, thin: int = 0, max_symbols: int = 1_000_000) -> Tuple[int, int]:
    """Bounded count-only Penrose rhomb substitution proxy.

    The count matrix is thick -> 2 thick + thin and thin -> thick + thin.
    Geometry and matching rules are intentionally outside this compact oracle.
    """
    if depth < 0 or thick < 0 or thin < 0 or max_symbols < 1:
        raise ValueError("invalid substitution parameters")
    for _ in range(depth):
        thick, thin = 2 * thick + thin, thick + thin
        if thick + thin > max_symbols:
            raise OverflowError("symbol budget exceeded")
    return thick, thin


def ammann_beenker_counts(depth: int, square: int = 1, rhomb: int = 0, max_symbols: int = 1_000_000) -> Tuple[int, int]:
    """Bounded count proxy using square -> square+2 rhombs; rhomb -> square+rhomb."""
    if depth < 0 or square < 0 or rhomb < 0 or max_symbols < 1:
        raise ValueError("invalid substitution parameters")
    for _ in range(depth):
        square, rhomb = square + rhomb, 2 * square + rhomb
        if square + rhomb > max_symbols:
            raise OverflowError("symbol budget exceeded")
    return square, rhomb


def cut_and_project_1d(index_radius: int, acceptance_half_width: float = 0.5) -> List[float]:
    if index_radius < 0 or acceptance_half_width < 0.0:
        raise ValueError("invalid cut-and-project parameters")
    phi = (1.0 + sqrt(5.0)) / 2.0
    phi_conjugate = (1.0 - sqrt(5.0)) / 2.0
    points = set()
    for m in range(-index_radius, index_radius + 1):
        for n in range(-index_radius, index_radius + 1):
            internal = m + n * phi_conjugate
            if abs(internal) <= acceptance_half_width:
                points.add(m + n * phi)
    return sorted(points)


def voronoi_label(point: Sequence[float], seeds: Sequence[Sequence[float]]) -> int:
    if not seeds or any(len(s) != len(point) for s in seeds):
        raise ValueError("nonempty consistent seeds required")
    return min(range(len(seeds)), key=lambda i: (distance(point, seeds[i]), i))


def _circumcircle(a: Vec2, b: Vec2, c: Vec2, eps: float = 1e-12) -> Tuple[Vec2, float] | None:
    ax, ay = a; bx, by = b; cx, cy = c
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) <= eps:
        return None
    aa = ax * ax + ay * ay; bb = bx * bx + by * by; cc = cx * cx + cy * cy
    ux = (aa * (by - cy) + bb * (cy - ay) + cc * (ay - by)) / d
    uy = (aa * (cx - bx) + bb * (ax - cx) + cc * (bx - ax)) / d
    center = (ux, uy)
    return center, distance(center, a)


def delaunay_triangles_2d(points: Sequence[Vec2], eps: float = 1e-10) -> List[Tuple[int, int, int]]:
    n = len(points)
    triangles = []
    for i, j, k in combinations(range(n), 3):
        circle = _circumcircle(points[i], points[j], points[k])
        if circle is None:
            continue
        center, radius = circle
        if all(distance(center, points[m]) >= radius - eps for m in range(n) if m not in (i, j, k)):
            triangles.append((i, j, k))
    return triangles


def delaunay_edges_2d(points: Sequence[Vec2]) -> List[Tuple[int, int]]:
    if len(points) < 2:
        return []
    if len(points) == 2:
        return [(0, 1)]
    edges: Set[Tuple[int, int]] = set()
    for tri in delaunay_triangles_2d(points):
        for u, v in combinations(tri, 2):
            edges.add(tuple(sorted((u, v))))
    if not edges:
        # Collinear fallback: connect nearest neighbors along x/y order.
        order = sorted(range(len(points)), key=lambda i: (points[i][0], points[i][1], i))
        edges.update(tuple(sorted((order[i], order[i + 1]))) for i in range(len(order) - 1))
    return sorted(edges)


def alpha_complex_proxy_2d(points: Sequence[Vec2], alpha: float) -> SimplicialComplex:
    if alpha < 0.0:
        raise ValueError("alpha must be nonnegative")
    complex_ = SimplicialComplex((i,) for i in range(len(points)))
    for i, j in delaunay_edges_2d(points):
        if 0.5 * distance(points[i], points[j]) <= alpha:
            complex_.add((i, j))
    for tri in delaunay_triangles_2d(points):
        circle = _circumcircle(points[tri[0]], points[tri[1]], points[tri[2]])
        if circle is not None and circle[1] <= alpha:
            complex_.add(tri)
    return complex_


def lloyd_step_samples(seeds: Sequence[Vec2], samples: Sequence[Vec2], relaxation: float = 1.0) -> List[Vec2]:
    if not seeds or not 0.0 <= relaxation <= 1.0:
        raise ValueError("nonempty seeds and relaxation in [0,1] required")
    buckets: List[List[Vec2]] = [[] for _ in seeds]
    for p in samples:
        buckets[voronoi_label(p, seeds)].append(p)
    out = []
    for seed, bucket in zip(seeds, buckets):
        if not bucket:
            out.append(seed)
            continue
        centroid = (sum(p[0] for p in bucket) / len(bucket), sum(p[1] for p in bucket) / len(bucket))
        out.append(((1.0 - relaxation) * seed[0] + relaxation * centroid[0],
                    (1.0 - relaxation) * seed[1] + relaxation * centroid[1]))
    return out


def poisson_disk_2d(width: float, height: float, radius: float, seed: int = 0, attempts: int = 30) -> List[Vec2]:
    if width <= 0.0 or height <= 0.0 or radius <= 0.0 or attempts < 1:
        raise ValueError("invalid Poisson-disk parameters")
    rng = random.Random(seed)
    cell = radius / sqrt(2.0)
    gw, gh = int(width / cell) + 1, int(height / cell) + 1
    grid: List[int | None] = [None] * (gw * gh)
    points: List[Vec2] = []
    active: List[int] = []

    def grid_index(p: Vec2) -> Tuple[int, int]:
        return min(gw - 1, int(p[0] / cell)), min(gh - 1, int(p[1] / cell))

    def insert(p: Vec2) -> None:
        idx = len(points); points.append(p); active.append(idx)
        gx, gy = grid_index(p); grid[gy * gw + gx] = idx

    insert((rng.random() * width, rng.random() * height))
    while active:
        ai = rng.randrange(len(active))
        base_index = active[ai]
        base = points[base_index]
        found = False
        for _ in range(attempts):
            angle = rng.random() * 6.283185307179586
            rr = radius * (1.0 + rng.random())
            from math import cos, sin
            candidate = (base[0] + rr * cos(angle), base[1] + rr * sin(angle))
            if not (0.0 <= candidate[0] < width and 0.0 <= candidate[1] < height):
                continue
            gx, gy = grid_index(candidate)
            ok = True
            for yy in range(max(0, gy - 2), min(gh, gy + 3)):
                for xx in range(max(0, gx - 2), min(gw, gx + 3)):
                    other = grid[yy * gw + xx]
                    if other is not None and distance(candidate, points[other]) < radius:
                        ok = False; break
                if not ok:
                    break
            if ok:
                insert(candidate); found = True; break
        if not found:
            active.pop(ai)
    return points


def blue_noise_diagnostics(points: Sequence[Vec2], width: float = 1.0, height: float = 1.0) -> Dict[str, float]:
    if len(points) < 2 or width <= 0.0 or height <= 0.0:
        raise ValueError("at least two points and positive domain required")
    nearest = []
    for i, p in enumerate(points):
        nearest.append(min(distance(p, q) for j, q in enumerate(points) if i != j))
    mean = sum(nearest) / len(nearest)
    variance = sum((d - mean) ** 2 for d in nearest) / len(nearest)
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    return {
        "min_nearest": min(nearest),
        "mean_nearest": mean,
        "nearest_cv": sqrt(variance) / mean if mean > 0.0 else 0.0,
        "centroid_offset": sqrt((cx - width / 2.0) ** 2 + (cy - height / 2.0) ** 2),
    }


def hilbert_index_2d(x: int, y: int, bits: int) -> int:
    if bits < 1 or not (0 <= x < 1 << bits and 0 <= y < 1 << bits):
        raise ValueError("coordinates outside Hilbert grid")
    d = 0
    xx, yy = x, y
    s = 1 << (bits - 1)
    while s:
        rx = 1 if xx & s else 0
        ry = 1 if yy & s else 0
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                xx = (1 << bits) - 1 - xx
                yy = (1 << bits) - 1 - yy
            xx, yy = yy, xx
        s >>= 1
    return d


def _part1by1(n: int) -> int:
    n &= 0x0000FFFF
    n = (n | (n << 8)) & 0x00FF00FF
    n = (n | (n << 4)) & 0x0F0F0F0F
    n = (n | (n << 2)) & 0x33333333
    n = (n | (n << 1)) & 0x55555555
    return n


def morton2(x: int, y: int, bits: int = 16) -> int:
    if bits < 1 or bits > 16 or not (0 <= x < 1 << bits and 0 <= y < 1 << bits):
        raise ValueError("coordinates outside Morton width")
    return _part1by1(x) | (_part1by1(y) << 1)


def haar_forward(values: Sequence[float]) -> List[float]:
    n = len(values)
    if n == 0 or n & (n - 1):
        raise ValueError("Haar input length must be a positive power of two")
    out = [float(v) for v in values]
    temp = [0.0] * n
    length = n
    inv_sqrt2 = 1.0 / sqrt(2.0)
    while length > 1:
        half = length // 2
        for i in range(half):
            a, b = out[2 * i], out[2 * i + 1]
            temp[i] = (a + b) * inv_sqrt2
            temp[half + i] = (a - b) * inv_sqrt2
        out[:length] = temp[:length]
        length = half
    return out


def haar_inverse(coefficients: Sequence[float]) -> List[float]:
    n = len(coefficients)
    if n == 0 or n & (n - 1):
        raise ValueError("Haar coefficient length must be a positive power of two")
    out = [float(v) for v in coefficients]
    temp = [0.0] * n
    length = 1
    inv_sqrt2 = 1.0 / sqrt(2.0)
    while length < n:
        for i in range(length):
            a, d = out[i], out[length + i]
            temp[2 * i] = (a + d) * inv_sqrt2
            temp[2 * i + 1] = (a - d) * inv_sqrt2
        out[: 2 * length] = temp[: 2 * length]
        length *= 2
    return out


def _smooth_downsample(values: Sequence[float]) -> List[float]:
    if len(values) < 2 or len(values) % 2:
        raise ValueError("even input length >=2 required")
    return [0.5 * (values[2 * i] + values[2 * i + 1]) for i in range(len(values) // 2)]


def _upsample_linear(values: Sequence[float]) -> List[float]:
    out = []
    for v in values:
        out.extend((float(v), float(v)))
    return out


def laplacian_pyramid_1d(values: Sequence[float], levels: int) -> Tuple[List[List[float]], List[float]]:
    if levels < 0:
        raise ValueError("levels must be nonnegative")
    current = [float(v) for v in values]
    residuals: List[List[float]] = []
    for _ in range(levels):
        if len(current) < 2 or len(current) % 2:
            raise ValueError("each pyramid level requires even length")
        coarse = _smooth_downsample(current)
        up = _upsample_linear(coarse)
        residuals.append([current[i] - up[i] for i in range(len(current))])
        current = coarse
    return residuals, current


def reconstruct_laplacian_pyramid_1d(residuals: Sequence[Sequence[float]], coarse: Sequence[float]) -> List[float]:
    current = [float(v) for v in coarse]
    for residual in reversed(residuals):
        up = _upsample_linear(current)
        if len(up) != len(residual):
            raise ValueError("pyramid shape mismatch")
        current = [up[i] + residual[i] for i in range(len(up))]
    return current


def jacobi_eigen_symmetric(matrix: Sequence[Sequence[float]], max_iterations: int = 100, tolerance: float = 1e-12) -> Tuple[List[float], List[List[float]]]:
    n = len(matrix)
    if n == 0 or any(len(row) != n for row in matrix):
        raise ValueError("nonempty square matrix required")
    a = [[float(v) for v in row] for row in matrix]
    if any(abs(a[i][j] - a[j][i]) > tolerance for i in range(n) for j in range(n)):
        raise ValueError("matrix must be symmetric")
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    from math import atan2, cos, sin
    for _ in range(max_iterations):
        p, q, maxval = 0, 1 if n > 1 else 0, 0.0
        for i in range(n):
            for j in range(i + 1, n):
                if abs(a[i][j]) > maxval:
                    p, q, maxval = i, j, abs(a[i][j])
        if maxval <= tolerance or n == 1:
            break
        angle = 0.5 * atan2(2.0 * a[p][q], a[q][q] - a[p][p])
        c, s = cos(angle), sin(angle)
        for k in range(n):
            if k not in (p, q):
                apk, aqk = a[p][k], a[q][k]
                a[p][k] = a[k][p] = c * apk - s * aqk
                a[q][k] = a[k][q] = s * apk + c * aqk
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        a[p][p] = c * c * app - 2 * s * c * apq + s * s * aqq
        a[q][q] = s * s * app + 2 * s * c * apq + c * c * aqq
        a[p][q] = a[q][p] = 0.0
        for k in range(n):
            vkp, vkq = v[k][p], v[k][q]
            v[k][p] = c * vkp - s * vkq
            v[k][q] = s * vkp + c * vkq
    eigenvalues = [a[i][i] for i in range(n)]
    order = sorted(range(n), key=lambda i: eigenvalues[i])
    return [eigenvalues[i] for i in order], [[v[row][i] for row in range(n)] for i in order]
