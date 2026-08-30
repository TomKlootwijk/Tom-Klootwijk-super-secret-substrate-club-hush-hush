"""Compact relative transform animation for Mobile 3D projects.

The original ``transform_animation`` metadata remains a byte-stable one-clip
autoplay contract.  ``transform_animation_library`` adds a bounded collection
of named rigid-transform clips without changing the relative-pose rules used
by the editor, desktop ECS, or native runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
import struct
from typing import Any, Mapping, Sequence

from .animation import easing
from .math3d import add, quat_mul, quat_nlerp, quat_normalize


ANIMATION_METADATA_KEY = "transform_animation"
TRANSFORM_ANIMATION_SCHEMA = "ugts-transform-animation-1"
ANIMATION_LIBRARY_METADATA_KEY = "transform_animation_library"
TRANSFORM_ANIMATION_LIBRARY_SCHEMA = "ugts-transform-animation-library-1"
DEFAULT_ANIMATION_CLIP_ID = "main"
DEFAULT_ANIMATION_CLIP_LABEL = "Main"
ANIMATION_CLIP_ID_PATTERN = r"[a-z][a-z0-9_.-]{0,31}"
ANIMATION_EASINGS = (
    "linear",
    "step",
    "ease_in",
    "ease_out",
    "ease_in_out",
    "smoothstep",
    "smootherstep",
    "back_out",
    "elastic_out",
)
ANIMATION_LOOP_MODES = ("once", "loop", "pingpong")

MAX_ANIMATED_NODES = 64
MAX_ANIMATION_KEYS_PER_NODE = 128
MAX_ANIMATION_KEYS_PER_CLIP = MAX_ANIMATION_KEYS_PER_NODE
MAX_ANIMATION_KEYS_TOTAL = 4096
MAX_ANIMATION_CLIPS_PER_NODE = 16
MAX_ANIMATION_CLIPS_TOTAL = 256
MAX_ANIMATION_DURATION = 120.0
MAX_ANIMATION_TRANSLATION = 4096.0
MAX_ANIMATION_SCALE = 64.0
MIN_ANIMATION_SCALE = 1.0 / 1024.0


class TransformAnimationError(ValueError):
    """Invalid Mobile 3D transform-animation authoring data."""


def _values(value: Any, count: int, label: str) -> tuple[float, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) != count
    ):
        raise TransformAnimationError(f"{label} requires {count} numbers")
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise TransformAnimationError(f"{label} requires {count} numbers") from exc
    if not all(math.isfinite(item) for item in result):
        raise TransformAnimationError(f"{label} must be finite")
    return result


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _f16(value: float, label: str) -> float:
    try:
        result = struct.unpack("<e", struct.pack("<e", float(value)))[0]
    except (OverflowError, struct.error) as exc:
        raise TransformAnimationError(
            f"{label} is outside the compact animation range"
        ) from exc
    if not math.isfinite(result):
        raise TransformAnimationError(f"{label} is outside the compact animation range")
    return result


def _time_code(time: float, duration: float) -> int:
    return int(round(max(0.0, min(duration, time)) / duration * 65535.0))


def _quantize_rotation(
    rotation: Sequence[float],
) -> tuple[float, float, float, float]:
    """Return the binary16 payload Android normalizes after decoding."""

    try:
        normalized = quat_normalize(rotation)
    except ValueError as exc:
        raise TransformAnimationError(
            "animation key turn collapsed in the compact phone format"
        ) from exc
    payload = tuple(_f16(value, "animation key turn") for value in normalized)
    try:
        quat_normalize(payload)
    except ValueError as exc:
        raise TransformAnimationError(
            "animation key turn collapsed in the compact phone format"
        ) from exc
    return payload  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class TransformKey3D:
    """One relative pose; easing describes how the pose is approached."""

    time: float
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    easing: str = "smoothstep"
    _packed_rotation: tuple[float, float, float, float] | None = field(
        default=None,
        init=False,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        time = float(self.time)
        if not math.isfinite(time) or time < 0.0:
            raise TransformAnimationError(
                "animation key time must be finite and non-negative"
            )
        translation = _values(self.translation, 3, "animation key position")
        rotation = _values(self.rotation, 4, "animation key turn")
        scale = _values(self.scale, 3, "animation key size")
        try:
            normalized = quat_normalize(rotation)
        except ValueError as exc:
            raise TransformAnimationError(
                "animation key turn cannot be a zero quaternion"
            ) from exc
        if any(abs(value) > MAX_ANIMATION_TRANSLATION for value in translation):
            raise TransformAnimationError(
                f"animation key position offsets must stay within {MAX_ANIMATION_TRANSLATION:g}"
            )
        if any(
            value < MIN_ANIMATION_SCALE or value > MAX_ANIMATION_SCALE
            for value in scale
        ):
            raise TransformAnimationError(
                "animation key size multipliers must stay away from zero and within "
                f"{MAX_ANIMATION_SCALE:g}"
            )
        if self.easing not in ANIMATION_EASINGS:
            raise TransformAnimationError(
                f"unsupported animation easing: {self.easing}"
            )
        object.__setattr__(self, "time", time)
        object.__setattr__(self, "translation", translation)
        object.__setattr__(self, "rotation", normalized)
        object.__setattr__(self, "scale", scale)

    def to_dict(self) -> dict[str, Any]:
        return {
            "time": self.time,
            "translation": list(self.translation),
            "rotation": list(self.rotation),
            "scale": list(self.scale),
            "easing": self.easing,
        }

    @property
    def packed_rotation(self) -> tuple[float, float, float, float] | None:
        """Internal KCAN quaternion payload, present only after quantization."""

        return self._packed_rotation

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TransformKey3D":
        if not isinstance(data, Mapping):
            raise TransformAnimationError("each animation key must be an object")
        unknown = set(data) - {"time", "translation", "rotation", "scale", "easing"}
        if unknown:
            raise TransformAnimationError(
                "animation key contains unsupported fields: "
                + ", ".join(sorted(unknown))
            )
        if "time" not in data:
            raise TransformAnimationError("animation key time is required")
        return cls(
            float(data["time"]),
            _values(data.get("translation", (0, 0, 0)), 3, "animation key position"),
            _values(data.get("rotation", (1, 0, 0, 0)), 4, "animation key turn"),
            _values(data.get("scale", (1, 1, 1)), 3, "animation key size"),
            str(data.get("easing", "smoothstep")),
        )


@dataclass(frozen=True, slots=True)
class TransformAnimation3D:
    duration: float
    keys: tuple[TransformKey3D, ...]
    loop_mode: str = "once"
    schema: str = TRANSFORM_ANIMATION_SCHEMA

    def validate(self) -> None:
        if self.schema != TRANSFORM_ANIMATION_SCHEMA:
            raise TransformAnimationError(
                f"animation schema must be {TRANSFORM_ANIMATION_SCHEMA}"
            )
        duration = float(self.duration)
        if (
            not math.isfinite(duration)
            or duration < 1.0 / 60.0
            or duration > MAX_ANIMATION_DURATION
        ):
            raise TransformAnimationError(
                f"animation length must be between 1/60 and {MAX_ANIMATION_DURATION:g} seconds"
            )
        if self.loop_mode not in ANIMATION_LOOP_MODES:
            raise TransformAnimationError(
                "animation repeat must be once, loop, or pingpong"
            )
        if not 1 <= len(self.keys) <= MAX_ANIMATION_KEYS_PER_NODE:
            raise TransformAnimationError(
                f"animation needs 1 to {MAX_ANIMATION_KEYS_PER_NODE} keys"
            )
        times = [key.time for key in self.keys]
        if times != sorted(times) or len(times) != len(set(times)):
            raise TransformAnimationError(
                "animation keys must have unique increasing times"
            )
        if times[0] != 0.0:
            raise TransformAnimationError(
                "the first animation key must be at 0 seconds"
            )
        if times[-1] > duration:
            raise TransformAnimationError(
                "an animation key is later than the animation length"
            )
        first = self.keys[0]
        identity = (
            first.translation == (0.0, 0.0, 0.0)
            and first.rotation == (1.0, 0.0, 0.0, 0.0)
            and first.scale == (1.0, 1.0, 1.0)
        )
        if not identity:
            raise TransformAnimationError(
                "the first animation key must keep the object's starting pose"
            )
        codes = [_time_code(time, duration) for time in times]
        if len(codes) != len(set(codes)):
            raise TransformAnimationError(
                "two animation keys are too close together for the compact phone format"
            )
        easing_upper = {"back_out": 1.101, "elastic_out": 1.374}
        for left, right in zip(self.keys, self.keys[1:]):
            upper = easing_upper.get(right.easing, 1.0)
            for first_scale, second_scale in zip(left.scale, right.scale):
                extreme = first_scale + (second_scale - first_scale) * upper
                if not math.isfinite(extreme) or extreme < MIN_ANIMATION_SCALE:
                    raise TransformAnimationError(
                        "animation easing would make an object's size cross zero"
                    )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "duration": self.duration,
            "loop_mode": self.loop_mode,
            "keys": [key.to_dict() for key in self.keys],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TransformAnimation3D":
        if not isinstance(data, Mapping):
            raise TransformAnimationError("transform_animation must be an object")
        unknown = set(data) - {"schema", "duration", "loop_mode", "keys"}
        if unknown:
            raise TransformAnimationError(
                "transform_animation contains unsupported fields: "
                + ", ".join(sorted(unknown))
            )
        raw_keys = data.get("keys")
        if not isinstance(raw_keys, (list, tuple)):
            raise TransformAnimationError("transform_animation keys must be a list")
        try:
            duration = float(data.get("duration", 2.0))
        except (TypeError, ValueError) as exc:
            raise TransformAnimationError("animation length must be a number") from exc
        result = cls(
            duration,
            tuple(TransformKey3D.from_dict(item) for item in raw_keys),
            str(data.get("loop_mode", "once")),
            str(data.get("schema", "")),
        )
        result.validate()
        return result


def _validated_clip_id(value: Any) -> str:
    clip_id = str(value)
    if re.fullmatch(ANIMATION_CLIP_ID_PATTERN, clip_id, flags=re.ASCII) is None:
        raise TransformAnimationError(
            "animation clip id must start with a lowercase letter, use only "
            "lowercase ASCII letters, digits, dot, underscore, or hyphen, and be at most "
            "32 characters"
        )
    return clip_id


def animation_clip_hash(clip_id: str) -> int:
    """Return the portable unsigned 64-bit FNV-1a hash for one clip id."""

    value = _validated_clip_id(clip_id)
    result = 0xCBF29CE484222325
    for byte in value.encode("ascii"):
        result ^= byte
        result = (result * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return result


@dataclass(frozen=True, slots=True)
class TransformClip3D:
    """One stable child-readable name bound to a relative transform clip."""

    id: str
    label: str
    animation: TransformAnimation3D

    def __post_init__(self) -> None:
        clip_id = _validated_clip_id(self.id)
        label = str(self.label).strip()
        if not label:
            raise TransformAnimationError("animation clip name is required")
        if not isinstance(self.animation, TransformAnimation3D):
            raise TransformAnimationError(
                "animation clip animation must be a transform animation"
            )
        self.animation.validate()
        object.__setattr__(self, "id", clip_id)
        object.__setattr__(self, "label", label)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "animation": self.animation.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TransformClip3D":
        if not isinstance(data, Mapping):
            raise TransformAnimationError(
                "each animation library clip must be an object"
            )
        unknown = set(data) - {"id", "label", "animation"}
        if unknown:
            raise TransformAnimationError(
                "animation library clip contains unsupported fields: "
                + ", ".join(sorted(unknown))
            )
        if "id" not in data:
            raise TransformAnimationError("animation library clip id is required")
        raw_animation = data.get("animation")
        if not isinstance(raw_animation, Mapping):
            raise TransformAnimationError(
                "animation library clip animation must be an object"
            )
        return cls(
            str(data["id"]),
            str(data.get("label", data["id"])),
            TransformAnimation3D.from_dict(raw_animation),
        )


@dataclass(frozen=True, slots=True)
class TransformAnimationLibrary3D:
    """A bounded ordered clip library with one optional autoplay choice."""

    clips: tuple[TransformClip3D, ...]
    autoplay: str | None = None
    schema: str = TRANSFORM_ANIMATION_LIBRARY_SCHEMA

    def __post_init__(self) -> None:
        clips = tuple(self.clips)
        autoplay = None if self.autoplay is None else _validated_clip_id(self.autoplay)
        object.__setattr__(self, "clips", clips)
        object.__setattr__(self, "autoplay", autoplay)
        self.validate()

    def validate(self) -> None:
        if self.schema != TRANSFORM_ANIMATION_LIBRARY_SCHEMA:
            raise TransformAnimationError(
                f"animation library schema must be {TRANSFORM_ANIMATION_LIBRARY_SCHEMA}"
            )
        if not 1 <= len(self.clips) <= MAX_ANIMATION_CLIPS_PER_NODE:
            raise TransformAnimationError(
                f"animation library needs 1 to {MAX_ANIMATION_CLIPS_PER_NODE} clips"
            )
        ids: list[str] = []
        hashes: dict[int, str] = {}
        for clip in self.clips:
            if not isinstance(clip, TransformClip3D):
                raise TransformAnimationError(
                    "animation library clips must be TransformClip3D values"
                )
            clip.animation.validate()
            ids.append(clip.id)
            clip_hash = animation_clip_hash(clip.id)
            previous = hashes.get(clip_hash)
            if previous is not None and previous != clip.id:
                raise TransformAnimationError(
                    f"animation clip ids {previous!r} and {clip.id!r} have the same portable hash"
                )
            hashes[clip_hash] = clip.id
        if len(ids) != len(set(ids)):
            raise TransformAnimationError("animation library clip ids must be unique")
        if self.autoplay is not None and self.autoplay not in set(ids):
            raise TransformAnimationError(
                f"animation library autoplay clip {self.autoplay!r} is missing"
            )

    def clip(self, clip_id: str) -> TransformClip3D:
        wanted = _validated_clip_id(clip_id)
        for clip in self.clips:
            if clip.id == wanted:
                return clip
        raise TransformAnimationError(f"animation clip {wanted!r} is missing")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "clips": [clip.to_dict() for clip in self.clips],
            "autoplay": self.autoplay,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TransformAnimationLibrary3D":
        if not isinstance(data, Mapping):
            raise TransformAnimationError(
                "transform_animation_library must be an object"
            )
        unknown = set(data) - {"schema", "clips", "autoplay"}
        if unknown:
            raise TransformAnimationError(
                "transform_animation_library contains unsupported fields: "
                + ", ".join(sorted(unknown))
            )
        raw_clips = data.get("clips")
        if not isinstance(raw_clips, (list, tuple)):
            raise TransformAnimationError(
                "transform_animation_library clips must be a list"
            )
        raw_autoplay = data.get("autoplay")
        if raw_autoplay is not None and not isinstance(raw_autoplay, str):
            raise TransformAnimationError(
                "transform_animation_library autoplay must be a clip id or null"
            )
        return cls(
            tuple(TransformClip3D.from_dict(item) for item in raw_clips),
            raw_autoplay,
            str(data.get("schema", "")),
        )


def default_transform_animation(duration: float = 2.0) -> TransformAnimation3D:
    result = TransformAnimation3D(float(duration), (TransformKey3D(0.0),))
    result.validate()
    return result


def default_transform_animation_library(
    duration: float = 2.0,
) -> TransformAnimationLibrary3D:
    return TransformAnimationLibrary3D(
        (
            TransformClip3D(
                DEFAULT_ANIMATION_CLIP_ID,
                DEFAULT_ANIMATION_CLIP_LABEL,
                default_transform_animation(duration),
            ),
        ),
        DEFAULT_ANIMATION_CLIP_ID,
    )


def _reject_mixed_animation_metadata(metadata: Mapping[str, Any]) -> None:
    if (
        ANIMATION_METADATA_KEY in metadata
        and ANIMATION_LIBRARY_METADATA_KEY in metadata
    ):
        raise TransformAnimationError(
            "an object cannot use transform_animation and "
            "transform_animation_library together"
        )


def transform_animation_library_from_metadata(
    metadata: Mapping[str, Any],
) -> TransformAnimationLibrary3D | None:
    _reject_mixed_animation_metadata(metadata)
    if ANIMATION_METADATA_KEY in metadata:
        raw_legacy = metadata[ANIMATION_METADATA_KEY]
        if not isinstance(raw_legacy, Mapping):
            raise TransformAnimationError("transform_animation must be an object")
        return TransformAnimationLibrary3D(
            (
                TransformClip3D(
                    DEFAULT_ANIMATION_CLIP_ID,
                    DEFAULT_ANIMATION_CLIP_LABEL,
                    TransformAnimation3D.from_dict(raw_legacy),
                ),
            ),
            DEFAULT_ANIMATION_CLIP_ID,
        )
    if ANIMATION_LIBRARY_METADATA_KEY not in metadata:
        return None
    raw = metadata[ANIMATION_LIBRARY_METADATA_KEY]
    if not isinstance(raw, Mapping):
        raise TransformAnimationError("transform_animation_library must be an object")
    return TransformAnimationLibrary3D.from_dict(raw)


def transform_animation_from_metadata(
    metadata: Mapping[str, Any],
) -> TransformAnimation3D | None:
    """Return the legacy clip or the library's autoplay/first compatibility view."""

    _reject_mixed_animation_metadata(metadata)
    if ANIMATION_METADATA_KEY in metadata:
        raw = metadata[ANIMATION_METADATA_KEY]
        if not isinstance(raw, Mapping):
            raise TransformAnimationError("transform_animation must be an object")
        return TransformAnimation3D.from_dict(raw)
    library = transform_animation_library_from_metadata(metadata)
    if library is None:
        return None
    if library.autoplay is not None:
        return library.clip(library.autoplay).animation
    return library.clips[0].animation


