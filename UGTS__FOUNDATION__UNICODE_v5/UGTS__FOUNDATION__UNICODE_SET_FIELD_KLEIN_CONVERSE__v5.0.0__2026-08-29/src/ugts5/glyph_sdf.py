"""Canonical UGTS mathematical-glyph SDFs.

The canonical profile is not a font outline. It is a finite union of equal-radius
capsules around a versioned line-segment skeleton. The returned value is therefore
an exact Euclidean SDF to that canonical capsule union, subject only to floating-point
rounding. Font-exact glyph profiles remain separate records.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, hypot, pi, sin
from typing import Iterable, Sequence

Point = tuple[float, float]
Segment = tuple[Point, Point]


@dataclass(frozen=True)
class GlyphGeometry:
    literal: str
    segments: tuple[Segment, ...]
    stroke_radius: float
    bbox: tuple[float, float, float, float] = (-1.0, -1.0, 1.0, 1.0)
    profile_id: str = "ugts.canonical.capsule-glyph.v1"


def _segment_distance(p: Point, a: Point, b: Point) -> float:
    px, py = p
    ax, ay = a
    bx, by = b
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    vv = vx * vx + vy * vy
    if vv == 0.0:
        return hypot(wx, wy)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / vv))
    qx = ax + t * vx
    qy = ay + t * vy
    return hypot(px - qx, py - qy)


def _arc_segments(*, opens_right: bool, samples: int = 28, rx: float = 0.72, ry: float = 0.86) -> list[Segment]:
    # A C-shaped half ellipse. opens_right=True keeps the left half and leaves a gap at +x.
    start = pi / 3.0 if opens_right else -2.0 * pi / 3.0
    end = 5.0 * pi / 3.0 if opens_right else 2.0 * pi / 3.0
    points = [(rx * cos(start + (end - start) * i / samples), ry * sin(start + (end - start) * i / samples)) for i in range(samples + 1)]
    return list(zip(points[:-1], points[1:]))


def _mirror_segments(segments: Iterable[Segment]) -> list[Segment]:
    return [((-a[0], a[1]), (-b[0], b[1])) for a, b in segments]


def _slash() -> list[Segment]:
    return [((-0.62, -0.92), (0.62, 0.92))]


def _base_membership(opens_right: bool, *, bar: bool = True) -> list[Segment]:
    segments = _arc_segments(opens_right=opens_right)
    if bar:
        if opens_right:
            segments.append(((-0.62, 0.0), (0.56, 0.0)))
        else:
            segments.append(((0.62, 0.0), (-0.56, 0.0)))
    return segments


def _subset_equal(opens_right: bool) -> list[Segment]:
    segments = _base_membership(opens_right, bar=False)
    segments.append(((-0.60, -0.72), (0.60, -0.72)))
    return segments if opens_right else _mirror_segments(_subset_equal(True))


def glyph_segments(literal: str) -> GlyphGeometry:
    stroke = 0.075
    if literal == "∈":
        segs = _base_membership(True, bar=True)
    elif literal == "∋":
        segs = _mirror_segments(_base_membership(True, bar=True))
    elif literal == "∉":
        segs = _base_membership(True, bar=True) + _slash()
    elif literal == "∌":
        segs = _mirror_segments(_base_membership(True, bar=True) + _slash())
    elif literal in {"⊂", "⊊"}:
        segs = _base_membership(True, bar=False)
        if literal == "⊊":
            segs += [((-0.58, -0.68), (0.58, -0.68)), ((-0.18, -0.82), (0.18, -0.54))]
    elif literal in {"⊃", "⊋"}:
        source = "⊂" if literal == "⊃" else "⊊"
        segs = _mirror_segments(list(glyph_segments(source).segments))
    elif literal == "⊆":
        segs = _base_membership(True, bar=False) + [((-0.58, -0.68), (0.58, -0.68))]
    elif literal == "⊇":
        segs = _mirror_segments(list(glyph_segments("⊆").segments))
    elif literal == "⊄":
        segs = _base_membership(True, bar=False) + _slash()
    elif literal == "⊅":
        segs = _mirror_segments(list(glyph_segments("⊄").segments))
    elif literal == "⊈":
        segs = list(glyph_segments("⊆").segments) + _slash()
    elif literal == "⊉":
        segs = _mirror_segments(list(glyph_segments("⊈").segments))
    elif literal == "∪":
        # Lower half ellipse, open upward.
        pts = [(0.72 * cos(pi + pi * i / 28), 0.75 * sin(pi + pi * i / 28) + 0.28) for i in range(29)]
        segs = list(zip(pts[:-1], pts[1:]))
    elif literal == "∩":
        segs = [((-a[0], -a[1]), (-b[0], -b[1])) for a, b in glyph_segments("∪").segments]
    elif literal == "∖":
        segs = [((-0.48, 0.82), (0.48, -0.82))]
    elif literal == "∁":
        segs = _base_membership(True, bar=False) + [((0.25, 0.50), (0.66, 0.78))]
    elif literal == "∅":
        pts = [(0.68 * cos(2 * pi * i / 32), 0.82 * sin(2 * pi * i / 32)) for i in range(33)]
        segs = list(zip(pts[:-1], pts[1:])) + _slash()
    elif literal == "=":
        segs = [((-0.68, 0.28), (0.68, 0.28)), ((-0.68, -0.28), (0.68, -0.28))]
    else:
        raise KeyError(f"no canonical glyph geometry for {literal!r}")
    return GlyphGeometry(literal=literal, segments=tuple(segs), stroke_radius=stroke)


def glyph_sdf(literal: str, x: float, y: float) -> float:
    geometry = glyph_segments(literal)
    distance = min(_segment_distance((x, y), a, b) for a, b in geometry.segments)
    return distance - geometry.stroke_radius


def reflection_residual(direct: str, converse: str, samples: Sequence[Point]) -> float:
    return max(abs(glyph_sdf(direct, x, y) - glyph_sdf(converse, -x, y)) for x, y in samples)
