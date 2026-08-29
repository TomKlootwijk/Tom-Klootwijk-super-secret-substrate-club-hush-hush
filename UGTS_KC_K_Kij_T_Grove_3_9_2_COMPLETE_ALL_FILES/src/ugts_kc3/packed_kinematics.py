"""Compact log-polar kinematic components and compressed ECS documents.

This module distils the useful, bounded part of the UGTS SCLP 3.6.2 work into
game-engine records.  A polar pose occupies one 64-bit word and its first and
second derivatives occupy a second word.  A small binary16 lookup table can be
shared by every entity; it is a storage/determinism option, not an unconditional
claim that lookup beats native trigonometric instructions on every GPU.

The archive helpers use canonical JSON plus raw DEFLATE.  That keeps authored
projects inspectable while making deployed ECS/graph data compact without a
third-party codec or an opaque executable serializer.
"""
from __future__ import annotations

from dataclasses import dataclass
import binascii
import json
import math
import struct
from typing import Any, Mapping
import zlib


TAU = math.tau
_POSE_BITS = (20, 18, 14, 12)  # log-radius, angle, tick, heading
_POSE_MAGIC = b"UGPL1"
_ARCHIVE_MAGIC = b"UGECS1"
_LUT_MAGIC = b"UGLUT1"


def _finite(value: float, label: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return value


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _quantize_closed(value: float, minimum: float, maximum: float, bits: int) -> int:
    value = _clamp(_finite(value, "value"), minimum, maximum)
    maximum_code = (1 << bits) - 1
    unit = (value - minimum) / (maximum - minimum)
    return min(maximum_code, max(0, int(round(unit * maximum_code))))


def _dequantize_closed(code: int, minimum: float, maximum: float, bits: int) -> float:
    maximum_code = (1 << bits) - 1
    if not 0 <= int(code) <= maximum_code:
        raise ValueError(f"{bits}-bit code is out of range: {code}")
    return minimum + (maximum - minimum) * (int(code) / maximum_code)


def _quantize_periodic(value: float, bits: int) -> int:
    unit = (_finite(value, "angle") % TAU) / TAU
    return int(math.floor(unit * (1 << bits))) & ((1 << bits) - 1)


def _dequantize_periodic(code: int, bits: int) -> float:
    mask = (1 << bits) - 1
    if not 0 <= int(code) <= mask:
        raise ValueError(f"{bits}-bit periodic code is out of range: {code}")
    return TAU * int(code) / (1 << bits)


def _encode_signed(value: float, maximum_magnitude: float) -> int:
    maximum_magnitude = _finite(maximum_magnitude, "maximum magnitude")
    if maximum_magnitude <= 0:
        raise ValueError("maximum magnitude must be positive")
    normalized = _clamp(_finite(value, "motion value") / maximum_magnitude, -1.0, 1.0)
    signed = int(round(normalized * 32767.0))
    return signed & 0xFFFF


def _decode_signed(code: int, maximum_magnitude: float) -> float:
    code = int(code)
    if not 0 <= code <= 0xFFFF:
        raise ValueError(f"16-bit motion code is out of range: {code}")
    signed = code - 0x10000 if code & 0x8000 else code
    return (signed / 32767.0) * float(maximum_magnitude)


@dataclass(frozen=True)
class LogPolarProfile:
    """Quantization domain shared by packed poses and their lookup table."""

    r0: float = 1.0
    rho_min: float = -12.0
    rho_max: float = 12.0
    core_radius: float = 1.0e-6

    def __post_init__(self) -> None:
        if _finite(self.r0, "reference radius") <= 0:
            raise ValueError("reference radius must be positive")
        if _finite(self.rho_min, "minimum log radius") >= _finite(self.rho_max, "maximum log radius"):
            raise ValueError("minimum log radius must be smaller than maximum log radius")
        if _finite(self.core_radius, "core radius") <= 0:
            raise ValueError("core radius must be positive")

    def encode_cartesian(self, x: float, y: float) -> tuple[float, float, bool]:
        radius = math.hypot(_finite(x, "x"), _finite(y, "y"))
        if radius < self.core_radius:
            return self.rho_min, 0.0, True
        rho = math.log(radius / self.r0)
        return _clamp(rho, self.rho_min, self.rho_max), math.atan2(y, x), False

    def decode_cartesian(self, rho: float, theta: float) -> tuple[float, float]:
        radius = self.r0 * math.exp(_clamp(float(rho), self.rho_min, self.rho_max))
        return radius * math.cos(theta), radius * math.sin(theta)


@dataclass(frozen=True)
class PolarPose:
    rho: float
    theta: float
    tick: int = 0
    heading: float = 0.0


@dataclass(frozen=True)
class PolarMotion:
    rho_velocity: float = 0.0
    theta_velocity: float = 0.0
    rho_acceleration: float = 0.0
    theta_acceleration: float = 0.0


@dataclass(frozen=True)
class MotionRange:
    rho_velocity: float = 16.0
    theta_velocity: float = 32.0
    rho_acceleration: float = 64.0
    theta_acceleration: float = 128.0

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if _finite(value, name.replace("_", " ")) <= 0:
                raise ValueError(f"{name.replace('_', ' ')} range must be positive")


@dataclass
class PackedKinematicComponent:
    """Two-word ECS component: quantized polar pose plus polar derivatives."""

    pose_word: int
    motion_word: int = 0
    profile_id: str = "default"

    def validate(self) -> None:
        if not 0 <= int(self.pose_word) < (1 << 64):
            raise ValueError("packed pose must be an unsigned 64-bit integer")
        if not 0 <= int(self.motion_word) < (1 << 64):
            raise ValueError("packed motion must be an unsigned 64-bit integer")
        if not self.profile_id:
            raise ValueError("packed kinematic profile id is required")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "pose": f"{self.pose_word:016x}",
            "motion": f"{self.motion_word:016x}",
            "profile": self.profile_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PackedKinematicComponent":
        def word(name: str) -> int:
            value = data.get(name, "0")
            return int(value, 16) if isinstance(value, str) else int(value)

        component = cls(word("pose"), word("motion"), str(data.get("profile", "default")))
        component.validate()
        return component


class PackedKinematicCodec:
    """Encode/decode the two 64-bit words used by ``PackedKinematicComponent``."""

    def __init__(
        self,
        profile: LogPolarProfile | None = None,
        motion_range: MotionRange | None = None,
    ) -> None:
        self.profile = profile or LogPolarProfile()
        self.motion_range = motion_range or MotionRange()

    def pack_pose(self, pose: PolarPose) -> int:
        rho_bits, theta_bits, tick_bits, heading_bits = _POSE_BITS
        rho = _quantize_closed(pose.rho, self.profile.rho_min, self.profile.rho_max, rho_bits)
        theta = _quantize_periodic(pose.theta, theta_bits)
        tick = int(pose.tick) & ((1 << tick_bits) - 1)
        heading = _quantize_periodic(pose.heading, heading_bits)
        return (
            (rho << (theta_bits + tick_bits + heading_bits))
            | (theta << (tick_bits + heading_bits))
            | (tick << heading_bits)
            | heading
        )

    def unpack_pose(self, word: int) -> PolarPose:
        word = self._word(word, "pose")
        rho_bits, theta_bits, tick_bits, heading_bits = _POSE_BITS
        heading_mask = (1 << heading_bits) - 1
        tick_mask = (1 << tick_bits) - 1
        theta_mask = (1 << theta_bits) - 1
        heading = word & heading_mask
        tick = (word >> heading_bits) & tick_mask
        theta = (word >> (heading_bits + tick_bits)) & theta_mask
        rho = word >> (heading_bits + tick_bits + theta_bits)
        return PolarPose(
            _dequantize_closed(rho, self.profile.rho_min, self.profile.rho_max, rho_bits),
            _dequantize_periodic(theta, theta_bits),
            tick,
            _dequantize_periodic(heading, heading_bits),
        )

    def pack_motion(self, motion: PolarMotion) -> int:
        limits = self.motion_range
        values = (
            _encode_signed(motion.rho_velocity, limits.rho_velocity),
            _encode_signed(motion.theta_velocity, limits.theta_velocity),
            _encode_signed(motion.rho_acceleration, limits.rho_acceleration),
            _encode_signed(motion.theta_acceleration, limits.theta_acceleration),
        )
        word = 0
        for value in values:
            word = (word << 16) | value
        return word

    def unpack_motion(self, word: int) -> PolarMotion:
        word = self._word(word, "motion")
        codes = tuple((word >> shift) & 0xFFFF for shift in (48, 32, 16, 0))
        limits = self.motion_range
        return PolarMotion(
            _decode_signed(codes[0], limits.rho_velocity),
            _decode_signed(codes[1], limits.theta_velocity),
            _decode_signed(codes[2], limits.rho_acceleration),
            _decode_signed(codes[3], limits.theta_acceleration),
        )

    def component(
        self,
        pose: PolarPose,
        motion: PolarMotion | None = None,
        *,
        profile_id: str = "default",
    ) -> PackedKinematicComponent:
        return PackedKinematicComponent(
            self.pack_pose(pose), self.pack_motion(motion or PolarMotion()), profile_id
        )

    def cartesian_state(
        self,
        component: PackedKinematicComponent,
        lut: "PolarLookupTable | None" = None,
    ) -> dict[str, tuple[float, float] | PolarPose | PolarMotion]:
        component.validate()
        pose = self.unpack_pose(component.pose_word)
        motion = self.unpack_motion(component.motion_word)
        if lut is None:
            radius = self.profile.r0 * math.exp(pose.rho)
            sine, cosine = math.sin(pose.theta), math.cos(pose.theta)
        else:
            if lut.profile != self.profile:
                raise ValueError("lookup table profile does not match the packed component codec")
            radius = lut.radius(pose.rho)
            sine, cosine = lut.sin_cos(pose.theta)
        radial = (cosine, sine)
        tangent = (-sine, cosine)
        position = (radius * radial[0], radius * radial[1])
        velocity = (
            radius * (motion.rho_velocity * radial[0] + motion.theta_velocity * tangent[0]),
            radius * (motion.rho_velocity * radial[1] + motion.theta_velocity * tangent[1]),
        )
        radial_acceleration = (
            motion.rho_acceleration
            + motion.rho_velocity * motion.rho_velocity
            - motion.theta_velocity * motion.theta_velocity
        )
        tangent_acceleration = (
            motion.theta_acceleration
            + 2.0 * motion.rho_velocity * motion.theta_velocity
        )
        acceleration = (
            radius * (radial_acceleration * radial[0] + tangent_acceleration * tangent[0]),
            radius * (radial_acceleration * radial[1] + tangent_acceleration * tangent[1]),
        )
        return {
            "pose": pose,
            "motion": motion,
            "position": position,
            "velocity": velocity,
            "acceleration": acceleration,
        }

    def advance(
        self,
        component: PackedKinematicComponent,
        dt: float,
    ) -> PackedKinematicComponent:
        """Advance one packed component with bounded semi-implicit kinematics."""
        dt = _finite(dt, "time step")
        if dt <= 0:
            raise ValueError("time step must be positive")
        pose = self.unpack_pose(component.pose_word)
        motion = self.unpack_motion(component.motion_word)
        rho_velocity = motion.rho_velocity + motion.rho_acceleration * dt
        theta_velocity = motion.theta_velocity + motion.theta_acceleration * dt
        next_motion = PolarMotion(
            rho_velocity,
            theta_velocity,
            motion.rho_acceleration,
            motion.theta_acceleration,
        )
        next_pose = PolarPose(
            _clamp(pose.rho + rho_velocity * dt, self.profile.rho_min, self.profile.rho_max),
            (pose.theta + theta_velocity * dt) % TAU,
            pose.tick + 1,
            (pose.heading + theta_velocity * dt) % TAU,
        )
        return self.component(next_pose, next_motion, profile_id=component.profile_id)

    @staticmethod
    def _word(word: int, label: str) -> int:
        word = int(word)
        if not 0 <= word < (1 << 64):
            raise ValueError(f"packed {label} must be an unsigned 64-bit integer")
        return word


def make_packed_kinematic_system(
    codec: PackedKinematicCodec | None = None,
    lut: "PolarLookupTable | None" = None,
):
    """Create a normal ``GameWorld`` system that composes packed motion with Transform2D.

    The callback uses public ECS query/component APIs only.  Keeping it as an
    ordinary system means a learner can remove, reorder, or replace it without
    hidden engine state.
    """
    codec = codec or PackedKinematicCodec()

    def packed_kinematic_system(world, dt: float, input_frame) -> None:
        del input_frame
        for entity in world.query("packed_kinematic"):
            packed = entity.components["packed_kinematic"]
            advanced = codec.advance(packed, dt)
            entity.components["packed_kinematic"] = advanced
            transform = entity.components.get("transform")
            if transform is not None:
                state = codec.cartesian_state(advanced, lut)
                transform.position = state["position"]
                transform.rotation = state["pose"].heading

    packed_kinematic_system.__name__ = "packed_polar_kinematics"
    return packed_kinematic_system


def attach_packed_kinematics(
    world,
    codec: PackedKinematicCodec | None = None,
    lut: "PolarLookupTable | None" = None,
) -> bool:
    """Attach the packed system when a world contains at least one such component."""
    if not world.query("packed_kinematic", active_only=False):
        return False
    world.add_system(
        make_packed_kinematic_system(codec, lut),
        phase="pre_physics",
        priority=-100,
        name="packed_polar_kinematics",
    )
    return True


@dataclass(frozen=True)
class PolarLookupTable:
    """Small shared binary16 LUT with linear interpolation and bounded domains."""

    profile: LogPolarProfile
    resolution: int
    sine: tuple[float, ...]
    cosine: tuple[float, ...]
    radii: tuple[float, ...]

    @classmethod
    def generate(
        cls, profile: LogPolarProfile | None = None, resolution: int = 256
    ) -> "PolarLookupTable":
        profile = profile or LogPolarProfile()
        if not 16 <= int(resolution) <= 65535:
            raise ValueError("polar lookup resolution must be between 16 and 65535")
        resolution = int(resolution)
        angles = (TAU * index / resolution for index in range(resolution))
        pairs = tuple((math.sin(angle), math.cos(angle)) for angle in angles)
        radii = tuple(
            profile.r0 * math.exp(
                profile.rho_min
                + (profile.rho_max - profile.rho_min) * index / (resolution - 1)
            )
            for index in range(resolution)
        )
        return cls(
            profile,
            resolution,
            tuple(pair[0] for pair in pairs),
            tuple(pair[1] for pair in pairs),
            radii,
        )

    def __post_init__(self) -> None:
        if len(self.sine) != self.resolution or len(self.cosine) != self.resolution or len(self.radii) != self.resolution:
            raise ValueError("polar lookup arrays must match the declared resolution")

    def sin_cos(self, theta: float) -> tuple[float, float]:
        coordinate = (_finite(theta, "angle") % TAU) * self.resolution / TAU
        low = int(math.floor(coordinate)) % self.resolution
        high = (low + 1) % self.resolution
        fraction = coordinate - math.floor(coordinate)
        sine = self.sine[low] + (self.sine[high] - self.sine[low]) * fraction
        cosine = self.cosine[low] + (self.cosine[high] - self.cosine[low]) * fraction
        length = math.hypot(sine, cosine)
        return sine / length, cosine / length

    def radius(self, rho: float) -> float:
        rho = _clamp(_finite(rho, "log radius"), self.profile.rho_min, self.profile.rho_max)
        coordinate = (rho - self.profile.rho_min) * (self.resolution - 1) / (self.profile.rho_max - self.profile.rho_min)
        low = int(math.floor(coordinate))
        high = min(self.resolution - 1, low + 1)
        fraction = coordinate - low
        return self.radii[low] + (self.radii[high] - self.radii[low]) * fraction

    def to_bytes(self) -> bytes:
        header = struct.pack(
            "<6sHdddd",
            _LUT_MAGIC,
            self.resolution,
            self.profile.r0,
            self.profile.rho_min,
            self.profile.rho_max,
            self.profile.core_radius,
        )
        values = self.sine + self.cosine + self.radii
        return header + struct.pack(f"<{len(values)}e", *values)

    @classmethod
    def from_bytes(cls, data: bytes) -> "PolarLookupTable":
        header_format = "<6sHdddd"
        header_size = struct.calcsize(header_format)
        if len(data) < header_size:
            raise ValueError("polar lookup data is truncated")
        magic, resolution, r0, rho_min, rho_max, core_radius = struct.unpack(
            header_format, data[:header_size]
        )
        if magic != _LUT_MAGIC:
            raise ValueError("polar lookup magic does not match UGLUT1")
        count = int(resolution) * 3
        expected = header_size + count * 2
        if len(data) != expected:
            raise ValueError(f"polar lookup length is {len(data)} bytes; expected {expected}")
        values = struct.unpack(f"<{count}e", data[header_size:])
        return cls(
            LogPolarProfile(r0, rho_min, rho_max, core_radius),
            resolution,
            tuple(values[:resolution]),
            tuple(values[resolution:resolution * 2]),
            tuple(values[resolution * 2:]),
        )


def canonical_document_bytes(document: Mapping[str, Any]) -> bytes:
    """Return stable, whitespace-free UTF-8 JSON suitable for hashing/packing."""
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def pack_ecs_document(document: Mapping[str, Any], level: int = 9) -> bytes:
    """Pack an ECS/project/graph mapping into a checksummed UGECS1 payload."""
    if not 0 <= int(level) <= 9:
        raise ValueError("DEFLATE level must be between 0 and 9")
    raw = canonical_document_bytes(document)
    compressed = zlib.compress(raw, int(level))
    checksum = binascii.crc32(raw) & 0xFFFFFFFF
    return _ARCHIVE_MAGIC + struct.pack("<II", len(raw), checksum) + compressed


def unpack_ecs_document(data: bytes) -> dict[str, Any]:
    """Validate and unpack one UGECS1 payload."""
    header_size = len(_ARCHIVE_MAGIC) + 8
    if len(data) < header_size or data[:len(_ARCHIVE_MAGIC)] != _ARCHIVE_MAGIC:
        raise ValueError("packed ECS document does not start with UGECS1")
    raw_length, expected_checksum = struct.unpack(
        "<II", data[len(_ARCHIVE_MAGIC):header_size]
    )
    try:
        raw = zlib.decompress(data[header_size:])
    except zlib.error as exc:
        raise ValueError(f"packed ECS document is corrupt: {exc}") from exc
    if len(raw) != raw_length:
        raise ValueError(
            f"packed ECS length mismatch: decoded {len(raw)}, expected {raw_length}"
        )
    checksum = binascii.crc32(raw) & 0xFFFFFFFF
    if checksum != expected_checksum:
        raise ValueError("packed ECS checksum mismatch")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("packed ECS root must be a JSON object")
    return value