def metadata_with_transform_animation(
    metadata: Mapping[str, Any], animation: TransformAnimation3D | None
) -> dict[str, Any]:
    result = dict(metadata)
    result.pop(ANIMATION_LIBRARY_METADATA_KEY, None)
    if animation is None:
        result.pop(ANIMATION_METADATA_KEY, None)
    else:
        result[ANIMATION_METADATA_KEY] = animation.to_dict()
    return result


def metadata_with_transform_animation_library(
    metadata: Mapping[str, Any], library: TransformAnimationLibrary3D | None
) -> dict[str, Any]:
    result = dict(metadata)
    result.pop(ANIMATION_METADATA_KEY, None)
    if library is None:
        result.pop(ANIMATION_LIBRARY_METADATA_KEY, None)
    else:
        result[ANIMATION_LIBRARY_METADATA_KEY] = library.to_dict()
    return result


def quantize_transform_animation(
    animation: TransformAnimation3D,
) -> TransformAnimation3D:
    """Roundtrip fields through the exact KCAN scalar encodings."""

    animation.validate()
    duration = _f32(animation.duration)
    if not math.isfinite(duration) or duration <= 0.0:
        raise TransformAnimationError(
            "animation length is not representable on the phone"
        )
    keys: list[TransformKey3D] = []
    previous_code: int | None = None
    previous_rotation: tuple[float, ...] | None = None
    for key in animation.keys:
        code = _time_code(key.time, duration)
        if previous_code is not None and code <= previous_code:
            raise TransformAnimationError(
                "two animation keys are too close together for the compact phone format"
            )
        previous_code = code
        translation = tuple(
            _f16(value, "animation key position") for value in key.translation
        )
        rotation_payload = key.packed_rotation or _quantize_rotation(key.rotation)
        if (
            previous_rotation is not None
            and sum(
                left * right for left, right in zip(previous_rotation, rotation_payload)
            )
            < 0.0
        ):
            rotation_payload = tuple(-value for value in rotation_payload)
        scale = tuple(_f16(value, "animation key size") for value in key.scale)
        if any(value < MIN_ANIMATION_SCALE for value in scale):
            raise TransformAnimationError(
                "animation key size is too close to zero for the compact phone format"
            )
        quantized_key = TransformKey3D(
            duration * code / 65535.0,
            translation,  # type: ignore[arg-type]
            rotation_payload,  # type: ignore[arg-type]
            scale,  # type: ignore[arg-type]
            key.easing,
        )
        object.__setattr__(quantized_key, "_packed_rotation", rotation_payload)
        keys.append(quantized_key)
        previous_rotation = quantized_key.rotation
    result = TransformAnimation3D(duration, tuple(keys), animation.loop_mode)
    result.validate()
    return result


