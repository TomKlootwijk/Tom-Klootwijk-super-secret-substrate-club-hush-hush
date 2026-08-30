"""Native Android project and compact scene-pack exporter for UGTS-KC 3.9.x."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import struct
import re
from typing import Any, Mapping
from xml.sax.saxutils import escape as xml_escape

from .animationpack import (
    ANIMATION_PACK_ASSET,
    compile_animation_pack_bytes,
    inspect_animation_pack,
)
from .chrono_binding_pack import (
    CHRONO_BINDING_PACK_ASSET,
    collect_chrono_bindings,
    compile_chrono_binding_pack_bytes,
    inspect_chrono_binding_pack,
    resolve_chrono_player_assets,
)
from .export import write_gltf
from .graphpack import (
    GRAPH_PACK_ASSET,
    compile_graph_pack_bytes,
    inspect_graph_pack,
)
from .hierarchypack import (
    HIERARCHY_PACK_ASSET,
    compile_hierarchy_pack_bytes,
    inspect_hierarchy_pack,
)
from .mobile3d import Mobile3DProject, tag_mask
from .polarpack import (
    POLAR_PACK_ASSET,
    compile_polar_pack_bytes,
    inspect_polar_pack,
)
from .polar_population_pack import (
    POLAR_POPULATION_PACK_ASSET,
    compile_polar_population_pack_bytes,
    inspect_polar_population_pack,
)
from .renderpack import (
    RENDER_SUBSTRATE_PACK_ASSET,
    compile_render_substrate_pack_bytes,
    inspect_render_substrate_pack,
)
from .scatterpack import (
    SCATTER_PACK_ASSET,
    compile_scatter_pack_bytes,
    inspect_scatter_pack,
)

# Grove emits KC3D392.  The native reader accepts both 3.9.1 and 3.9.2 packs,
# while inspection remains backward compatible with existing Signature assets.
PACK_MAGIC = b"KC3D392\0"
SUPPORTED_PACK_MAGICS = (b"KC3D391\0", PACK_MAGIC)
PACK_ENDIAN = 0x01020304
PACK_VERSION = 1

_SAVED_SCENE_METADATA_KEYS = frozenset({"saved_scenes", "saved_scene_instances"})
_ANDROID_TEMPLATE_VOLATILE_NAMES = (
    ".cxx",
    ".gradle",
    ".idea",
    "*.iml",
    "build",
    "local.properties",
)
_CHRONO_RUNTIME_BINDING_HEADER = "chrono_runtime_binding.hpp"
_CHRONO_SAFE_PATH = re.compile(r"[A-Za-z0-9._/-]+\Z")
_SHA256_HEX = re.compile(r"[0-9a-fA-F]{64}\Z")
_MAX_UINT64 = (1 << 64) - 1


def _materialized_project(project: Mobile3DProject) -> Mobile3DProject:
    metadata = getattr(project, "metadata", {})
    if not isinstance(metadata, Mapping) or not any(
        key in metadata for key in _SAVED_SCENE_METADATA_KEYS
    ):
        return project
    from .saved_scene import materialize_saved_scenes

    return materialize_saved_scenes(project)


class _Writer:
    def __init__(self):
        self.data = bytearray()

    def raw(self, value: bytes) -> None:
        self.data.extend(value)

    def u8(self, value: int) -> None:
        self.data.extend(struct.pack("<B", value))

    def u16(self, value: int) -> None:
        self.data.extend(struct.pack("<H", value))

    def u32(self, value: int) -> None:
        self.data.extend(struct.pack("<I", value))

    def f32(self, value: float) -> None:
        self.data.extend(struct.pack("<f", float(value)))

    def floats(self, values) -> None:
        for value in values:
            self.f32(value)

    def string(self, value: str) -> None:
        encoded = value.encode("utf-8")
        if len(encoded) > 65535:
            raise ValueError("scene-pack string too long")
        self.u16(len(encoded))
        self.raw(encoded)


def compile_scene_pack_bytes(project: Mobile3DProject) -> bytes:
    """Compile a validated project into the dependency-free native binary format."""
    project = _materialized_project(project)
    project.validate()
    writer = _Writer()
    writer.raw(PACK_MAGIC)
    writer.u32(PACK_ENDIAN)
    writer.u32(PACK_VERSION)
    writer.u32(len(project.meshes))
    writer.u32(len(project.materials))
    writer.u32(len(project.nodes))
    writer.u32(len(project.quality_tiers))
    writer.u32(len(project.target_profiles))
    writer.floats(project.background)
    writer.floats(project.camera.position)
    writer.floats(project.camera.target)
    writer.floats(project.camera.up)
    writer.f32(project.camera.vertical_fov_degrees)
    writer.f32(project.camera.near)
    writer.f32(project.camera.far)
    writer.floats(project.light.direction)
    writer.floats(project.light.color)
    writer.f32(project.light.intensity)
    writer.f32(project.light.ambient)
    writer.f32(project.world.fixed_dt)
    writer.floats(project.world.gravity)
    writer.f32(project.world.floor_y)
    writer.floats(project.world.bounds_min)
    writer.floats(project.world.bounds_max)
    writer.f32(project.world.player_speed)
    writer.f32(project.world.jump_speed)
    writer.raw(project.content_hash().encode("ascii"))
    writer.string(project.id)
    writer.string(project.title)
    writer.string(project.author)
    writer.string(project.start_quality)

    for tier in project.quality_tiers:
        writer.string(tier.id)
        writer.u16(tier.target_fps)
        writer.f32(tier.render_scale)
        writer.u32(tier.max_visible_nodes)
        writer.u8(tier.msaa_samples)
        writer.u8(1 if tier.post_processing else 0)
        writer.u8(tier.shadow_quality)
        writer.u8(0)

    for profile in project.target_profiles:
        writer.string(profile.id)
        writer.string(profile.label)
        writer.u16(profile.min_sdk)
        writer.u16(profile.target_sdk)
        writer.u16(profile.compile_sdk)
        writer.u16(profile.target_refresh_hz)
        writer.u32(profile.memory_floor_mb)
        writer.u8(profile.required_gles[0])
        writer.u8(profile.required_gles[1])
        writer.u8(1 if profile.vulkan_optional else 0)
        writer.u8(len(profile.preferred_abis))
        for abi in profile.preferred_abis:
            writer.string(abi)
        writer.string(profile.default_quality)
        writer.u8(len(profile.device_hints))
        for hint in profile.device_hints:
            writer.string(hint)
        writer.u8(len(profile.gpu_hints))
        for hint in profile.gpu_hints:
            writer.string(hint)

    mesh_ids = sorted(project.meshes)
    mesh_indices = {mesh_id: index for index, mesh_id in enumerate(mesh_ids)}
    for mesh_id in mesh_ids:
        mesh = project.meshes[mesh_id]
        normals = mesh.resolved_normals()
        writer.string(mesh.id)
        writer.u32(len(mesh.vertices))
        writer.u32(len(mesh.triangles) * 3)
        for position, normal in zip(mesh.vertices, normals):
            writer.floats(position)
            writer.floats(normal)
        for triangle in mesh.triangles:
            for index in triangle:
                writer.u32(index)

    material_ids = sorted(project.materials)
    material_indices = {
        material_id: index for index, material_id in enumerate(material_ids)
    }
    for material_id in material_ids:
        material = project.materials[material_id]
        writer.string(material.id)
        writer.floats(material.base_color)
        writer.f32(material.metallic)
        writer.f32(material.roughness)
        writer.floats(material.emissive)
        writer.u8(1 if material.double_sided else 0)
        writer.raw(b"\0\0\0")

    collider_types = {"none": 0, "sphere": 1, "box": 2}
    for node in project.nodes:
        writer.string(node.id)
        writer.u32(mesh_indices[node.mesh_id])
        writer.u32(material_indices[node.material_id])
        writer.floats(node.transform.translation)
        writer.floats(node.transform.rotation)
        writer.floats(node.transform.scale)
        writer.floats(node.velocity)
        writer.floats(node.angular_velocity)
        writer.u8(collider_types[node.collider.shape])
        writer.u8(1 if node.collider.sensor else 0)
        writer.u8(1 if node.dynamic else 0)
        writer.u8(0)
        writer.f32(node.collider.radius)
        writer.floats(node.collider.half_extents)
        writer.f32(node.mass)
        writer.f32(node.restitution)
        writer.u32(tag_mask(node.tags))
    return bytes(writer.data)


def write_scene_pack(project: Mobile3DProject, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(compile_scene_pack_bytes(project))
    return path


class _Reader:
    def __init__(self, data: bytes):
        self.data = memoryview(data)
        self.offset = 0

    def raw(self, count: int) -> bytes:
        if count < 0 or self.offset + count > len(self.data):
            raise ValueError("truncated scene pack")
        result = self.data[self.offset:self.offset + count].tobytes()
        self.offset += count
        return result

    def unpack(self, fmt: str):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.raw(size))

    def u8(self) -> int:
        return self.unpack("<B")[0]

    def u16(self) -> int:
        return self.unpack("<H")[0]

    def u32(self) -> int:
        return self.unpack("<I")[0]

    def f32(self) -> float:
        return self.unpack("<f")[0]

    def string(self) -> str:
        return self.raw(self.u16()).decode("utf-8")


def inspect_scene_pack(data_or_path: bytes | str | Path) -> dict[str, Any]:
    """Read structural counts and verify all records without needing Android."""
    if isinstance(data_or_path, (str, Path)):
        data = Path(data_or_path).read_bytes()
    else:
        data = data_or_path
    reader = _Reader(data)
    if reader.raw(8) not in SUPPORTED_PACK_MAGICS:
        raise ValueError("scene-pack magic mismatch")
    if reader.u32() != PACK_ENDIAN:
        raise ValueError("scene-pack endian marker mismatch")
    if reader.u32() != PACK_VERSION:
        raise ValueError("unsupported scene-pack version")
    mesh_count = reader.u32()
    material_count = reader.u32()
    node_count = reader.u32()
    quality_count = reader.u32()
    target_count = reader.u32()
    for _ in range(4 + 3 + 3 + 3 + 3 + 3 + 3 + 2 + 1 + 3 + 1 + 3 + 3 + 2):
        reader.f32()
    project_hash = reader.raw(64).decode("ascii")
    project_id, title, author, start_quality = (
        reader.string(), reader.string(), reader.string(), reader.string()
    )
    qualities = []
    for _ in range(quality_count):
        quality_id = reader.string()
        target_fps = reader.u16()
        render_scale = reader.f32()
        max_nodes = reader.u32()
        reader.raw(4)
        qualities.append(
            {
                "id": quality_id, "target_fps": target_fps,
                "render_scale": render_scale, "max_visible_nodes": max_nodes,
            }
        )
    targets = []
    for _ in range(target_count):
        profile_id, label = reader.string(), reader.string()
        min_sdk, target_sdk, compile_sdk, refresh = (
            reader.u16(), reader.u16(), reader.u16(), reader.u16()
        )
        memory = reader.u32()
        gles = (reader.u8(), reader.u8())
        vulkan = bool(reader.u8())
        abis = [reader.string() for _ in range(reader.u8())]
        default_quality = reader.string()
        device_hints = [reader.string() for _ in range(reader.u8())]
        gpu_hints = [reader.string() for _ in range(reader.u8())]
        targets.append(
            {
                "id": profile_id, "label": label, "min_sdk": min_sdk,
                "target_sdk": target_sdk, "compile_sdk": compile_sdk,
                "target_refresh_hz": refresh, "memory_floor_mb": memory,
                "gles": gles, "vulkan_optional": vulkan, "abis": abis,
                "default_quality": default_quality,
                "device_hints": device_hints, "gpu_hints": gpu_hints,
            }
        )
    meshes = []
    for _ in range(mesh_count):
        mesh_id = reader.string()
        vertex_count, index_count = reader.u32(), reader.u32()
        reader.raw(vertex_count * 6 * 4)
        reader.raw(index_count * 4)
        meshes.append(
            {
                "id": mesh_id, "vertex_count": vertex_count,
                "index_count": index_count,
            }
        )
    materials = []
    for _ in range(material_count):
        material_id = reader.string()
        reader.raw((4 + 1 + 1 + 3) * 4 + 4)
        materials.append(material_id)
    nodes = []
    for _ in range(node_count):
        node_id = reader.string()
        mesh_index, material_index = reader.u32(), reader.u32()
        reader.raw((3 + 4 + 3 + 3 + 3) * 4)
        collider_type, sensor, dynamic = reader.u8(), reader.u8(), reader.u8()
        reader.u8()
        reader.raw((1 + 3 + 1 + 1) * 4)
        tags = reader.u32()
        if mesh_index >= mesh_count or material_index >= material_count:
            raise ValueError("scene-pack node has invalid mesh/material index")
        nodes.append(
            {
                "id": node_id, "mesh_index": mesh_index,
                "material_index": material_index,
                "collider_type": collider_type, "sensor": bool(sensor),
                "dynamic": bool(dynamic), "tag_mask": tags,
            }
        )
    if reader.offset != len(data):
        raise ValueError(f"scene-pack trailing bytes: {len(data)-reader.offset}")
    if len(project_hash) != 64 or any(c not in "0123456789abcdef" for c in project_hash):
        raise ValueError("scene-pack project hash invalid")
    return {
        "schema": "ugts-kc-native-scene-pack-inspection-3.9.2",
        "format_version": PACK_VERSION,
        "byte_length": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "project_hash": project_hash,
        "project_id": project_id,
        "title": title,
        "author": author,
        "start_quality": start_quality,
        "mesh_count": mesh_count,
        "material_count": material_count,
        "node_count": node_count,
        "quality_count": quality_count,
        "target_count": target_count,
        "qualities": qualities,
        "targets": targets,
        "meshes": meshes,
        "materials": materials,
        "nodes": nodes,
    }


@dataclass(frozen=True)
class AndroidProjectBuild:
    output_dir: Path
    project_file: Path
    scene_pack: Path
    build_report: Path
    file_count: int
    total_bytes: int
    project_hash: str
    profile_hint: str
    graph_pack: Path | None = None
    polar_pack: Path | None = None
    polar_population_pack: Path | None = None
    scatter_pack: Path | None = None
    animation_pack: Path | None = None
    hierarchy_pack: Path | None = None
    render_substrate_pack: Path | None = None
    chrono_binding_pack: Path | None = None

    @property
    def render_pack(self) -> Path | None:
        """Short alias retained for callers that use the module name."""

        return self.render_substrate_pack


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class _ChronoRuntimeAsset:
    relative_posix: str
    relative_parts: tuple[str, ...]
    source: Path
    byte_count: int
    sha256: str

    @property
    def packaged_path(self) -> str:
        return f"chrono/{self.relative_posix}"


@dataclass(frozen=True)
class _ChronoRuntimeBinding:
    present: bool
    manifest_relative_posix: str
    manifest_sha256: str
    profile_relative_posix: str
    profile_sha256: str
    assets: tuple[_ChronoRuntimeAsset, ...]

    @property
    def manifest_packaged_path(self) -> str:
        if not self.manifest_relative_posix:
            return ""
        return f"chrono/{self.manifest_relative_posix}"

    @property
    def profile_packaged_path(self) -> str:
        if not self.profile_relative_posix:
            return ""
        return f"chrono/{self.profile_relative_posix}"


def _canonical_chrono_asset_path(value: object, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} path must be a non-empty string")
    if not _CHRONO_SAFE_PATH.fullmatch(value) or "\\" in value:
        raise ValueError(
            f"{label} path must use portable ASCII asset characters and '/' separators"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value != path.as_posix()
        or not path.parts
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        raise ValueError(f"{label} path must be a canonical safe relative path")
    return path


def _canonical_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_HEX.fullmatch(value):
        raise ValueError(f"{label} SHA-256 must contain exactly 64 hexadecimal digits")
    return value.lower()


def _declared_byte_count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} byte count must be an integer")
    if value < 0 or value > _MAX_UINT64:
        raise ValueError(f"{label} byte count must fit an unsigned 64-bit integer")
    return value


def _validate_chrono_runtime_binding(
    chrono_metadata: object,
    asset_source_root: str | Path | None,
) -> _ChronoRuntimeBinding:
    if chrono_metadata is None:
        return _ChronoRuntimeBinding(False, "", "", "", "", ())
    if not isinstance(chrono_metadata, Mapping):
        raise ValueError("metadata.chrono_scene_observation must be an object")
    declared_assets = chrono_metadata.get("runtime_assets", ())
    if not isinstance(declared_assets, (list, tuple)):
        raise ValueError("metadata.chrono_scene_observation.runtime_assets must be a list")
    if not declared_assets:
        return _ChronoRuntimeBinding(False, "", "", "", "", ())
    if asset_source_root is None:
        raise ValueError(
            "chrono runtime assets were declared but no asset source root was provided"
        )
    source_root = Path(asset_source_root).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(
            f"chrono asset source root is not a directory: {source_root}"
        )

    assets: list[_ChronoRuntimeAsset] = []
    folded_paths: dict[tuple[str, ...], str] = {}
    for index, item in enumerate(declared_assets):
        label = f"chrono runtime asset {index}"
        if not isinstance(item, Mapping):
            raise ValueError(f"{label} must be an object")
        relative = _canonical_chrono_asset_path(item.get("path"), label)
        folded = tuple(part.casefold() for part in relative.parts)
        if folded in folded_paths:
            raise ValueError(
                "chrono runtime asset duplicate or case-collision: "
                f"{folded_paths[folded]} and {relative.as_posix()}"
            )
        for prior_folded, prior_text in folded_paths.items():
            common = min(len(folded), len(prior_folded))
            if folded[:common] == prior_folded[:common] and len(folded) != len(prior_folded):
                raise ValueError(
                    "chrono runtime asset file/directory path collision: "
                    f"{prior_text} and {relative.as_posix()}"
                )
        folded_paths[folded] = relative.as_posix()

        expected_bytes = _declared_byte_count(item.get("bytes"), label)
        expected_hash = _canonical_sha256(item.get("sha256"), label)
        source_asset = source_root.joinpath(*relative.parts).resolve()
        if not source_asset.is_relative_to(source_root) or not source_asset.is_file():
            raise FileNotFoundError(
                "chrono runtime asset is missing or escapes its root: "
                f"{relative.as_posix()}"
            )
        actual_bytes = source_asset.stat().st_size
        if actual_bytes != expected_bytes:
            raise ValueError(
                f"chrono runtime asset byte-count mismatch for {relative.as_posix()}: "
                f"declared {expected_bytes}, found {actual_bytes}"
            )
        actual_hash = _file_digest(source_asset)
        if actual_hash != expected_hash:
            raise ValueError(
                f"chrono runtime asset hash mismatch for {relative.as_posix()}"
            )
        assets.append(
            _ChronoRuntimeAsset(
                relative.as_posix(),
                tuple(relative.parts),
                source_asset,
                expected_bytes,
                expected_hash,
            )
        )

    manifest_relative = _canonical_chrono_asset_path(
        chrono_metadata.get("manifest"),
        "metadata.chrono_scene_observation manifest",
    )
    manifest_sha256 = _canonical_sha256(
        chrono_metadata.get("manifest_sha256"),
        "metadata.chrono_scene_observation manifest",
    )
    manifest_assets = [
        asset for asset in assets if asset.relative_posix == manifest_relative.as_posix()
    ]
    if len(manifest_assets) != 1:
        raise ValueError(
            "chrono manifest must be declared exactly once as a runtime asset"
        )
    if manifest_assets[0].sha256 != manifest_sha256:
        raise ValueError(
            "chrono manifest metadata SHA-256 does not match its runtime asset receipt"
        )

    try:
        manifest_value = json.loads(
            manifest_assets[0].source.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("chrono manifest runtime asset is not readable JSON") from exc
    if not isinstance(manifest_value, Mapping):
        raise ValueError("chrono manifest runtime asset root must be an object")

    profile_relative_posix = ""
    profile_sha256 = ""
    from .chrono_video import (
        CHRONO_MANIFEST_SCHEMA,
        ChronoVideoError,
        inspect_chrono_profile_receipt,
    )

    if manifest_value.get("schema") == CHRONO_MANIFEST_SCHEMA:
        profile_relative = _canonical_chrono_asset_path(
            manifest_value.get("profile_asset"), "chrono manifest profile_asset"
        )
        if profile_relative.as_posix() != "profile.json":
            raise ValueError("chrono manifest profile_asset must be profile.json")
        profile_assets = [
            asset
            for asset in assets
            if asset.relative_posix == profile_relative.as_posix()
        ]
        if len(profile_assets) != 1:
            raise ValueError(
                "chrono profile must be declared exactly once as a runtime asset"
            )
        manifest_asset_receipts = manifest_value.get("assets")
        if not isinstance(manifest_asset_receipts, list):
            raise ValueError("chrono manifest assets must be a list")
        manifest_profile_receipts = [
            item
            for item in manifest_asset_receipts
            if isinstance(item, Mapping)
            and item.get("path") == profile_relative.as_posix()
        ]
        if len(manifest_profile_receipts) != 1:
            raise ValueError(
                "chrono manifest must hash-bind profile.json exactly once"
            )
        manifest_profile_receipt = manifest_profile_receipts[0]
        manifest_profile_bytes = _declared_byte_count(
            manifest_profile_receipt.get("bytes"), "chrono manifest profile asset"
        )
        manifest_profile_hash = _canonical_sha256(
            manifest_profile_receipt.get("sha256"), "chrono manifest profile asset"
        )
        profile_asset = profile_assets[0]
        if (
            manifest_profile_bytes != profile_asset.byte_count
            or manifest_profile_hash != profile_asset.sha256
        ):
            raise ValueError(
                "chrono manifest and project profile asset receipts disagree"
            )
        try:
            raw_profile = json.loads(profile_asset.source.read_text(encoding="utf-8"))
            profile_report = inspect_chrono_profile_receipt(raw_profile)
        except (OSError, json.JSONDecodeError, ChronoVideoError) as exc:
            raise ValueError(f"chrono profile receipt is invalid: {exc}") from exc
        profile_sha256 = _canonical_sha256(
            manifest_value.get("profile_sha256"), "chrono manifest profile"
        )
        if profile_report["profile_sha256"] != profile_sha256:
            raise ValueError(
                "chrono manifest profile SHA-256 does not match recomputed profile"
            )
        profile_relative_posix = profile_relative.as_posix()
    return _ChronoRuntimeBinding(
        True,
        manifest_relative.as_posix(),
        manifest_sha256,
        profile_relative_posix,
        profile_sha256,
        tuple(assets),
    )


def _cpp_sha256_array(digest: str) -> str:
    values = (
        [f"0x{digest[index:index + 2]}u" for index in range(0, len(digest), 2)]
        if digest
        else ["0u"] * 32
    )
    return "{{" + ", ".join(values) + "}}"


def _chrono_runtime_binding_header(binding: _ChronoRuntimeBinding) -> str:
    manifest_hex = binding.manifest_sha256
    profile_hex = binding.profile_sha256
    asset_lines = [
        "        AssetBinding{"
        f'"{asset.packaged_path}", std::uint64_t{{{asset.byte_count}}}, '
        f"std::array<std::uint8_t, 32>{_cpp_sha256_array(asset.sha256)}"
        "},"
        for asset in binding.assets
    ]
    if asset_lines:
        asset_initializer = "{{\n" + "\n".join(asset_lines) + "\n    }}"
    else:
        asset_initializer = "{}"
    return (
        "// Generated by ugts_kc3.androidexport; do not edit.\n"
        "#pragma once\n"
        "#include <array>\n"
        "#include <cstdint>\n"
        "#include <string_view>\n\n"
        "namespace kc::chrono_runtime_binding {\n\n"
        "struct AssetBinding {\n"
        "    std::string_view path;\n"
        "    std::uint64_t bytes;\n"
        "    std::array<std::uint8_t, 32> sha256;\n"
        "};\n\n"
        f"inline constexpr bool kPresent = {'true' if binding.present else 'false'};\n"
        f'inline constexpr std::string_view kManifestAssetPath{{"{binding.manifest_packaged_path}"}};\n'
        f'inline constexpr std::string_view kManifestSha256Hex{{"{manifest_hex}"}};\n'
        "inline constexpr std::array<std::uint8_t, 32> kManifestSha256"
        f"{_cpp_sha256_array(manifest_hex)};\n"
        f'inline constexpr std::string_view kProfileAssetPath{{"{binding.profile_packaged_path}"}};\n'
        f'inline constexpr std::string_view kProfileSha256Hex{{"{profile_hex}"}};\n'
        "inline constexpr std::array<std::uint8_t, 32> kProfileSha256"
        f"{_cpp_sha256_array(profile_hex)};\n"
        f"inline constexpr std::array<AssetBinding, {len(binding.assets)}> kAssets"
        f"{asset_initializer};\n\n"
        "[[nodiscard]] inline constexpr const AssetBinding* find(\n"
        "    std::string_view path) noexcept {\n"
        "    for (const auto& asset : kAssets) {\n"
        "        if (asset.path == path) return &asset;\n"
        "    }\n"
        "    return nullptr;\n"
        "}\n\n"
        "} // namespace kc::chrono_runtime_binding\n"
    )


def android_application_id(project_id: str) -> str:
    """Derive a stable, install-safe package id so learner projects do not collide."""
    segments = []
    for raw in re.split(r"[^a-zA-Z0-9_]+", project_id.lower()):
        if not raw:
            continue
        if raw[0].isdigit():
            raw = "g_" + raw
        segments.append(raw)
    if not segments:
        segments = ["game"]
    suffix = ".".join(segments)
    application_id = f"org.ugts.games.{suffix}"
    if len(application_id) > 150:
        digest = hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:12]
        application_id = f"org.ugts.games.game_{digest}"
    return application_id


def build_android_project(
    project: Mobile3DProject,
    output_dir: str | Path,
    profile_hint: str = "auto",
    clean: bool = True,
    include_authoring_assets: bool = False,
    asset_source_root: str | Path | None = None,
) -> AndroidProjectBuild:
    """Materialize a self-contained Android Studio/Gradle native source project."""
    authored_project = project
    project = _materialized_project(project)
    project.validate()
    chrono_binding = _validate_chrono_runtime_binding(
        authored_project.metadata.get("chrono_scene_observation"),
        asset_source_root,
    )
    # Compile metadata before touching an existing output directory.  A graph
    # outside the native subset must fail export clearly and non-destructively.
    hierarchy_pack_data = compile_hierarchy_pack_bytes(project)
    hierarchy_inspection = (
        inspect_hierarchy_pack(hierarchy_pack_data, node_count=len(project.nodes))
        if hierarchy_pack_data else None
    )
    graph_pack_data = compile_graph_pack_bytes(project)
    graph_inspection = (
        inspect_graph_pack(graph_pack_data) if graph_pack_data else None
    )
    polar_pack_data = compile_polar_pack_bytes(project)
    polar_inspection = (
        inspect_polar_pack(polar_pack_data, node_count=len(project.nodes))
        if polar_pack_data else None
    )
    polar_population_pack_data = compile_polar_population_pack_bytes(project)
    polar_population_inspection = (
        inspect_polar_population_pack(
            polar_population_pack_data, node_count=len(project.nodes)
        )
        if polar_population_pack_data
        else None
    )
    scatter_pack_data = compile_scatter_pack_bytes(project)
    scatter_inspection = (
        inspect_scatter_pack(scatter_pack_data, node_count=len(project.nodes))
        if scatter_pack_data else None
    )
    animation_pack_data = compile_animation_pack_bytes(project)
    animation_inspection = (
        inspect_animation_pack(animation_pack_data, node_count=len(project.nodes))
        if animation_pack_data else None
    )
    render_substrate_pack_data = compile_render_substrate_pack_bytes(project)
    render_substrate_inspection = (
        inspect_render_substrate_pack(render_substrate_pack_data)
        if render_substrate_pack_data else None
    )
    chrono_node_bindings = collect_chrono_bindings(project, materialize=False)
    chrono_binding_pack_data = compile_chrono_binding_pack_bytes(project)
    chrono_binding_pack_inspection = (
        inspect_chrono_binding_pack(
            chrono_binding_pack_data, node_count=len(project.nodes)
        )
        if chrono_binding_pack_data
        else None
    )
    chrono_player_assets = resolve_chrono_player_assets(
        chrono_node_bindings, asset_source_root
    )
    output_dir = Path(output_dir)
    template = Path(__file__).with_name("android_template") / "project"
    if not template.exists():
        raise FileNotFoundError(f"Android template missing: {template}")
    if output_dir.exists() and clean:
        shutil.rmtree(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output is not empty: {output_dir}")
    shutil.copytree(
        template,
        output_dir,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*_ANDROID_TEMPLATE_VOLATILE_NAMES),
    )

    strings_path = output_dir / "app/src/main/res/values/strings.xml"
    strings_path.write_text(
        strings_path.read_text("utf-8").replace(
            "__APP_TITLE__", xml_escape(project.title, {'"': "&quot;", "'": "&apos;"})
        ),
        encoding="utf-8",
    )
    gradle_path = output_dir / "app/build.gradle"
    gradle_path.write_text(
        gradle_path.read_text("utf-8")
        .replace("__PROFILE_HINT__", profile_hint)
        .replace("__APPLICATION_ID__", android_application_id(project.id)),
        encoding="utf-8",
    )
    assets = output_dir / "app/src/main/assets"
    assets.mkdir(parents=True, exist_ok=True)
    chrono_asset_receipts: list[dict[str, object]] = []
    chrono_substrate_asset_receipts: list[dict[str, object]] = []
    chrono_assets = assets / "chrono"
    for asset in chrono_binding.assets:
        target_asset = chrono_assets.joinpath(*asset.relative_parts)
        if target_asset.exists():
            raise FileExistsError(
                f"chrono runtime asset target already exists: {asset.packaged_path}"
            )
        target_asset.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asset.source, target_asset)
        copied_bytes = target_asset.stat().st_size
        copied_hash = _file_digest(target_asset)
        if copied_bytes != asset.byte_count or copied_hash != asset.sha256:
            raise ValueError(
                "copied chrono runtime asset failed byte/SHA verification: "
                f"{asset.packaged_path}"
            )
        chrono_asset_receipts.append(
            {
                "path": asset.packaged_path,
                "bytes": copied_bytes,
                "sha256": copied_hash,
            }
        )
    for asset in chrono_player_assets:
        relative = PurePosixPath(asset.packaged_path)
        target_asset = assets.joinpath(*relative.parts)
        if target_asset.exists():
            raise FileExistsError(
                f"chrono substrate asset target already exists: {asset.packaged_path}"
            )
        target_asset.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asset.source, target_asset)
        copied_bytes = target_asset.stat().st_size
        copied_hash = _file_digest(target_asset)
        if copied_bytes != asset.byte_count or copied_hash != asset.sha256:
            raise ValueError(
                "copied chrono substrate asset failed byte/SHA verification: "
                f"{asset.packaged_path}"
            )
        chrono_substrate_asset_receipts.append(
            {
                "path": asset.packaged_path,
                "bytes": copied_bytes,
                "sha256": copied_hash,
            }
        )
    binding_header = output_dir / "app/src/main/cpp" / _CHRONO_RUNTIME_BINDING_HEADER
    binding_header.write_text(
        _chrono_runtime_binding_header(chrono_binding),
        encoding="utf-8",
        newline="\n",
    )
    # Authoring JSON and inspection evidence are not runtime inputs.  Keeping
    # them outside app/src/main/assets avoids silently packaging duplicate data
    # into every APK.  A diagnostic export can opt back into the old layout.
    evidence_dir = assets if include_authoring_assets else output_dir
    project_file = evidence_dir / "project.json"
    project_file.write_text(
        json.dumps(authored_project.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    scene_pack = write_scene_pack(project, assets / "signature_scene.kc3d")
    hierarchy_pack = None
    if hierarchy_pack_data:
        hierarchy_pack = assets / HIERARCHY_PACK_ASSET
        hierarchy_pack.write_bytes(hierarchy_pack_data)
    graph_pack = None
    if graph_pack_data:
        graph_pack = assets / GRAPH_PACK_ASSET
        graph_pack.write_bytes(graph_pack_data)
    polar_pack = None
    if polar_pack_data:
        polar_pack = assets / POLAR_PACK_ASSET
        polar_pack.write_bytes(polar_pack_data)
    polar_population_pack = None
    if polar_population_pack_data:
        polar_population_pack = assets / POLAR_POPULATION_PACK_ASSET
        polar_population_pack.write_bytes(polar_population_pack_data)
    scatter_pack = None
    if scatter_pack_data:
        scatter_pack = assets / SCATTER_PACK_ASSET
        scatter_pack.write_bytes(scatter_pack_data)
    animation_pack = None
    if animation_pack_data:
        animation_pack = assets / ANIMATION_PACK_ASSET
        animation_pack.write_bytes(animation_pack_data)
    render_substrate_pack = None
    if render_substrate_pack_data:
        render_substrate_pack = assets / RENDER_SUBSTRATE_PACK_ASSET
        render_substrate_pack.write_bytes(render_substrate_pack_data)
    chrono_binding_pack = None
    if chrono_binding_pack_data:
        chrono_binding_pack = assets / CHRONO_BINDING_PACK_ASSET
        chrono_binding_pack.write_bytes(chrono_binding_pack_data)
    inspection = inspect_scene_pack(scene_pack)
    (evidence_dir / "scene-pack-inspection.json").write_text(
        json.dumps(inspection, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    files = sorted(path for path in output_dir.rglob("*") if path.is_file())
    report = {
        "schema": "ugts-kc-android-source-build-3.9.2",
        "edition": project.edition,
        "project_id": project.id,
        "project_hash": project.content_hash(),
        "authoring_project_hash": authored_project.content_hash(),
        "profile_hint": profile_hint,
        "native_backend": "OpenGL ES 3.0 via Android NDK NativeActivity",
        "vulkan_status": "optional interface reserved; no Vulkan renderer is claimed",
        "application_id": android_application_id(project.id),
        "authoring_assets_packaged": include_authoring_assets,
        "chrono_video_assets": chrono_asset_receipts,
        "chrono_runtime_binding": {
            "present": chrono_binding.present,
            "header": binding_header.relative_to(output_dir).as_posix(),
            "manifest_asset_path": chrono_binding.manifest_packaged_path or None,
            "manifest_sha256": chrono_binding.manifest_sha256 or None,
            "profile_asset_path": chrono_binding.profile_packaged_path or None,
            "profile_sha256": chrono_binding.profile_sha256 or None,
            "asset_count": len(chrono_asset_receipts),
            "asset_bytes": sum(
                int(receipt["bytes"]) for receipt in chrono_asset_receipts
            ),
        },
        "chrono_substrate_runtime": {
            "present": chrono_binding_pack_inspection is not None,
            "asset": (
                CHRONO_BINDING_PACK_ASSET
                if chrono_binding_pack_inspection is not None
                else None
            ),
            "pack": chrono_binding_pack_inspection,
            "source_assets": chrono_substrate_asset_receipts,
            "source_asset_bytes": sum(
                int(receipt["bytes"])
                for receipt in chrono_substrate_asset_receipts
            ),
            "seed_boundary": (
                "root seed regenerates traversal; arbitrary observed pixels remain "
                "exact novelty evidence"
            ),
        },
        "transform_hierarchy_runtime": hierarchy_inspection,
        "visual_graph_runtime": graph_inspection,
        "packed_kinematic_runtime": polar_inspection,
        "polar_population_recipe_asset": polar_population_inspection,
        "population_runtime": scatter_inspection,
        "transform_animation_runtime": animation_inspection,
        "render_substrate_runtime": render_substrate_inspection,
        "compile_sdk": 36,
        "target_sdk": 36,
        "min_sdk": 26,
        "agp": "8.13.2",
        "gradle": "8.13",
        "ndk": "r29 / 29.0.14206865",
        "files_scope": "exported source inputs before Gradle build",
        "files_exclude": list(_ANDROID_TEMPLATE_VOLATILE_NAMES) + ["build-report.json"],
        "files": [
            {
                "path": path.relative_to(output_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _file_digest(path),
            }
            for path in files
        ],
    }
    report_path = output_dir / "build-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    files = sorted(path for path in output_dir.rglob("*") if path.is_file())
    return AndroidProjectBuild(
        output_dir=output_dir,
        project_file=project_file,
        scene_pack=scene_pack,
        build_report=report_path,
        file_count=len(files),
        total_bytes=sum(path.stat().st_size for path in files),
        project_hash=project.content_hash(),
        profile_hint=profile_hint,
        graph_pack=graph_pack,
        polar_pack=polar_pack,
        polar_population_pack=polar_population_pack,
        scatter_pack=scatter_pack,
        animation_pack=animation_pack,
        hierarchy_pack=hierarchy_pack,
        render_substrate_pack=render_substrate_pack,
        chrono_binding_pack=chrono_binding_pack,
    )


def write_mobile3d_gltf(project: Mobile3DProject, path: str | Path) -> dict:
    """Export the same project through the retained glTF interchange path."""
    project = _materialized_project(project)
    project.validate()
    return write_gltf(project.to_scene(), path, project.material_map())
