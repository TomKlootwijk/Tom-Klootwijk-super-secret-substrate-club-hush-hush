"""Small CPU/SVG preview renderer.

This renderer is deliberately downstream and non-authoritative.  Its purpose is to make the
reference vertical slice visible and to generate deterministic regression artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass
import html
import math
from pathlib import Path
from typing import Mapping

from .materials import ColorPipeline, PBRMaterial, apply_color_pipeline, shade_lambert
from .math3d import cross, dot, normalize, sub, transform_point
from .scene import Scene

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class Camera:
    position: Vec3 = (4.0, 3.0, 5.0)
    target: Vec3 = (0.0, 0.0, 0.0)
    up: Vec3 = (0.0, 1.0, 0.0)
    vertical_fov_degrees: float = 45.0
    near: float = 0.01

    def basis(self):
        forward = normalize(sub(self.target, self.position))
        right = normalize(cross(forward, self.up))
        true_up = normalize(cross(right, forward))
        return right, true_up, forward


@dataclass(frozen=True)
class RenderSettings:
    width: int = 960
    height: int = 640
    background: tuple[float, float, float] = (0.035, 0.07, 0.10)
    wireframe: bool = False
    show_node_labels: bool = True
    light_direction: Vec3 = (-0.5, -1.0, -0.7)
    color_pipeline: ColorPipeline = ColorPipeline(exposure_stops=0.0, tone_mapper="aces-fitted")


@dataclass(frozen=True)
class RenderResult:
    path: str
    visible_nodes: int
    triangle_count: int
    culled_triangles: int


def _project(point: Vec3, camera: Camera, width: int, height: int):
    right, up, forward = camera.basis()
    rel = sub(point, camera.position)
    z = dot(rel, forward)
    if z <= camera.near:
        return None
    x = dot(rel, right)
    y = dot(rel, up)
    focal = height / (2.0 * math.tan(math.radians(camera.vertical_fov_degrees) * 0.5))
    return width * 0.5 + focal * x / z, height * 0.5 - focal * y / z, z


def _hex(color):
    values = [max(0, min(255, int(round(c * 255)))) for c in color]
    return "#%02x%02x%02x" % tuple(values)


def render_scene_svg(
    scene: Scene,
    path: str | Path,
    materials: Mapping[str, PBRMaterial] | None = None,
    camera: Camera = Camera(),
    settings: RenderSettings = RenderSettings(),
) -> RenderResult:
    materials = materials or {}
    path = str(path)
    bg = _hex(apply_color_pipeline(settings.background, settings.color_pipeline))
    triangles = []
    labels = []
    culled = 0
    visible_nodes = 0

    default_material = PBRMaterial("default", (0.25, 0.72, 0.78, 1.0), metallic=0.05, roughness=0.45)
    for node_id in sorted(scene.nodes):
        node = scene.composed_node(node_id)
        if not node.visible or node.asset_id is None:
            continue
        asset = scene.assets[node.asset_id]
        transform = scene.world_transform(node_id)
        world_vertices = [transform_point(transform, p) for p in asset.mesh.vertices]
        projected = [_project(p, camera, settings.width, settings.height) for p in world_vertices]
        material = materials.get(asset.material_id or "", default_material)
        material.validate()
        visible_nodes += 1
        for tri in asset.mesh.triangles:
            pa, pb, pc = (projected[i] for i in tri)
            if pa is None or pb is None or pc is None:
                culled += 1
                continue
            wa, wb, wc = (world_vertices[i] for i in tri)
            try:
                normal = normalize(cross(sub(wb, wa), sub(wc, wa)))
            except ValueError:
                culled += 1
                continue
            shaded = shade_lambert(material, normal, settings.light_direction, light_intensity=0.9, ambient=0.18)
            display = apply_color_pipeline(shaded, settings.color_pipeline)
            depth = (pa[2] + pb[2] + pc[2]) / 3.0
            triangles.append((depth, node_id, (pa, pb, pc), _hex(display), material.base_color[3]))
        center = scene.node_bounds(node_id)
        if center is not None:
            p = _project(center.center(), camera, settings.width, settings.height)
            if p is not None:
                labels.append((p[2], node_id, p[0], p[1]))

    triangles.sort(key=lambda item: (-item[0], item[1]))
    labels.sort(key=lambda item: -item[0])
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{settings.width}" height="{settings.height}" viewBox="0 0 {settings.width} {settings.height}">',
        f'<rect width="100%" height="100%" fill="{bg}"/>',
        '<g stroke-linejoin="round" stroke-linecap="round">',
    ]
    for _, node_id, pts, fill, alpha in triangles:
        coords = " ".join(f"{p[0]:.3f},{p[1]:.3f}" for p in pts)
        if settings.wireframe:
            lines.append(f'<polygon points="{coords}" fill="none" stroke="{fill}" stroke-width="0.8" opacity="{alpha:.3f}" data-node="{html.escape(node_id)}"/>')
        else:
            lines.append(f'<polygon points="{coords}" fill="{fill}" stroke="#0b2634" stroke-width="0.35" opacity="{alpha:.3f}" data-node="{html.escape(node_id)}"/>')
    lines.append("</g>")
    if settings.show_node_labels:
        lines.append('<g font-family="DejaVu Sans, sans-serif" font-size="13" fill="#eef8fa" stroke="#0b2634" stroke-width="2" paint-order="stroke">')
        for _, node_id, x, y in labels:
            lines.append(f'<text x="{x:.2f}" y="{y - 8:.2f}" text-anchor="middle">{html.escape(node_id)}</text>')
        lines.append("</g>")
    lines.append(f'<text x="18" y="{settings.height - 18}" font-family="DejaVu Sans, sans-serif" font-size="12" fill="#8fb8c2">KC Two Hands 3.0 CPU reference preview - non-authoritative projection</text>')
    lines.append("</svg>")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return RenderResult(path, visible_nodes, len(triangles), culled)