def animation_local_time(animation: TransformAnimation3D, elapsed: float) -> float:
    animation.validate()
    elapsed = float(elapsed)
    if not math.isfinite(elapsed):
        raise TransformAnimationError("animation sample time must be finite")
    elapsed = max(0.0, elapsed)
    duration = animation.duration
    if animation.loop_mode == "once":
        return min(duration, elapsed)
    if animation.loop_mode == "loop":
        return elapsed % duration
    phase = elapsed % (duration * 2.0)
    return phase if phase <= duration else duration * 2.0 - phase


def sample_transform_animation(
    animation: TransformAnimation3D, elapsed: float
) -> TransformKey3D:
    """Sample one relative pose with shortest-path normalized rotation."""

    local = animation_local_time(animation, elapsed)
    keys = animation.keys
    if local <= keys[0].time or len(keys) == 1:
        return TransformKey3D(
            local, keys[0].translation, keys[0].rotation, keys[0].scale, keys[0].easing
        )
    for left, right in zip(keys, keys[1:]):
        if local == right.time:
            return TransformKey3D(
                local, right.translation, right.rotation, right.scale, right.easing
            )
        if left.time <= local < right.time:
            fraction = (local - left.time) / (right.time - left.time)
            amount = easing(right.easing, fraction)
            translation = tuple(
                a + (b - a) * amount
                for a, b in zip(left.translation, right.translation)
            )
            scale = tuple(a + (b - a) * amount for a, b in zip(left.scale, right.scale))
            rotation = quat_nlerp(left.rotation, right.rotation, amount)
            return TransformKey3D(
                local,
                translation,  # type: ignore[arg-type]
                rotation,  # type: ignore[arg-type]
                scale,  # type: ignore[arg-type]
                right.easing,
            )
    last = keys[-1]
    return TransformKey3D(
        local, last.translation, last.rotation, last.scale, last.easing
    )


