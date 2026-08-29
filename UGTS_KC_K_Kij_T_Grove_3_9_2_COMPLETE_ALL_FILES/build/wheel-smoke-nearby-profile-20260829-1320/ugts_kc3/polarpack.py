"""Deterministic sparse packed-log-polar asset for the native Android runtime.

The authoring API is deliberately small:

* ``project.metadata["packed_kinematic_profiles"]`` maps profile ids to the
  ``LogPolarProfile``/``MotionRange`` fields plus an optional
  ``lut_resolution`` (256 by default).
* ``node.metadata["packed_kinematic"]`` is a
  :class:`~ugts_kc3.packed_kinematics.PackedKinematicComponent` mapping.

Only nodes carrying the component are written.  Each referenced profile owns
one shared UGLUT2 binary16 table, so the native ``NodeData`` layout stays
unchanged and graph-free/non-polar projects gain no asset or runtime records.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import struct
from typing import Any, Mapping

from .packed_kinematics import (
    PackedKinematicCodec,
    PackedKinematicComponent,
    PolarLookupTable,
    packed_kinematic_codecs_from_dict,
)


POLAR_PACK_ASSET = "packed_kinematics.kcpk"
POLAR_PACK_MAGIC = b"KCPK392\0"
POLAR_PACK_ENDIAN = 0x01020304
POLAR_PACK_VERSION = 1
MAX_POLAR_PROFILES = 64
MAX_POLAR_COMPONENTS = 65535
MAX_LUT_RESOLUTION = 4096
MAX_POLAR_PACK_BYTES = 2 * 1024 * 1024


class PolarPackError(ValueError):
    """An authoring or binary-format error in a native polar pack."""


@dataclass(frozen=True)
class PolarProfileSpec:
    id: str
    codec: PackedKinematicCodec
    lut_resolution: int


@dataclass(frozen=True)
class PolarComponentSpec:
    node_index: int
    node_id: str
    component: PackedKinematicComponent


@dataclass(frozen=True)
class PolarProjectSpec:
    profiles: tuple[PolarProfileSpec, ...]
    components: tuple[PolarComponentSpec, ...]


def profile_lut_bytes(profile: PolarProfileSpec) -> bytes:
    """Build and validate the exact scaled UGLUT2 bytes used on Android."""
    try:
        data = PolarLookupTable.generate(
            profile.codec.profile, profile.lut_resolution
        ).to_bytes()
        PolarLookupTable.from_bytes(data)
        return data
    except (OverflowError, struct.error, ValueError) as error:
        raise PolarPackError(
            f"packed kinematic profile {profile.id!r} cannot form a finite UGLUT2: {error}"
        ) from error


def quantized_profile_lut(profile: PolarProfileSpec) -> PolarLookupTable:
    """Return the binary16-roundtripped table used by desktop preview."""
    return PolarLookupTable.from_bytes(profile_lut_bytes(profile))


def _profile_configs(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = metadata.get("packed_kinematic_profiles", {})
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise PolarPackError("metadata.packed_kinematic_profiles must be an object")
    if len(raw) > MAX_POLAR_PROFILES:
        raise PolarPackError(
            f"Android polar packs support at most {MAX_POLAR_PROFILES} profiles"
        )
    return raw


def _component(value: Any, node_id: str) -> PackedKinematicComponent:
    if isinstance(value, PackedKinematicComponent):
        result = value
    elif isinstance(value, Mapping):
        raw_profile = value.get("profile", "default")
        if not isinstance(raw_profile, str) or not raw_profile.strip():
            raise PolarPackError(
                f"node {node_id!r} packed_kinematic.profile must be nonempty text"
            )
        try:
            result = PackedKinematicComponent.from_dict(value)
        except (TypeError, ValueError) as error:
            raise PolarPackError(
                f"node {node_id!r} has malformed packed_kinematic words: {error}"
            ) from error
    else:
        raise PolarPackError(
            f"node {node_id!r} metadata.packed_kinematic must be an object"
        )
    try:
        result.validate()
    except (TypeError, ValueError) as error:
        raise PolarPackError(
            f"node {node_id!r} has malformed packed_kinematic words: {error}"
        ) from error
    if not isinstance(result.profile_id, str) or not result.profile_id.strip():
        raise PolarPackError(
            f"node {node_id!r} packed_kinematic.profile must be nonempty text"
        )
    # -32768 has no positive mirror in the codec's symmetric /32767 domain.
    # The Python encoder never emits it, so rejecting it makes malformed raw
    # words explicit instead of accepting a noncanonical value beyond range.
    for shift in (48, 32, 16, 0):
        if ((result.motion_word >> shift) & 0xFFFF) == 0x8000:
            raise PolarPackError(
                f"node {node_id!r} packed motion contains reserved signed code 0x8000"
            )
    return result


def collect_polar_project_spec(project: Any) -> PolarProjectSpec:
    """Validate authoring metadata and return a canonical sparse view.

    This helper intentionally does not call ``project.validate()`` so it can be
    used by :meth:`Mobile3DProject.validate` without recursion.
    """

    metadata = getattr(project, "metadata", {})
    if not isinstance(metadata, Mapping):
        raise PolarPackError("project metadata must be an object")
    raw_profiles = _profile_configs(metadata)
    try:
        codecs = packed_kinematic_codecs_from_dict(raw_profiles)
    except (TypeError, ValueError) as error:
        raise PolarPackError(f"invalid packed kinematic profile: {error}") from error

    resolutions: dict[str, int] = {"default": 256}
    for raw_id, raw_config in raw_profiles.items():
        profile_id = str(raw_id).strip()
        if not profile_id:
            raise PolarPackError("packed kinematic profile id cannot be empty")
        if not isinstance(raw_config, Mapping):
            raise PolarPackError(
                f"packed kinematic profile {profile_id!r} must be an object"
            )
        raw_resolution = raw_config.get("lut_resolution", 256)
        if isinstance(raw_resolution, bool) or not isinstance(raw_resolution, int):
            raise PolarPackError(
                f"packed kinematic profile {profile_id!r} lut_resolution must be an integer"
            )
        if not 16 <= raw_resolution <= MAX_LUT_RESOLUTION:
            raise PolarPackError(
                f"packed kinematic profile {profile_id!r} lut_resolution must be between "
                f"16 and {MAX_LUT_RESOLUTION}"
            )
        resolutions[profile_id] = raw_resolution

    components: list[PolarComponentSpec] = []
    for node_index, node in enumerate(getattr(project, "nodes", ())):
        raw = getattr(node, "metadata", {}).get("packed_kinematic")
        if raw is None:
            continue
        if len(components) >= MAX_POLAR_COMPONENTS:
            raise PolarPackError(
                f"Android polar packs support at most {MAX_POLAR_COMPONENTS} components"
            )
        component = _component(raw, str(node.id))
        if component.profile_id not in codecs:
            raise PolarPackError(
                f"node {node.id!r} references unknown packed kinematic profile "
                f"{component.profile_id!r}"
            )
        components.append(PolarComponentSpec(node_index, str(node.id), component))

    referenced = sorted(
        {item.component.profile_id for item in components},
        key=lambda value: value.encode("utf-8"),
    )
    if len(referenced) > MAX_POLAR_PROFILES:
        raise PolarPackError(
            f"Android polar packs support at most {MAX_POLAR_PROFILES} referenced profiles"
        )
    profiles = tuple(
        PolarProfileSpec(profile_id, codecs[profile_id], resolutions[profile_id])
        for profile_id in referenced
    )
    return PolarProjectSpec(profiles, tuple(components))


class _Writer:
    def __init__(self) -> None:
        self.data = bytearray()

    def raw(self, value: bytes) -> None:
        self.data.extend(value)

    def u16(self, value: int) -> None:
        self.raw(struct.pack("<H", value))

    def u32(self, value: int) -> None:
        self.raw(struct.pack("<I", value))

    def u64(self, value: int) -> None:
        self.raw(struct.pack("<Q", value))

    def f64(self, value: float) -> None:
        self.raw(struct.pack("<d", float(value)))

    def string(self, value: str) -> None:
        encoded = value.encode("utf-8")
        if not encoded or len(encoded) > 65535:
            raise PolarPackError("polar profile id must use 1..65535 UTF-8 bytes")
        self.u16(len(encoded))
        self.raw(encoded)


def compile_polar_pack_bytes(project: Any) -> bytes:
    """Compile one optional sparse KCPK asset, or ``b''`` when unused."""

    project.validate()
    spec = collect_polar_project_spec(project)
    if not spec.components:
        return b""
    writer = _Writer()
    writer.raw(POLAR_PACK_MAGIC)
    writer.u32(POLAR_PACK_ENDIAN)
    writer.u32(POLAR_PACK_VERSION)
    writer.u16(len(spec.profiles))
    writer.u16(0)
    writer.u32(len(spec.components))

    for profile in spec.profiles:
        writer.string(profile.id)
        motion = profile.codec.motion_range
        for value in (
            motion.rho_velocity,
            motion.theta_velocity,
            motion.rho_acceleration,
            motion.theta_acceleration,
        ):
            writer.f64(value)
        lut = profile_lut_bytes(profile)
        writer.u32(len(lut))
        writer.raw(lut)

    profile_indices = {profile.id: index for index, profile in enumerate(spec.profiles)}
    for item in spec.components:
        writer.u32(item.node_index)
        writer.u16(profile_indices[item.component.profile_id])
        writer.u16(0)
        writer.u64(item.component.pose_word)
        writer.u64(item.component.motion_word)

    result = bytes(writer.data)
    if len(result) > MAX_POLAR_PACK_BYTES:
        raise PolarPackError(
            f"Android polar pack is {len(result)} bytes; limit is {MAX_POLAR_PACK_BYTES}"
        )
    return result


def write_polar_pack(project: Any, path: str | Path) -> Path | None:
    data = compile_polar_pack_bytes(project)
    if not data:
        return None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class _Reader:
    def __init__(self, data: bytes):
        self.data = memoryview(data)
        self.offset = 0

    def raw(self, size: int) -> bytes:
        if size < 0 or self.offset + size > len(self.data):
            raise PolarPackError("truncated packed-kinematic asset")
        value = self.data[self.offset:self.offset + size].tobytes()
        self.offset += size
        return value

    def unpack(self, fmt: str) -> tuple[Any, ...]:
        return struct.unpack(fmt, self.raw(struct.calcsize(fmt)))

    def u16(self) -> int:
        return self.unpack("<H")[0]

    def u32(self) -> int:
        return self.unpack("<I")[0]

    def u64(self) -> int:
        return self.unpack("<Q")[0]

    def f64(self) -> float:
        return self.unpack("<d")[0]

    def string(self) -> str:
        size = self.u16()
        if size == 0:
            raise PolarPackError("packed-kinematic profile id cannot be empty")
        try:
            return self.raw(size).decode("utf-8")
        except UnicodeDecodeError as error:
            raise PolarPackError("packed-kinematic profile id is not UTF-8") from error


def inspect_polar_pack(
    data_or_path: bytes | str | Path, *, node_count: int | None = None
) -> dict[str, Any]:
    """Validate the complete KCPK structure and return compact diagnostics."""

    data = (
        Path(data_or_path).read_bytes()
        if isinstance(data_or_path, (str, Path))
        else bytes(data_or_path)
    )
    if len(data) > MAX_POLAR_PACK_BYTES:
        raise PolarPackError("packed-kinematic asset exceeds its byte limit")
    reader = _Reader(data)
    if reader.raw(8) != POLAR_PACK_MAGIC:
        raise PolarPackError("packed-kinematic magic mismatch")
    if reader.u32() != POLAR_PACK_ENDIAN:
        raise PolarPackError("packed-kinematic endian marker mismatch")
    if reader.u32() != POLAR_PACK_VERSION:
        raise PolarPackError("unsupported packed-kinematic version")
    profile_count = reader.u16()
    if reader.u16() != 0:
        raise PolarPackError("packed-kinematic header reserved field is nonzero")
    component_count = reader.u32()
    if not 1 <= profile_count <= MAX_POLAR_PROFILES:
        raise PolarPackError("packed-kinematic profile count is invalid")
    if not 1 <= component_count <= MAX_POLAR_COMPONENTS:
        raise PolarPackError("packed-kinematic component count is invalid")

    profiles: list[dict[str, Any]] = []
    previous_id: bytes | None = None
    for _ in range(profile_count):
        profile_id = reader.string()
        encoded_id = profile_id.encode("utf-8")
        if previous_id is not None and encoded_id <= previous_id:
            raise PolarPackError("packed-kinematic profiles are not canonical")
        previous_id = encoded_id
        motion_values = tuple(reader.f64() for _ in range(4))
        if any(not math.isfinite(value) or value <= 0 for value in motion_values):
            raise PolarPackError("packed-kinematic motion ranges must be positive and finite")
        lut_size = reader.u32()
        try:
            lut = PolarLookupTable.from_bytes(reader.raw(lut_size))
        except ValueError as error:
            raise PolarPackError(f"packed-kinematic UGLUT2 is invalid: {error}") from error
        if lut.resolution > MAX_LUT_RESOLUTION:
            raise PolarPackError("packed-kinematic LUT exceeds the native resolution limit")
        profiles.append(
            {
                "id": profile_id,
                "profile": lut.profile.to_dict(),
                "motion_range": {
                    "rho_velocity": motion_values[0],
                    "theta_velocity": motion_values[1],
                    "rho_acceleration": motion_values[2],
                    "theta_acceleration": motion_values[3],
                },
                "lut_resolution": lut.resolution,
                "lut_bytes": lut_size,
            }
        )

    components: list[dict[str, Any]] = []
    previous_node: int | None = None
    for _ in range(component_count):
        node_index, profile_index, reserved = reader.u32(), reader.u16(), reader.u16()
        pose_word, motion_word = reader.u64(), reader.u64()
        if reserved != 0:
            raise PolarPackError("packed-kinematic component reserved field is nonzero")
        if profile_index >= profile_count:
            raise PolarPackError("packed-kinematic component has an invalid profile index")
        if previous_node is not None and node_index <= previous_node:
            raise PolarPackError("packed-kinematic components are not sparse-canonical")
        if node_count is not None and node_index >= node_count:
            raise PolarPackError("packed-kinematic component has an invalid scene node index")
        previous_node = node_index
        for shift in (48, 32, 16, 0):
            if ((motion_word >> shift) & 0xFFFF) == 0x8000:
                raise PolarPackError("packed-kinematic motion uses reserved signed code 0x8000")
        components.append(
            {
                "node_index": node_index,
                "profile_index": profile_index,
                "profile": profiles[profile_index]["id"],
                "pose": f"{pose_word:016x}",
                "motion": f"{motion_word:016x}",
            }
        )
    if reader.offset != len(data):
        raise PolarPackError(
            f"packed-kinematic asset has {len(data) - reader.offset} trailing bytes"
        )
    return {
        "schema": "ugts-kc-native-packed-kinematics-inspection-3.9.2",
        "format_version": POLAR_PACK_VERSION,
        "byte_length": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "profile_count": profile_count,
        "component_count": component_count,
        "profiles": profiles,
        "components": components,
    }


__all__ = [
    "MAX_LUT_RESOLUTION",
    "MAX_POLAR_COMPONENTS",
    "MAX_POLAR_PACK_BYTES",
    "MAX_POLAR_PROFILES",
    "POLAR_PACK_ASSET",
    "POLAR_PACK_ENDIAN",
    "POLAR_PACK_MAGIC",
    "POLAR_PACK_VERSION",
    "PolarComponentSpec",
    "PolarPackError",
    "PolarProfileSpec",
    "PolarProjectSpec",
    "collect_polar_project_spec",
    "compile_polar_pack_bytes",
    "inspect_polar_pack",
    "profile_lut_bytes",
    "quantized_profile_lut",
    "write_polar_pack",
]
