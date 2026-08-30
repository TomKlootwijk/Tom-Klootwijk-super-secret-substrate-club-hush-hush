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
_LUT_MAGIC = b"UGLUT2"
_LUT_MAGIC_V1 = b"UGLUT1"
_MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


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

    def to_dict(self) -> dict[str, float]:
        return {
            "r0": self.r0,
            "rho_min": self.rho_min,
            "rho_max": self.rho_max,
            "core_radius": self.core_radius,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "LogPolarProfile":
        data = data or {}
        return cls(
            float(data.get("r0", 1.0)),
            float(data.get("rho_min", -12.0)),
            float(data.get("rho_max", 12.0)),
            float(data.get("core_radius", 1.0e-6)),
        )


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

    def to_dict(self) -> dict[str, float]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "MotionRange":
        data = data or {}
        return cls(
            float(data.get("rho_velocity", 16.0)),
            float(data.get("theta_velocity", 32.0)),
            float(data.get("rho_acceleration", 64.0)),
            float(data.get("theta_acceleration", 128.0)),
        )


@dataclass
class PackedKinematicComponent:
    """Two-word ECS component: quantized polar pose plus polar derivatives."""

    pose_word: int
    motion_word: int = 0
    profile_id: str = "default"

    def validate(self) -> None:
        if isinstance(self.pose_word, bool) or not isinstance(self.pose_word, int):
            raise TypeError("packed pose must be an integer unsigned 64-bit word")
        if not 0 <= self.pose_word < (1 << 64):
            raise ValueError("packed pose must be an unsigned 64-bit integer")
        if isinstance(self.motion_word, bool) or not isinstance(self.motion_word, int):
            raise TypeError("packed motion must be an integer unsigned 64-bit word")
        if not 0 <= self.motion_word < (1 << 64):
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
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                raise TypeError(f"packed {name} must be hexadecimal text or an integer")
            return int(value, 16) if isinstance(value, str) else value

        component = cls(word("pose"), word("motion"), str(data.get("profile", "default")))
        component.validate()
        return component


POLAR_MOVEMENT_FIELDS = (
    "radius",
    "angle_degrees",
    "facing_degrees",
    "turns_per_second",
    "growth_per_second",
    "turn_acceleration",
    "growth_acceleration",
)


def _binary32(value: float, label: str) -> float:
    """Enter the same finite scalar domain used by the Android graph VM."""

    try:
        result = struct.unpack("<f", struct.pack("<f", float(value)))[0]
    except (OverflowError, struct.error, TypeError, ValueError) as error:
        raise ValueError(f"{label} must fit a finite 32-bit number") from error
    if not math.isfinite(result):
        raise ValueError(f"{label} must fit a finite 32-bit number")
    return result


@dataclass
class PolarMovementComponent3D:
    """Friendly decoded view of one compact log-polar movement component.

    This view is deliberately virtual: snapshots and Android packs keep the
    existing two unsigned 64-bit words.  ``GameWorld3D.add_component`` commits
    an edited view back through the owning profile's quantizer.
    """

    radius: float
    angle_degrees: float
    facing_degrees: float
    turns_per_second: float
    growth_per_second: float
    turn_acceleration: float
    growth_acceleration: float

    def validate(self) -> None:
        for name in POLAR_MOVEMENT_FIELDS:
            setattr(self, name, _binary32(getattr(self, name), name.replace("_", " ")))

    def to_dict(self) -> dict[str, float]:
        self.validate()
        return {name: getattr(self, name) for name in POLAR_MOVEMENT_FIELDS}

    @classmethod
    def from_value(
        cls, value: "PolarMovementComponent3D | Mapping[str, Any]"
    ) -> "PolarMovementComponent3D":
        if isinstance(value, cls):
            result = cls(*(getattr(value, name) for name in POLAR_MOVEMENT_FIELDS))
        elif isinstance(value, Mapping):
            missing = [name for name in POLAR_MOVEMENT_FIELDS if name not in value]
            if missing:
                raise ValueError(
                    "polar movement needs every friendly field; missing "
                    + ", ".join(missing)
                )
            unknown = [name for name in value if name not in POLAR_MOVEMENT_FIELDS]
            if unknown:
                raise ValueError(
                    "polar movement has unknown fields: " + ", ".join(map(str, unknown))
                )
            result = cls(*(value[name] for name in POLAR_MOVEMENT_FIELDS))
        else:
            raise TypeError("polar movement must be a friendly component or mapping")
        result.validate()
        return result


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


def polar_movement_from_component(
    component: PackedKinematicComponent,
    codec: PackedKinematicCodec,
    lut: "PolarLookupTable | None" = None,
) -> PolarMovementComponent3D:
    """Decode the seven child-facing numbers from one quantized component."""

    component.validate()
    pose = codec.unpack_pose(component.pose_word)
    motion = codec.unpack_motion(component.motion_word)
    if lut is None:
        radius = codec.profile.r0 * math.exp(pose.rho)
    else:
        if lut.profile != codec.profile:
            raise ValueError("lookup table profile does not match the packed component codec")
        radius = lut.radius(pose.rho)
    movement = PolarMovementComponent3D(
        radius,
        math.degrees(pose.theta),
        math.degrees(pose.heading),
        motion.theta_velocity / TAU,
        motion.rho_velocity,
        motion.theta_acceleration / TAU,
        motion.rho_acceleration,
    )
    movement.validate()
    return movement


def _replace_word_bits(word: int, shift: int, width: int, code: int) -> int:
    mask = ((1 << width) - 1) << shift
    return (word & ~mask) | ((int(code) << shift) & mask)


def replace_polar_movement(
    component: PackedKinematicComponent,
    codec: PackedKinematicCodec,
    value: PolarMovementComponent3D | Mapping[str, Any],
    lut: "PolarLookupTable | None" = None,
) -> PackedKinematicComponent:
    """Re-encode edited friendly fields while preserving every untouched bit.

    Inputs enter binary32 before bounds checks, matching the native graph value
    domain.  The packed tick and any field not changed through the semantic view
    are retained bit-for-bit.
    """

    component.validate()
    target = PolarMovementComponent3D.from_value(value)
    current = polar_movement_from_component(component, codec, lut)
    pose_word = component.pose_word
    motion_word = component.motion_word

    if target.radius != current.radius:
        minimum = _binary32(
            codec.profile.r0 * math.exp(codec.profile.rho_min), "minimum radius"
        )
        maximum = _binary32(
            codec.profile.r0 * math.exp(codec.profile.rho_max), "maximum radius"
        )
        if not minimum <= target.radius <= maximum:
            raise ValueError(
                f"radius must stay between {minimum:g} and {maximum:g} for this movement profile"
            )
        rho = math.log(target.radius / codec.profile.r0)
        rho = _clamp(rho, codec.profile.rho_min, codec.profile.rho_max)
        rho_code = _quantize_closed(
            rho, codec.profile.rho_min, codec.profile.rho_max, _POSE_BITS[0]
        )
        pose_word = _replace_word_bits(pose_word, 44, 20, rho_code)

    if target.angle_degrees != current.angle_degrees:
        theta_code = _quantize_periodic(math.radians(target.angle_degrees), 18)
        pose_word = _replace_word_bits(pose_word, 26, 18, theta_code)

    if target.facing_degrees != current.facing_degrees:
        heading_code = _quantize_periodic(math.radians(target.facing_degrees), 12)
        pose_word = _replace_word_bits(pose_word, 0, 12, heading_code)

    motion_fields = (
        (
            "turns_per_second",
            32,
            codec.motion_range.theta_velocity / TAU,
            codec.motion_range.theta_velocity,
            TAU,
        ),
        (
            "growth_per_second",
            48,
            codec.motion_range.rho_velocity,
            codec.motion_range.rho_velocity,
            1.0,
        ),
        (
            "turn_acceleration",
            0,
            codec.motion_range.theta_acceleration / TAU,
            codec.motion_range.theta_acceleration,
            TAU,
        ),
        (
            "growth_acceleration",
            16,
            codec.motion_range.rho_acceleration,
            codec.motion_range.rho_acceleration,
            1.0,
        ),
    )
    for name, shift, friendly_limit, encoded_limit, multiplier in motion_fields:
        requested = getattr(target, name)
        if requested == getattr(current, name):
            continue
        limit = _binary32(friendly_limit, f"{name} limit")
        if abs(requested) > limit:
            raise ValueError(
                f"{name.replace('_', ' ')} must stay between {-limit:g} and {limit:g} "
                "for this movement profile"
            )
        code = _encode_signed(requested * multiplier, encoded_limit)
        motion_word = _replace_word_bits(motion_word, shift, 16, code)

    result = PackedKinematicComponent(
        pose_word, motion_word, component.profile_id
    )
    result.validate()
    return result


def packed_kinematic_codecs_from_dict(
    profiles: Mapping[str, Any] | None = None,
) -> dict[str, PackedKinematicCodec]:
    """Build an explicit profile-id registry for project/runtime composition."""
    result: dict[str, PackedKinematicCodec] = {"default": PackedKinematicCodec()}
    for raw_id, raw_config in (profiles or {}).items():
        profile_id = str(raw_id).strip()
        if not profile_id:
            raise ValueError("packed kinematic profile id cannot be empty")
        if not isinstance(raw_config, Mapping):
            raise TypeError(f"packed kinematic profile {profile_id!r} must be an object")
        profile_data = raw_config.get("profile", raw_config)
        motion_data = raw_config.get("motion_range", {})
        if not isinstance(profile_data, Mapping) or not isinstance(motion_data, Mapping):
            raise TypeError(f"packed kinematic profile {profile_id!r} fields must be objects")
        result[profile_id] = PackedKinematicCodec(
            LogPolarProfile.from_dict(profile_data), MotionRange.from_dict(motion_data)
        )
    return result


def make_packed_kinematic_system(
    codec: PackedKinematicCodec | None = None,
    lut: "PolarLookupTable | None" = None,
    *,
    codecs: Mapping[str, PackedKinematicCodec] | None = None,
    luts: Mapping[str, "PolarLookupTable"] | None = None,
):
    """Create a normal ``GameWorld`` system that composes packed motion with Transform2D.

    The callback uses public ECS query/component APIs only.  Keeping it as an
    ordinary system means a learner can remove, reorder, or replace it without
    hidden engine state.
    """
    if codec is not None and codecs is not None:
        raise ValueError("pass either one default codec or a profile codec registry, not both")
    codec_registry = dict(codecs or {"default": codec or PackedKinematicCodec()})
    lut_registry = dict(luts or {})
    if lut is not None:
        lut_registry.setdefault("default", lut)

    def packed_kinematic_system(world, dt: float, input_frame) -> None:
        del input_frame
        for entity in world.query("packed_kinematic"):
            packed = entity.components["packed_kinematic"]
            selected = codec_registry.get(packed.profile_id)
            if selected is None:
                raise ValueError(
                    f"packed kinematic component references unknown profile {packed.profile_id!r}"
                )
            selected_lut = lut_registry.get(packed.profile_id)
            advanced = selected.advance(packed, dt)
            entity.components["packed_kinematic"] = advanced
            transform = entity.components.get("transform")
            if transform is not None:
                state = selected.cartesian_state(advanced, selected_lut)
                transform.position = state["position"]
                transform.rotation = state["pose"].heading

    packed_kinematic_system.__name__ = "packed_polar_kinematics"
    return packed_kinematic_system


def attach_packed_kinematics(
    world,
    codec: PackedKinematicCodec | None = None,
    lut: "PolarLookupTable | None" = None,
    *,
    codecs: Mapping[str, PackedKinematicCodec] | None = None,
    luts: Mapping[str, "PolarLookupTable"] | None = None,
) -> bool:
    """Attach the packed system when a world contains at least one such component."""
    entities = world.query("packed_kinematic", active_only=False)
    if not entities:
        return False
    if codec is not None and codecs is not None:
        raise ValueError("pass either one default codec or a profile codec registry, not both")
    codec_registry = dict(codecs or {"default": codec or PackedKinematicCodec()})
    required_profiles = {
        entity.components["packed_kinematic"].profile_id for entity in entities
    }
    missing = sorted(required_profiles - set(codec_registry))
    if missing:
        raise ValueError(
            "packed kinematic components reference unknown profiles: " + ", ".join(missing)
        )
    lut_registry = dict(luts or {})
    if lut is not None:
        lut_registry.setdefault("default", lut)
    # Authoritative transforms must already match packed pose before ready
    # graphs run; advancing time remains the pre-physics system's job.
    for entity in entities:
        packed = entity.components["packed_kinematic"]
        selected = codec_registry[packed.profile_id]
        selected_lut = lut_registry.get(packed.profile_id)
        transform = entity.components.get("transform")
        if transform is not None:
            state = selected.cartesian_state(packed, selected_lut)
            transform.position = state["position"]
            transform.rotation = state["pose"].heading
    world.add_system(
        make_packed_kinematic_system(lut=lut, codecs=codec_registry, luts=luts),
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
        if not 16 <= int(self.resolution) <= 65535:
            raise ValueError("polar lookup resolution must be between 16 and 65535")
        if len(self.sine) != self.resolution or len(self.cosine) != self.resolution or len(self.radii) != self.resolution:
            raise ValueError("polar lookup arrays must match the declared resolution")
        if not all(
            math.isfinite(value)
            for values in (self.sine, self.cosine, self.radii)
            for value in values
        ):
            raise ValueError("polar lookup samples must be finite")
        if any(radius <= 0 for radius in self.radii):
            raise ValueError("polar lookup radius samples must be positive")
        if any(math.hypot(sine, cosine) <= 1.0e-9 for sine, cosine in zip(self.sine, self.cosine)):
            raise ValueError("polar lookup direction samples must be nonzero")

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
        # Binary16 tops out at 65,504 while the useful default log-radius
        # profile reaches exp(12).  One shared scale keeps all radius samples
        # representable without increasing the per-entry cost.
        radius_scale = max(1.0, max(self.radii) / 60000.0)
        header = struct.pack(
            "<6sHddddd",
            _LUT_MAGIC,
            self.resolution,
            self.profile.r0,
            self.profile.rho_min,
            self.profile.rho_max,
            self.profile.core_radius,
            radius_scale,
        )
        values = self.sine + self.cosine + tuple(radius / radius_scale for radius in self.radii)
        return header + struct.pack(f"<{len(values)}e", *values)

    @classmethod
    def from_bytes(cls, data: bytes) -> "PolarLookupTable":
        if len(data) < 6:
            raise ValueError("polar lookup data is truncated")
        magic = data[:6]
        if magic == _LUT_MAGIC:
            header_format = "<6sHddddd"
        elif magic == _LUT_MAGIC_V1:
            header_format = "<6sHdddd"
        else:
            raise ValueError("polar lookup magic does not match UGLUT1 or UGLUT2")
        header_size = struct.calcsize(header_format)
        if len(data) < header_size:
            raise ValueError("polar lookup data is truncated")
        header = struct.unpack(header_format, data[:header_size])
        _, resolution, r0, rho_min, rho_max, core_radius, *extra = header
        radius_scale = float(extra[0]) if extra else 1.0
        if not math.isfinite(radius_scale) or radius_scale <= 0:
            raise ValueError("polar lookup radius scale must be positive and finite")
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
            tuple(radius * radius_scale for radius in values[resolution * 2:]),
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
    if len(raw) > _MAX_ARCHIVE_BYTES:
        raise ValueError("ECS document exceeds the 256 MiB packed-format safety limit")
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
    if raw_length > _MAX_ARCHIVE_BYTES:
        raise ValueError("packed ECS document exceeds the 256 MiB safety limit")
    try:
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(data[header_size:], raw_length + 1)
    except zlib.error as exc:
        raise ValueError(f"packed ECS document is corrupt: {exc}") from exc
    if len(raw) > raw_length:
        raise ValueError("packed ECS document expands beyond its declared length")
    if not decompressor.eof:
        raise ValueError("packed ECS document has a truncated or oversized DEFLATE stream")
    if decompressor.unused_data or decompressor.unconsumed_tail:
        raise ValueError("packed ECS document has trailing bytes after its DEFLATE stream")
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