@dataclass(frozen=True, slots=True)
class TransformAnimationBinding3D:
    node_index: int
    node_id: str
    animation: TransformAnimation3D
    clip_id: str = DEFAULT_ANIMATION_CLIP_ID
    clip_hash: int = animation_clip_hash(DEFAULT_ANIMATION_CLIP_ID)
    autoplay: bool = True
    legacy: bool = True

    def __post_init__(self) -> None:
        clip_id = _validated_clip_id(self.clip_id)
        clip_hash = int(self.clip_hash)
        if not 0 <= clip_hash <= 0xFFFFFFFFFFFFFFFF:
            raise TransformAnimationError(
                "animation clip hash must be an unsigned 64-bit value"
            )
        expected_hash = animation_clip_hash(clip_id)
        if clip_hash != expected_hash:
            raise TransformAnimationError(
                f"animation clip {clip_id!r} hash does not match portable FNV-1a"
            )
        self.animation.validate()
        object.__setattr__(self, "node_index", int(self.node_index))
        object.__setattr__(self, "node_id", str(self.node_id))
        object.__setattr__(self, "clip_id", clip_id)
        object.__setattr__(self, "clip_hash", clip_hash)
        object.__setattr__(self, "autoplay", bool(self.autoplay))
        object.__setattr__(self, "legacy", bool(self.legacy))


