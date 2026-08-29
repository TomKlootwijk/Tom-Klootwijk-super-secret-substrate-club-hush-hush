"""Dependency-free 2D vector-art authoring and SVG interchange.

The format is intentionally small enough to serialize directly into a game project
and expressive enough for reusable game sprites, UI icons, collision guides and
browser Canvas rendering.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import html
import json
import math
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

Vec2 = tuple[float, float]


def _vec2(value: Sequence[float]) -> Vec2:
    if len(value) != 2:
        raise ValueError("expected two coordinates")
    x, y = float(value[0]), float(value[1])
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError("coordinates must be finite")
    return x, y


def _fmt(value: float) -> str:
    if abs(value) < 1.0e-12:
        value = 0.0
    return f"{value:.9g}"


def _lerp(a: Vec2, b: Vec2, t: float) -> Vec2:
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def _distance_point_line(p: Vec2, a: Vec2, b: Vec2) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    denom = dx * dx + dy * dy
    if denom <= 1.0e-24:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / denom))
    qx, qy = a[0] + dx * t, a[1] + dy * t
    return math.hypot(p[0] - qx, p[1] - qy)


@dataclass(frozen=True)
class GradientStop:
    offset: float
    color: str

    def validate(self) -> None:
        if not 0.0 <= self.offset <= 1.0:
            raise ValueError("gradient stop offset must be in [0, 1]")
        if not self.color:
            raise ValueError("gradient stop color is required")

    def to_dict(self) -> dict[str, Any]:
        return {"offset": self.offset, "color": self.color}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GradientStop":
        stop = cls(float(data["offset"]), str(data["color"]))
        stop.validate()
        return stop


@dataclass(frozen=True)
class LinearGradient:
    id: str
    start: Vec2
    end: Vec2
    stops: tuple[GradientStop, ...]

    def validate(self) -> None:
        if not self.id:
            raise ValueError("gradient id is required")
        _vec2(self.start)
        _vec2(self.end)
        if len(self.stops) < 2:
            raise ValueError("a gradient requires at least two stops")
        for stop in self.stops:
            stop.validate()
        offsets = [s.offset for s in self.stops]
        if offsets != sorted(offsets):
            raise ValueError("gradient stops must be ordered")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "linear",
            "id": self.id,
            "start": list(self.start),
            "end": list(self.end),
            "stops": [s.to_dict() for s in self.stops],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LinearGradient":
        gradient = cls(
            str(data["id"]),
            _vec2(data["start"]),
            _vec2(data["end"]),
            tuple(GradientStop.from_dict(s) for s in data["stops"]),
        )
        gradient.validate()
        return gradient


@dataclass(frozen=True)
class RadialGradient:
    id: str
    center: Vec2
    radius: float
    stops: tuple[GradientStop, ...]
    focal: Vec2 | None = None

    def validate(self) -> None:
        if not self.id:
            raise ValueError("gradient id is required")
        _vec2(self.center)
        if self.focal is not None:
            _vec2(self.focal)
        if not math.isfinite(self.radius) or self.radius <= 0:
            raise ValueError("radial gradient radius must be positive")
        if len(self.stops) < 2:
            raise ValueError("a gradient requires at least two stops")
        for stop in self.stops:
            stop.validate()
        offsets = [s.offset for s in self.stops]
        if offsets != sorted(offsets):
            raise ValueError("gradient stops must be ordered")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": "radial",
            "id": self.id,
            "center": list(self.center),
            "radius": self.radius,
            "stops": [s.to_dict() for s in self.stops],
        }
        if self.focal is not None:
            data["focal"] = list(self.focal)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RadialGradient":
        gradient = cls(
            str(data["id"]),
            _vec2(data["center"]),
            float(data["radius"]),
            tuple(GradientStop.from_dict(s) for s in data["stops"]),
            _vec2(data["focal"]) if data.get("focal") is not None else None,
        )
        gradient.validate()
        return gradient


Gradient = LinearGradient | RadialGradient


@dataclass(frozen=True)
class VectorPaint:
    fill: str | None = "#ffffff"
    stroke: str | None = None
    stroke_width: float = 1.0
    opacity: float = 1.0
    line_cap: str = "round"
    line_join: str = "round"

    def validate(self) -> None:
        if self.fill is None and self.stroke is None:
            raise ValueError("paint must have a fill or stroke")
        if self.stroke_width < 0 or not math.isfinite(self.stroke_width):
            raise ValueError("stroke_width must be finite and non-negative")
        if not 0.0 <= self.opacity <= 1.0:
            raise ValueError("opacity must be in [0, 1]")
        if self.line_cap not in {"butt", "round", "square"}:
            raise ValueError("unsupported line_cap")
        if self.line_join not in {"miter", "round", "bevel"}:
            raise ValueError("unsupported line_join")

    def to_dict(self) -> dict[str, Any]:
        return {
            "fill": self.fill,
            "stroke": self.stroke,
            "stroke_width": self.stroke_width,
            "opacity": self.opacity,
            "line_cap": self.line_cap,
            "line_join": self.line_join,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VectorPaint":
        paint = cls(
            data.get("fill"),
            data.get("stroke"),
            float(data.get("stroke_width", 1.0)),
            float(data.get("opacity", 1.0)),
            str(data.get("line_cap", "round")),
            str(data.get("line_join", "round")),
        )
        paint.validate()
        return paint


_COMMAND_ARITY = {"M": 2, "L": 2, "Q": 4, "C": 6, "Z": 0}


@dataclass(frozen=True)
class PathCommand:
    op: str
    values: tuple[float, ...] = ()

    def validate(self) -> None:
        op = self.op.upper()
        if op not in _COMMAND_ARITY:
            raise ValueError(f"unsupported vector command: {self.op}")
        if len(self.values) != _COMMAND_ARITY[op]:
            raise ValueError(f"command {op} expects {_COMMAND_ARITY[op]} values")
        if not all(math.isfinite(float(v)) for v in self.values):
            raise ValueError("command coordinates must be finite")

    def to_dict(self) -> list[Any]:
        return [self.op.upper(), *self.values]

    @classmethod
    def from_value(cls, value: Sequence[Any]) -> "PathCommand":
        if not value:
            raise ValueError("empty path command")
        cmd = cls(str(value[0]).upper(), tuple(float(v) for v in value[1:]))
        cmd.validate()
        return cmd


class VectorPathBuilder:
    """Mutable convenience builder that produces an immutable :class:`VectorPath`."""

    def __init__(self, path_id: str, paint: VectorPaint | None = None, fill_rule: str = "nonzero"):
        self.path_id = path_id
        self.paint = paint or VectorPaint()
        self.fill_rule = fill_rule
        self.commands: list[PathCommand] = []

    def move_to(self, x: float, y: float) -> "VectorPathBuilder":
        self.commands.append(PathCommand("M", (float(x), float(y))))
        return self

    def line_to(self, x: float, y: float) -> "VectorPathBuilder":
        self.commands.append(PathCommand("L", (float(x), float(y))))
        return self

    def quadratic_to(self, cx: float, cy: float, x: float, y: float) -> "VectorPathBuilder":
        self.commands.append(PathCommand("Q", (float(cx), float(cy), float(x), float(y))))
        return self

    def cubic_to(self, c1x: float, c1y: float, c2x: float, c2y: float, x: float, y: float) -> "VectorPathBuilder":
        self.commands.append(PathCommand("C", (float(c1x), float(c1y), float(c2x), float(c2y), float(x), float(y))))
        return self

    def close(self) -> "VectorPathBuilder":
        self.commands.append(PathCommand("Z"))
        return self

    def build(self) -> "VectorPath":
        path = VectorPath(self.path_id, tuple(self.commands), self.paint, self.fill_rule)
        path.validate()
        return path


@dataclass(frozen=True)
class VectorPath:
    id: str
    commands: tuple[PathCommand, ...]
    paint: VectorPaint = field(default_factory=VectorPaint)
    fill_rule: str = "nonzero"
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def validate(self) -> None:
        if not self.id:
            raise ValueError("path id is required")
        if not self.commands:
            raise ValueError("path requires commands")
        if self.commands[0].op.upper() != "M":
            raise ValueError("path must begin with M")
        if self.fill_rule not in {"nonzero", "evenodd"}:
            raise ValueError("fill_rule must be nonzero or evenodd")
        for command in self.commands:
            command.validate()
        self.paint.validate()

    def svg_d(self) -> str:
        parts: list[str] = []
        for command in self.commands:
            values = " ".join(_fmt(v) for v in command.values)
            parts.append(command.op.upper() if not values else f"{command.op.upper()} {values}")
        return " ".join(parts)

    def flatten(self, tolerance: float = 0.5) -> tuple[tuple[Vec2, ...], ...]:
        """Flatten curves into one or more polylines.

        Each ``M`` starts a subpath. Closed paths repeat their first point at the end.
        The recursion is bounded so malformed coordinates cannot cause unbounded work.
        """
        if tolerance <= 0 or not math.isfinite(tolerance):
            raise ValueError("tolerance must be positive and finite")
        self.validate()
        subpaths: list[list[Vec2]] = []
        current: list[Vec2] = []
        cursor: Vec2 = (0.0, 0.0)
        start: Vec2 | None = None

        def emit(point: Vec2) -> None:
            nonlocal cursor
            p = _vec2(point)
            if not current or p != current[-1]:
                current.append(p)
            cursor = p

        def flatten_quad(a: Vec2, c: Vec2, b: Vec2, depth: int = 0) -> None:
            if depth >= 16 or _distance_point_line(c, a, b) <= tolerance:
                emit(b)
                return
            ac = _lerp(a, c, 0.5)
            cb = _lerp(c, b, 0.5)
            mid = _lerp(ac, cb, 0.5)
            flatten_quad(a, ac, mid, depth + 1)
            flatten_quad(mid, cb, b, depth + 1)

        def flatten_cubic(a: Vec2, c1: Vec2, c2: Vec2, b: Vec2, depth: int = 0) -> None:
            flatness = max(_distance_point_line(c1, a, b), _distance_point_line(c2, a, b))
            if depth >= 16 or flatness <= tolerance:
                emit(b)
                return
            a1 = _lerp(a, c1, 0.5)
            c12 = _lerp(c1, c2, 0.5)
            c2b = _lerp(c2, b, 0.5)
            left2 = _lerp(a1, c12, 0.5)
            right1 = _lerp(c12, c2b, 0.5)
            mid = _lerp(left2, right1, 0.5)
            flatten_cubic(a, a1, left2, mid, depth + 1)
            flatten_cubic(mid, right1, c2b, b, depth + 1)

        for command in self.commands:
            op, v = command.op.upper(), command.values
            if op == "M":
                if current:
                    subpaths.append(current)
                current = []
                start = (v[0], v[1])
                emit(start)
            elif op == "L":
                emit((v[0], v[1]))
            elif op == "Q":
                flatten_quad(cursor, (v[0], v[1]), (v[2], v[3]))
            elif op == "C":
                flatten_cubic(cursor, (v[0], v[1]), (v[2], v[3]), (v[4], v[5]))
            elif op == "Z" and start is not None:
                emit(start)
        if current:
            subpaths.append(current)
        return tuple(tuple(path) for path in subpaths)

    def bounds(self, tolerance: float = 0.25) -> tuple[Vec2, Vec2]:
        points = [p for subpath in self.flatten(tolerance) for p in subpath]
        if not points:
            raise ValueError("path has no drawable points")
        return (
            (min(p[0] for p in points), min(p[1] for p in points)),
            (max(p[0] for p in points), max(p[1] for p in points)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "commands": [c.to_dict() for c in self.commands],
            "paint": self.paint.to_dict(),
            "fill_rule": self.fill_rule,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VectorPath":
        path = cls(
            str(data["id"]),
            tuple(PathCommand.from_value(c) for c in data["commands"]),
            VectorPaint.from_dict(data.get("paint", {})),
            str(data.get("fill_rule", "nonzero")),
            dict(data.get("metadata", {})),
        )
        path.validate()
        return path


@dataclass(frozen=True)
class VectorAsset2D:
    id: str
    size: Vec2
    pivot: Vec2
    paths: tuple[VectorPath, ...]
    gradients: tuple[Gradient, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def validate(self) -> None:
        if not self.id:
            raise ValueError("vector asset id is required")
        width, height = _vec2(self.size)
        if width <= 0 or height <= 0:
            raise ValueError("vector asset size must be positive")
        _vec2(self.pivot)
        if not self.paths:
            raise ValueError("vector asset requires at least one path")
        ids: set[str] = set()
        for path in self.paths:
            path.validate()
            if path.id in ids:
                raise ValueError(f"duplicate path id: {path.id}")
            ids.add(path.id)
        gradient_ids: set[str] = set()
        for gradient in self.gradients:
            gradient.validate()
            if gradient.id in gradient_ids:
                raise ValueError(f"duplicate gradient id: {gradient.id}")
            gradient_ids.add(gradient.id)
        for path in self.paths:
            for paint_value in (path.paint.fill, path.paint.stroke):
                if isinstance(paint_value, str) and paint_value.startswith("@") and paint_value[1:] not in gradient_ids:
                    raise ValueError(f"unknown gradient reference: {paint_value}")

    def bounds(self) -> tuple[Vec2, Vec2]:
        boxes = [path.bounds() for path in self.paths]
        return (
            (min(box[0][0] for box in boxes), min(box[0][1] for box in boxes)),
            (max(box[1][0] for box in boxes), max(box[1][1] for box in boxes)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "size": list(self.size),
            "pivot": list(self.pivot),
            "paths": [p.to_dict() for p in self.paths],
            "gradients": [g.to_dict() for g in self.gradients],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VectorAsset2D":
        gradients: list[Gradient] = []
        for item in data.get("gradients", []):
            if item.get("type") == "linear":
                gradients.append(LinearGradient.from_dict(item))
            elif item.get("type") == "radial":
                gradients.append(RadialGradient.from_dict(item))
            else:
                raise ValueError(f"unsupported gradient type: {item.get('type')}")
        asset = cls(
            str(data["id"]),
            _vec2(data["size"]),
            _vec2(data.get("pivot", (0.0, 0.0))),
            tuple(VectorPath.from_dict(p) for p in data["paths"]),
            tuple(gradients),
            dict(data.get("metadata", {})),
        )
        asset.validate()
        return asset


class VectorLibrary:
    def __init__(self, assets: Iterable[VectorAsset2D] = ()):
        self.assets: dict[str, VectorAsset2D] = {}
        for asset in assets:
            self.add(asset)

    def add(self, asset: VectorAsset2D, replace_existing: bool = False) -> None:
        asset.validate()
        if asset.id in self.assets and not replace_existing:
            raise ValueError(f"vector asset already exists: {asset.id}")
        self.assets[asset.id] = asset

    def get(self, asset_id: str) -> VectorAsset2D:
        try:
            return self.assets[asset_id]
        except KeyError as exc:
            raise KeyError(f"unknown vector asset: {asset_id}") from exc

    def __iter__(self) -> Iterator[VectorAsset2D]:
        for asset_id in sorted(self.assets):
            yield self.assets[asset_id]

    def to_dict(self) -> dict[str, Any]:
        return {asset.id: asset.to_dict() for asset in self}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | list[dict[str, Any]]) -> "VectorLibrary":
        values = data.values() if isinstance(data, dict) else data
        return cls(VectorAsset2D.from_dict(item) for item in values)


def polygon_path(path_id: str, points: Sequence[Sequence[float]], paint: VectorPaint | None = None, close: bool = True) -> VectorPath:
    if len(points) < 2:
        raise ValueError("polygon path needs at least two points")
    builder = VectorPathBuilder(path_id, paint)
    first = _vec2(points[0])
    builder.move_to(*first)
    for point in points[1:]:
        builder.line_to(*_vec2(point))
    if close:
        builder.close()
    return builder.build()


def rectangle_asset(
    asset_id: str,
    width: float,
    height: float,
    fill: str = "#ffffff",
    stroke: str | None = None,
    corner_radius: float = 0.0,
) -> VectorAsset2D:
    if width <= 0 or height <= 0:
        raise ValueError("rectangle dimensions must be positive")
    hw, hh = width * 0.5, height * 0.5
    r = max(0.0, min(float(corner_radius), hw, hh))
    paint = VectorPaint(fill=fill, stroke=stroke, stroke_width=2.0 if stroke else 1.0)
    if r <= 0:
        path = polygon_path("body", [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)], paint)
    else:
        k = 0.5522847498307936
        b = VectorPathBuilder("body", paint).move_to(-hw + r, -hh)
        b.line_to(hw - r, -hh).cubic_to(hw - r + k * r, -hh, hw, -hh + r - k * r, hw, -hh + r)
        b.line_to(hw, hh - r).cubic_to(hw, hh - r + k * r, hw - r + k * r, hh, hw - r, hh)
        b.line_to(-hw + r, hh).cubic_to(-hw + r - k * r, hh, -hw, hh - r + k * r, -hw, hh - r)
        b.line_to(-hw, -hh + r).cubic_to(-hw, -hh + r - k * r, -hw + r - k * r, -hh, -hw + r, -hh).close()
        path = b.build()
    asset = VectorAsset2D(asset_id, (width, height), (0.0, 0.0), (path,))
    asset.validate()
    return asset


def circle_asset(asset_id: str, radius: float, fill: str = "#ffffff", stroke: str | None = None) -> VectorAsset2D:
    if radius <= 0:
        raise ValueError("radius must be positive")
    k = 0.5522847498307936 * radius
    r = float(radius)
    paint = VectorPaint(fill=fill, stroke=stroke, stroke_width=2.0 if stroke else 1.0)
    path = (
        VectorPathBuilder("body", paint)
        .move_to(r, 0)
        .cubic_to(r, k, k, r, 0, r)
        .cubic_to(-k, r, -r, k, -r, 0)
        .cubic_to(-r, -k, -k, -r, 0, -r)
        .cubic_to(k, -r, r, -k, r, 0)
        .close()
        .build()
    )
    asset = VectorAsset2D(asset_id, (2 * r, 2 * r), (0.0, 0.0), (path,))
    asset.validate()
    return asset


def star_asset(
    asset_id: str,
    points: int = 5,
    outer_radius: float = 24.0,
    inner_radius: float | None = None,
    fill: str = "#ffffff",
    stroke: str | None = None,
) -> VectorAsset2D:
    if points < 3:
        raise ValueError("star needs at least three points")
    if outer_radius <= 0:
        raise ValueError("outer_radius must be positive")
    inner_radius = outer_radius * 0.45 if inner_radius is None else float(inner_radius)
    if not 0 < inner_radius < outer_radius:
        raise ValueError("inner_radius must be between zero and outer_radius")
    vertices: list[Vec2] = []
    for i in range(points * 2):
        angle = -math.pi * 0.5 + i * math.pi / points
        radius = outer_radius if i % 2 == 0 else inner_radius
        vertices.append((math.cos(angle) * radius, math.sin(angle) * radius))
    paint = VectorPaint(fill=fill, stroke=stroke, stroke_width=2.0 if stroke else 1.0)
    path = polygon_path("body", vertices, paint)
    asset = VectorAsset2D(asset_id, (outer_radius * 2, outer_radius * 2), (0.0, 0.0), (path,))
    asset.validate()
    return asset


def _paint_to_svg(value: str | None) -> str:
    if value is None:
        return "none"
    if value.startswith("@"):
        return f"url(#{html.escape(value[1:], quote=True)})"
    return html.escape(value, quote=True)


def vector_asset_to_svg(asset: VectorAsset2D, background: str | None = None, padding: float = 0.0) -> str:
    asset.validate()
    width, height = asset.size
    # ``pivot`` is the local point placed on the entity origin by the browser
    # renderer. Frame the logical asset rectangle around that point so centered
    # procedural primitives are not clipped in standalone SVG output.
    min_x = asset.pivot[0] - width * 0.5 - padding
    min_y = asset.pivot[1] - height * 0.5 - padding
    view_w, view_h = width + 2 * padding, height + 2 * padding
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_fmt(view_w)}" height="{_fmt(view_h)}" viewBox="{_fmt(min_x)} {_fmt(min_y)} {_fmt(view_w)} {_fmt(view_h)}">',
        f"  <title>{html.escape(asset.id)}</title>",
    ]
    if asset.gradients:
        lines.append("  <defs>")
        for gradient in asset.gradients:
            if isinstance(gradient, LinearGradient):
                lines.append(
                    f'    <linearGradient id="{html.escape(gradient.id, quote=True)}" x1="{_fmt(gradient.start[0])}" y1="{_fmt(gradient.start[1])}" x2="{_fmt(gradient.end[0])}" y2="{_fmt(gradient.end[1])}" gradientUnits="userSpaceOnUse">'
                )
            else:
                focal = gradient.focal or gradient.center
                lines.append(
                    f'    <radialGradient id="{html.escape(gradient.id, quote=True)}" cx="{_fmt(gradient.center[0])}" cy="{_fmt(gradient.center[1])}" r="{_fmt(gradient.radius)}" fx="{_fmt(focal[0])}" fy="{_fmt(focal[1])}" gradientUnits="userSpaceOnUse">'
                )
            for stop in gradient.stops:
                lines.append(f'      <stop offset="{_fmt(stop.offset * 100)}%" stop-color="{html.escape(stop.color, quote=True)}"/>')
            lines.append("    </linearGradient>" if isinstance(gradient, LinearGradient) else "    </radialGradient>")
        lines.append("  </defs>")
    if background is not None:
        lines.append(
            f'  <rect x="{_fmt(min_x)}" y="{_fmt(min_y)}" width="{_fmt(view_w)}" height="{_fmt(view_h)}" fill="{html.escape(background, quote=True)}"/>'
        )
    for path in asset.paths:
        paint = path.paint
        lines.append(
            "  <path "
            f'id="{html.escape(path.id, quote=True)}" '
            f'd="{html.escape(path.svg_d(), quote=True)}" '
            f'fill="{_paint_to_svg(paint.fill)}" '
            f'stroke="{_paint_to_svg(paint.stroke)}" '
            f'stroke-width="{_fmt(paint.stroke_width)}" '
            f'opacity="{_fmt(paint.opacity)}" '
            f'stroke-linecap="{paint.line_cap}" stroke-linejoin="{paint.line_join}" '
            f'fill-rule="{path.fill_rule}"/>'
        )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def write_vector_svg(asset: VectorAsset2D, path: str | Path, background: str | None = None, padding: float = 0.0) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(vector_asset_to_svg(asset, background, padding), encoding="utf-8")
    return output


def write_vector_library_json(library: VectorLibrary, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(library.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
