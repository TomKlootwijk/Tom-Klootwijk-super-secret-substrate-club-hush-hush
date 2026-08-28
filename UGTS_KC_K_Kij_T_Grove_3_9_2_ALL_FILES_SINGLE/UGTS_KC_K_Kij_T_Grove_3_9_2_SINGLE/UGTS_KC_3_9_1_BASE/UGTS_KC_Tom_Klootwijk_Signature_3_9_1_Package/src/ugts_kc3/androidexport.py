"""Native Android project and compact scene-pack exporter for UGTS-KC 3.9.1."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import struct
from typing import Any

from .export import write_gltf
from .mobile3d import Mobile3DProject, tag_mask

PACK_MAGIC = b"KC3D391\0"
PACK_ENDIAN = 0x01020304
PACK_VERSION = 1


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
    if reader.raw(8) != PACK_MAGIC:
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
        "schema": "ugts-kc-native-scene-pack-inspection-3.9.1",
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


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_android_project(
    project: Mobile3DProject,
    output_dir: str | Path,
    profile_hint: str = "auto",
    clean: bool = True,
) -> AndroidProjectBuild:
    """Materialize a self-contained Android Studio/Gradle native source project."""
    project.validate()
    output_dir = Path(output_dir)
    template = Path(__file__).with_name("android_template") / "project"
    if not template.exists():
        raise FileNotFoundError(f"Android template missing: {template}")
    if output_dir.exists() and clean:
        shutil.rmtree(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output is not empty: {output_dir}")
    shutil.copytree(template, output_dir, dirs_exist_ok=True)

    strings_path = output_dir / "app/src/main/res/values/strings.xml"
    strings_path.write_text(
        strings_path.read_text("utf-8").replace("__APP_TITLE__", project.title),
        encoding="utf-8",
    )
    gradle_path = output_dir / "app/build.gradle"
    gradle_path.write_text(
        gradle_path.read_text("utf-8").replace(
            "__PROFILE_HINT__", profile_hint
        ),
        encoding="utf-8",
    )
    assets = output_dir / "app/src/main/assets"
    assets.mkdir(parents=True, exist_ok=True)
    project_file = project.write(assets / "project.json")
    scene_pack = write_scene_pack(project, assets / "signature_scene.kc3d")
    inspection = inspect_scene_pack(scene_pack)
    (assets / "scene-pack-inspection.json").write_text(
        json.dumps(inspection, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    files = sorted(path for path in output_dir.rglob("*") if path.is_file())
    report = {
        "schema": "ugts-kc-android-source-build-3.9.1",
        "edition": project.edition,
        "project_id": project.id,
        "project_hash": project.content_hash(),
        "profile_hint": profile_hint,
        "native_backend": "OpenGL ES 3.0 via Android NDK NativeActivity",
        "vulkan_status": "interface reserved; backend is a post-3.9.1 task",
        "compile_sdk": 36,
        "target_sdk": 36,
        "min_sdk": 26,
        "agp": "8.13.2",
        "gradle": "8.13",
        "ndk": "r29 / 29.0.14206865",
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
        output_dir, project_file, scene_pack, report_path, len(files),
        sum(path.stat().st_size for path in files),
        project.content_hash(), profile_hint,
    )


def write_mobile3d_gltf(project: Mobile3DProject, path: str | Path) -> dict:
    """Export the same project through the retained glTF interchange path."""
    project.validate()
    return write_gltf(project.to_scene(), path, project.material_map())