@dataclass(frozen=True, slots=True)
class TransformAnimationProjectSpec:
    bindings: tuple[TransformAnimationBinding3D, ...] = ()
    legacy: bool | None = None

    def __post_init__(self) -> None:
        bindings = tuple(self.bindings)
        object.__setattr__(self, "bindings", bindings)
        if self.legacy is None:
            object.__setattr__(
                self,
                "legacy",
                all(binding.legacy for binding in bindings),
            )
        else:
            object.__setattr__(self, "legacy", bool(self.legacy))

    @property
    def key_count(self) -> int:
        return sum(len(binding.animation.keys) for binding in self.bindings)

    @property
    def clip_count(self) -> int:
        return len(self.bindings)

    @property
    def animated_node_count(self) -> int:
        return len({binding.node_index for binding in self.bindings})


def _validate_animation_node(node: Any) -> None:
    if node.dynamic:
        raise TransformAnimationError(
            f"animated object {node.id!r} must be static because physics also owns its pose"
        )
    if "player" in node.tags:
        raise TransformAnimationError(
            f"animated object {node.id!r} cannot be the Player"
        )
    if node.metadata.get("packed_kinematic") is not None:
        raise TransformAnimationError(
            f"animated object {node.id!r} already has a Movement Pattern"
        )
    if node.metadata.get("scatter_population") is not None:
        raise TransformAnimationError(
            f"animated object {node.id!r} cannot also use Populate Area"
        )
    if any(abs(float(value)) > 1.0e-12 for value in node.angular_velocity):
        raise TransformAnimationError(
            f"animated object {node.id!r} must have zero spin velocity"
        )


