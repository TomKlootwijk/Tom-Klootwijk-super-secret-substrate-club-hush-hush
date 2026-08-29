"""Runtime glTF and authoring-oriented USDA export adapters."""
from __future__ import annotations

import base64
import json
import math
from pathlib import Path
import re
import struct
from typing import Mapping

from .materials import PBRMaterial
from .math3d import flatten_column_major
from .scene import Scene


def _align4(data: bytearray):
    while len(data) % 4:
        data.append(0)


def write_gltf(scene: Scene, path: str | Path, materials: Mapping[str, PBRMaterial] | None = None) -> dict:
    """Write a self-contained glTF 2.0 JSON asset with an embedded data URI buffer."""
    materials = materials or {}
    path = Path(path)
    binary = bytearray()
    buffer_views = []
    accessors = []
    mesh_defs = []
    asset_mesh_index: dict[str, int] = {}

    material_ids = sorted({a.material_id for a in scene.assets.values() if a.material_id and a.material_id in materials})
    material_index = {mid: i for i, mid in enumerate(material_ids)}
    material_defs = []
    for mid in material_ids:
        m = materials[mid]
        m.validate()
        material_defs.append(
            {
                "name": m.id,
                "pbrMetallicRoughness": {
                    "baseColorFactor": list(m.base_color),
                    "metallicFactor": m.metallic,
                    "roughnessFactor": m.roughness,
                },
                "emissiveFactor": list(m.emissive),
                "alphaMode": m.alpha_mode,
                "alphaCutoff": m.alpha_cutoff,
                "doubleSided": m.double_sided,
            }
        )

    def append_view(payload: bytes, target: int | None = None) -> int:
        _align4(binary)
        offset = len(binary)
        binary.extend(payload)
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(payload)}
        if target is not None:
            view["target"] = target
        buffer_views.append(view)
        return len(buffer_views) - 1

    def append_accessor(view: int, component_type: int, count: int, type_name: str, minimum=None, maximum=None) -> int:
        item = {"bufferView": view, "componentType": component_type, "count": count, "type": type_name}
        if minimum is not None:
            item["min"] = list(minimum)
        if maximum is not None:
            item["max"] = list(maximum)
        accessors.append(item)
        return len(accessors) - 1

    for asset_id in sorted(scene.assets):
        asset = scene.assets[asset_id]
        mesh = asset.mesh
        mesh.validate()
        position_bytes = b"".join(struct.pack("<3f", *p) for p in mesh.vertices)
        pview = append_view(position_bytes, 34962)
        mn, mx = mesh.bounds()
        pacc = append_accessor(pview, 5126, len(mesh.vertices), "VEC3", mn, mx)
        attributes = {"POSITION": pacc}
        if mesh.normals:
            normal_bytes = b"".join(struct.pack("<3f", *n) for n in mesh.normals)
            nview = append_view(normal_bytes, 34962)
            attributes["NORMAL"] = append_accessor(nview, 5126, len(mesh.normals), "VEC3")
        if mesh.uvs:
            uv_bytes = b"".join(struct.pack("<2f", *uv) for uv in mesh.uvs)
            uvview = append_view(uv_bytes, 34962)
            attributes["TEXCOORD_0"] = append_accessor(uvview, 5126, len(mesh.uvs), "VEC2")
        flat_indices = [i for tri in mesh.triangles for i in tri]
        index_bytes = b"".join(struct.pack("<I", i) for i in flat_indices)
        iview = append_view(index_bytes, 34963)
        iacc = append_accessor(iview, 5125, len(flat_indices), "SCALAR", [min(flat_indices)], [max(flat_indices)])
        primitive = {"attributes": attributes, "indices": iacc, "mode": 4}
        if asset.material_id in material_index:
            primitive["material"] = material_index[asset.material_id]
        mesh_defs.append(
            {
                "name": asset.id,
                "primitives": [primitive],
                "extras": {
                    "sourcePattern": asset.source_pattern_id,
                    "contentHash": asset.content_hash(),
                    "schemaHash": asset.schema_hash,
                },
            }
        )
        asset_mesh_index[asset_id] = len(mesh_defs) - 1

    node_ids = sorted(scene.nodes)
    node_index = {node_id: i for i, node_id in enumerate(node_ids)}
    node_defs = []
    for node_id in node_ids:
        node = scene.nodes[node_id]
        item = {
            "name": node.id,
            "matrix": flatten_column_major(node.local_transform),
            "extras": {
                "tags": sorted(node.tags),
                "layer": node.layer,
                "lineage": list(node.lineage),
                "visible": node.visible,
            },
        }
        if node.asset_id is not None:
            item["mesh"] = asset_mesh_index[node.asset_id]
        children = [node_index[c] for c in scene.children(node_id)]
        if children:
            item["children"] = children
        node_defs.append(item)

    roots = [node_index[node_id] for node_id in scene.children(None)]
    data_uri = "data:application/octet-stream;base64," + base64.b64encode(bytes(binary)).decode("ascii")
    gltf = {
        "asset": {"version": "2.0", "generator": "UGTS-KC Two Hands 3.0 reference exporter"},
        "scene": 0,
        "scenes": [{"name": "KC Two Hands Scene", "nodes": roots}],
        "nodes": node_defs,
        "meshes": mesh_defs,
        "buffers": [{"byteLength": len(binary), "uri": data_uri}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "extras": {
            "ugtsSchema": scene.metadata.schema_version,
            "sceneHash": scene.content_hash(),
            "authorityBoundary": "render asset only; authoritative state remains in UGTS event/lineage records",
        },
    }
    if material_defs:
        gltf["materials"] = material_defs
    path.write_text(json.dumps(gltf, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return gltf


def _usd_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not value or value[0].isdigit():
        value = "N_" + value
    return value


def _fmt(v: float) -> str:
    if abs(v) < 1.0e-12:
        v = 0.0
    return f"{v:.9g}"


def write_usda(scene: Scene, path: str | Path) -> None:
    """Write a compact USDA scene for inspection and authoring interchange."""
    path = Path(path)
    lines = [
        "#usda 1.0",
        "(",
        '    defaultPrim = "KC_Two_Hands_Scene"',
        '    upAxis = "Y"',
        f"    metersPerUnit = {1.0 / scene.metadata.units_per_meter:.9g}",
        ")",
        "",
        'def Xform "KC_Two_Hands_Scene"',
        "{",
        f'    custom string ugts:schemaVersion = "{scene.metadata.schema_version}"',
        f'    custom string ugts:sceneHash = "{scene.content_hash()}"',
    ]

    def emit_node(node_id: str, indent: int):
        node = scene.nodes[node_id]
        pad = " " * indent
        name = _usd_name(node.id)
        lines.append(f'{pad}def Xform "{name}"')
        lines.append(f"{pad}{{")
        rows = ["(" + ", ".join(_fmt(v) for v in row) + ")" for row in node.local_transform]
        lines.append(f"{pad}    matrix4d xformOp:transform = ({', '.join(rows)})")
        lines.append(f'{pad}    uniform token[] xformOpOrder = ["xformOp:transform"]')
        lines.append(f'{pad}    custom string ugts:nodeId = "{node.id}"')
        lines.append(f"{pad}    custom bool ugts:visible = {'true' if node.visible else 'false'}")
        if node.lineage:
            values = ", ".join(json.dumps(v) for v in node.lineage)
            lines.append(f"{pad}    custom string[] ugts:lineage = [{values}]")
        if node.asset_id is not None:
            asset = scene.assets[node.asset_id]
            mesh = asset.mesh
            lines.append(f'{pad}    def Mesh "Geometry"')
            lines.append(f"{pad}    {{")
            points = ", ".join("(" + ", ".join(_fmt(v) for v in p) + ")" for p in mesh.vertices)
            lines.append(f"{pad}        point3f[] points = [{points}]")
            lines.append(f"{pad}        int[] faceVertexCounts = [{', '.join('3' for _ in mesh.triangles)}]")
            indices = ", ".join(str(i) for tri in mesh.triangles for i in tri)
            lines.append(f"{pad}        int[] faceVertexIndices = [{indices}]")
            if mesh.normals:
                normals = ", ".join("(" + ", ".join(_fmt(v) for v in n) + ")" for n in mesh.normals)
                lines.append(f"{pad}        normal3f[] normals = [{normals}] (")
                lines.append(f'{pad}            interpolation = "vertex"')
                lines.append(f"{pad}        )")
            lines.append(f'{pad}        custom string ugts:assetId = "{asset.id}"')
            lines.append(f'{pad}        custom string ugts:contentHash = "{asset.content_hash()}"')
            lines.append(f"{pad}    }}")
        for child in scene.children(node_id):
            emit_node(child, indent + 4)
        lines.append(f"{pad}}}")

    for root in scene.children(None):
        emit_node(root, 4)
    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_scene_json(scene: Scene, path: str | Path) -> None:
    Path(path).write_text(json.dumps(scene.to_dict(include_geometry=True), indent=2, sort_keys=True) + "\n", encoding="utf-8")
