"""Typed PBR material and color-management reference contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from .math3d import clamp, dot, normalize, scale, add

Color3 = tuple[float, float, float]
Color4 = tuple[float, float, float, float]
Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class PBRMaterial:
    id: str
    base_color: Color4 = (0.8, 0.8, 0.8, 1.0)
    metallic: float = 0.0
    roughness: float = 0.5
    emissive: Color3 = (0.0, 0.0, 0.0)
    alpha_mode: str = "OPAQUE"
    alpha_cutoff: float = 0.5
    double_sided: bool = False
    pattern_inputs: dict[str, Any] = field(default_factory=dict, compare=False)

    def validate(self):
        if not self.id:
            raise ValueError("material id required")
        if any(not 0.0 <= c <= 1.0 for c in self.base_color):
            raise ValueError("base_color components must be in [0,1]")
        if any(c < 0.0 or not math.isfinite(c) for c in self.emissive):
            raise ValueError("emissive components must be finite and nonnegative")
        if not 0.0 <= self.metallic <= 1.0 or not 0.0 <= self.roughness <= 1.0:
            raise ValueError("metallic and roughness must be in [0,1]")
        if self.alpha_mode not in {"OPAQUE", "MASK", "BLEND"}:
            raise ValueError("invalid alpha_mode")


@dataclass(frozen=True)
class Light:
    id: str
    kind: str = "directional"
    direction: Vec3 = (0.0, -1.0, -1.0)
    color: Color3 = (1.0, 1.0, 1.0)
    intensity: float = 1.0
    casts_shadow: bool = True

    def validate(self):
        if self.kind not in {"directional", "point", "spot", "area"}:
            raise ValueError("invalid light kind")
        if self.intensity < 0 or any(c < 0 for c in self.color):
            raise ValueError("light values must be nonnegative")


@dataclass(frozen=True)
class ColorPipeline:
    working_space: str = "scene-linear"
    display: str = "sRGB"
    view: str = "reference"
    exposure_stops: float = 0.0
    tone_mapper: str = "reinhard"
    ocio_config: str | None = None
    aces_profile: str | None = None

    def validate(self):
        if self.tone_mapper not in {"none", "reinhard", "aces-fitted"}:
            raise ValueError("unsupported tone mapper")


def srgb_to_linear_channel(c: float) -> float:
    c = clamp(c, 0.0, 1.0)
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb_channel(c: float) -> float:
    c = max(0.0, c)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1.0 / 2.4) - 0.055


def srgb_to_linear(color: Color3) -> Color3:
    return tuple(srgb_to_linear_channel(c) for c in color)  # type: ignore[return-value]


def linear_to_srgb(color: Color3) -> Color3:
    return tuple(clamp(linear_to_srgb_channel(c), 0.0, 1.0) for c in color)  # type: ignore[return-value]


def tone_map(color: Color3, mode: str = "reinhard") -> Color3:
    if mode == "none":
        return color
    if mode == "reinhard":
        return tuple(c / (1.0 + c) for c in color)  # type: ignore[return-value]
    if mode == "aces-fitted":
        def f(x: float) -> float:
            a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
            return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0)
        return tuple(f(v) for v in color)  # type: ignore[return-value]
    raise ValueError("unsupported tone mapper")


def apply_color_pipeline(color: Color3, pipeline: ColorPipeline) -> Color3:
    pipeline.validate()
    gain = 2.0 ** pipeline.exposure_stops
    exposed = tuple(max(0.0, c * gain) for c in color)
    mapped = tone_map(exposed, pipeline.tone_mapper)
    return linear_to_srgb(mapped) if pipeline.display.lower() == "srgb" else mapped


def shade_lambert(
    material: PBRMaterial,
    normal: Vec3,
    light_direction: Vec3,
    light_color: Color3 = (1.0, 1.0, 1.0),
    light_intensity: float = 1.0,
    ambient: float = 0.08,
) -> Color3:
    """Small deterministic preview shader; not a full production BRDF."""
    material.validate()
    n = normalize(normal)
    l = normalize(scale(light_direction, -1.0))
    ndotl = max(0.0, dot(n, l))
    diffuse_weight = (1.0 - material.metallic) * (ambient + light_intensity * ndotl)
    base = material.base_color[:3]
    return tuple(
        max(0.0, base[i] * diffuse_weight * light_color[i] + material.emissive[i])
        for i in range(3)
    )  # type: ignore[return-value]


class MaterialGraph:
    """Tiny acyclic dataflow graph for deterministic procedural preview values.

    The graph may read substrate/pattern values but returns presentation values only.  It has no
    method that mutates authoritative scene or event state.
    """

    def __init__(self):
        self.nodes: dict[str, dict[str, Any]] = {}
        self.output: str | None = None

    def add_node(self, node_id: str, op: str, inputs: dict[str, Any]):
        if node_id in self.nodes:
            raise ValueError("duplicate material node")
        if op not in {"constant", "add", "multiply", "mix", "clamp", "pattern"}:
            raise ValueError("unsupported material operation")
        self.nodes[node_id] = {"op": op, "inputs": inputs}

    def set_output(self, node_id: str):
        if node_id not in self.nodes:
            raise KeyError(node_id)
        self.output = node_id

    def evaluate(self, context: dict[str, Any]):
        if self.output is None:
            raise ValueError("material graph output not set")
        visiting: set[str] = set()
        cache: dict[str, Any] = {}

        def resolve(value):
            if isinstance(value, str) and value.startswith("$"):
                return eval_node(value[1:])
            return value

        def scalar_or_tuple_binary(a, b, fn):
            if isinstance(a, (tuple, list)) or isinstance(b, (tuple, list)):
                if not isinstance(a, (tuple, list)):
                    a = [a] * len(b)
                if not isinstance(b, (tuple, list)):
                    b = [b] * len(a)
                return tuple(fn(x, y) for x, y in zip(a, b))
            return fn(a, b)

        def eval_node(node_id: str):
            if node_id in cache:
                return cache[node_id]
            if node_id in visiting:
                raise ValueError("material graph cycle")
            if node_id not in self.nodes:
                raise KeyError(node_id)
            visiting.add(node_id)
            node = self.nodes[node_id]
            op, inputs = node["op"], node["inputs"]
            if op == "constant":
                value = inputs["value"]
            elif op == "pattern":
                value = context[inputs["name"]]
            elif op == "add":
                value = scalar_or_tuple_binary(resolve(inputs["a"]), resolve(inputs["b"]), lambda x, y: x + y)
            elif op == "multiply":
                value = scalar_or_tuple_binary(resolve(inputs["a"]), resolve(inputs["b"]), lambda x, y: x * y)
            elif op == "mix":
                a, b, t = resolve(inputs["a"]), resolve(inputs["b"]), float(resolve(inputs["t"]))
                value = scalar_or_tuple_binary(a, b, lambda x, y: (1.0 - t) * x + t * y)
            elif op == "clamp":
                x = resolve(inputs["x"])
                lo, hi = inputs.get("lo", 0.0), inputs.get("hi", 1.0)
                value = tuple(clamp(v, lo, hi) for v in x) if isinstance(x, (tuple, list)) else clamp(x, lo, hi)
            else:  # pragma: no cover
                raise AssertionError(op)
            visiting.remove(node_id)
            cache[node_id] = value
            return value

        return eval_node(self.output)