def collect_transform_animation_spec(project: Any) -> TransformAnimationProjectSpec:
    """Parse, constrain, quantize, and canonically order every placed clip."""

    bindings: list[TransformAnimationBinding3D] = []
    total_keys = 0
    animated_nodes = 0
    library_form_seen = False
    for index, node in enumerate(getattr(project, "nodes", ())):
        library = transform_animation_library_from_metadata(node.metadata)
        if library is None:
            continue
        animated_nodes += 1
        if animated_nodes > MAX_ANIMATED_NODES:
            raise TransformAnimationError(
                f"projects support at most {MAX_ANIMATED_NODES} animated objects"
            )
        _validate_animation_node(node)
        is_legacy = ANIMATION_METADATA_KEY in node.metadata
        library_form_seen = library_form_seen or not is_legacy
        node_bindings: list[TransformAnimationBinding3D] = []
        seen_hashes: dict[int, str] = {}
        for clip in library.clips:
            clip_hash = animation_clip_hash(clip.id)
            previous = seen_hashes.get(clip_hash)
            if previous is not None:
                raise TransformAnimationError(
                    f"animation clips {previous!r} and {clip.id!r} on {node.id!r} "
                    "have the same portable hash"
                )
            seen_hashes[clip_hash] = clip.id
            quantized = quantize_transform_animation(clip.animation)
            total_keys += len(quantized.keys)
            if total_keys > MAX_ANIMATION_KEYS_TOTAL:
                raise TransformAnimationError(
                    f"projects support at most {MAX_ANIMATION_KEYS_TOTAL} animation keys"
                )
            node_bindings.append(
                TransformAnimationBinding3D(
                    index,
                    node.id,
                    quantized,
                    clip.id,
                    clip_hash,
                    library.autoplay == clip.id,
                    is_legacy,
                )
            )
        bindings.extend(sorted(node_bindings, key=lambda binding: binding.clip_hash))
        if len(bindings) > MAX_ANIMATION_CLIPS_TOTAL:
            raise TransformAnimationError(
                f"projects support at most {MAX_ANIMATION_CLIPS_TOTAL} animation clips"
            )
    return TransformAnimationProjectSpec(
        tuple(bindings),
        legacy=not library_form_seen,
    )


@dataclass(slots=True)
class TransformAnimationComponent3D:
    animation: TransformAnimation3D
    base_translation: tuple[float, float, float]
    base_rotation: tuple[float, float, float, float]
    base_scale: tuple[float, float, float]
    elapsed: float = 0.0
    clips: dict[str, TransformAnimation3D] = field(default_factory=dict)
    active_clip: str | None = DEFAULT_ANIMATION_CLIP_ID
    playing: bool = True

    def __post_init__(self) -> None:
        self.animation.validate()
        clips = dict(self.clips)
        if not clips:
            clips[DEFAULT_ANIMATION_CLIP_ID] = self.animation
        if not 1 <= len(clips) <= MAX_ANIMATION_CLIPS_PER_NODE:
            raise TransformAnimationError(
                f"animation component needs 1 to {MAX_ANIMATION_CLIPS_PER_NODE} clips"
            )
        for clip_id, animation in clips.items():
            _validated_clip_id(clip_id)
            animation.validate()
        self.clips = clips
        if self.active_clip is not None:
            active_clip = _validated_clip_id(self.active_clip)
            if active_clip not in clips:
                raise TransformAnimationError(
                    f"animation clip {active_clip!r} is missing"
                )
            self.active_clip = active_clip
            self.animation = clips[active_clip]
        else:
            self.playing = False
        self.elapsed = float(self.elapsed)
        if not math.isfinite(self.elapsed) or self.elapsed < 0.0:
            raise TransformAnimationError(
                "animation component elapsed time must be finite and non-negative"
            )
        self.playing = bool(self.playing)

    @property
    def active_animation(self) -> TransformAnimation3D | None:
        if self.active_clip is None:
            return None
        return self.clips[self.active_clip]

    def play(self, clip_id: str, restart: bool = True) -> None:
        wanted = _validated_clip_id(clip_id)
        if wanted not in self.clips:
            raise TransformAnimationError(f"animation clip {wanted!r} is missing")
        if restart or self.active_clip != wanted:
            self.elapsed = 0.0
        self.active_clip = wanted
        self.animation = self.clips[wanted]
        self.playing = True

    def stop(self, reset: bool = True) -> None:
        self.playing = False
        if reset:
            self.active_clip = None
            self.elapsed = 0.0

    def reset_pose(self, entity: Any) -> None:
        entity.position = tuple(self.base_translation)
        entity.rotation = tuple(self.base_rotation)
        entity.scale = tuple(self.base_scale)

    def to_dict(self) -> dict[str, Any]:
        return {
            "animation": self.animation.to_dict(),
            "clips": {
                clip_id: animation.to_dict()
                for clip_id, animation in sorted(self.clips.items())
            },
            "active_clip": self.active_clip,
            "playing": self.playing,
            "base_translation": list(self.base_translation),
            "base_rotation": list(self.base_rotation),
            "base_scale": list(self.base_scale),
            "elapsed": self.elapsed,
        }


def _compose_component(entity: Any, component: TransformAnimationComponent3D) -> None:
    if not entity.alive or not entity.active:
        return
    animation = component.active_animation
    if animation is None:
        return
    relative = sample_transform_animation(animation, component.elapsed)
    entity.position = add(component.base_translation, relative.translation)
    entity.rotation = quat_normalize(
        quat_mul(component.base_rotation, relative.rotation)
    )
    entity.scale = tuple(
        authored * multiplier
        for authored, multiplier in zip(component.base_scale, relative.scale)
    )


def attach_transform_animations_3d(
    world: Any, spec: TransformAnimationProjectSpec
) -> bool:
    """Attach autoplay clips at priority -50 and compose time zero immediately."""

    if not spec.bindings:
        return False
    bindings_by_node: dict[str, list[TransformAnimationBinding3D]] = {}
    for binding in spec.bindings:
        bindings_by_node.setdefault(binding.node_id, []).append(binding)
    for node_id, bindings in bindings_by_node.items():
        entity = world.require(node_id)
        autoplay = next(
            (binding.clip_id for binding in bindings if binding.autoplay),
            None,
        )
        compatibility = next(
            (binding.animation for binding in bindings if binding.autoplay),
            bindings[0].animation,
        )
        component = TransformAnimationComponent3D(
            compatibility,
            tuple(entity.position),
            tuple(entity.rotation),
            tuple(entity.scale),
            clips={binding.clip_id: binding.animation for binding in bindings},
            active_clip=autoplay,
            playing=autoplay is not None,
        )
        entity.extra_components[ANIMATION_METADATA_KEY] = component
        _compose_component(entity, component)

    def transform_animation_system(
        target_world: Any, dt: float, input_frame: Any
    ) -> None:
        del input_frame
        for entity_id in sorted(target_world.entities):
            entity = target_world.entities[entity_id]
            component = entity.extra_components.get(ANIMATION_METADATA_KEY)
            if component is None:
                continue
            animation = component.active_animation
            if component.playing and animation is not None:
                component.elapsed += dt
                if animation.loop_mode == "once" and (
                    component.elapsed >= animation.duration
                    or math.isclose(
                        component.elapsed,
                        animation.duration,
                        rel_tol=0.0,
                        abs_tol=1.0e-12,
                    )
                ):
                    component.elapsed = animation.duration
                    component.playing = False
            _compose_component(entity, component)

    world.add_system(
        transform_animation_system,
        phase="pre_physics",
        priority=-50,
        name="transform_animation_3d",
    )
    return True


__all__ = [
    "ANIMATION_CLIP_ID_PATTERN",
    "ANIMATION_EASINGS",
    "ANIMATION_LIBRARY_METADATA_KEY",
    "ANIMATION_LOOP_MODES",
    "ANIMATION_METADATA_KEY",
    "DEFAULT_ANIMATION_CLIP_ID",
    "DEFAULT_ANIMATION_CLIP_LABEL",
    "MAX_ANIMATED_NODES",
    "MAX_ANIMATION_CLIPS_PER_NODE",
    "MAX_ANIMATION_CLIPS_TOTAL",
    "MAX_ANIMATION_DURATION",
    "MAX_ANIMATION_KEYS_PER_CLIP",
    "MAX_ANIMATION_KEYS_PER_NODE",
    "MAX_ANIMATION_KEYS_TOTAL",
    "TRANSFORM_ANIMATION_LIBRARY_SCHEMA",
    "TRANSFORM_ANIMATION_SCHEMA",
    "TransformAnimation3D",
    "TransformAnimationBinding3D",
    "TransformAnimationComponent3D",
    "TransformAnimationError",
    "TransformAnimationLibrary3D",
    "TransformAnimationProjectSpec",
    "TransformClip3D",
    "TransformKey3D",
    "animation_clip_hash",
    "animation_local_time",
    "attach_transform_animations_3d",
    "collect_transform_animation_spec",
    "default_transform_animation",
    "default_transform_animation_library",
    "metadata_with_transform_animation",
    "metadata_with_transform_animation_library",
    "quantize_transform_animation",
    "sample_transform_animation",
    "transform_animation_from_metadata",
    "transform_animation_library_from_metadata",
]
