"""Compact deterministic render-substrate settings for the Android runtime."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from numbers import Integral, Real
from pathlib import Path
import struct
from typing import Any, Mapping


RENDER_SUBSTRATE_METADATA_KEY = "substrate_render"
RENDER_SUBSTRATE_PACK_ASSET = "render_substrate.kcrp"
RENDER_PACK_ASSET = RENDER_SUBSTRATE_PACK_ASSET
RENDER_PACK_MAGIC = b"KCRP392\0"
RENDER_PACK_ENDIAN = 0x01020304
RENDER_PACK_VERSION = 1
RENDER_PACK_BYTES = 32
RENDER_PACK_VERSION_V2 = 2
RENDER_PACK_V2_BYTES = 40

POLAR_RENDER_MODES = ("auto", "lut", "direct", "cpu")
BAYER_MODES = ("off", "subtle", "retro", "custom")
POLAR_MATERIAL_MODES = ("off", "bands")

_POLAR_MODE_CODES = {name: code for code, name in enumerate(POLAR_RENDER_MODES)}
_BAYER_MODE_CODES = {name: code for code, name in enumerate(BAYER_MODES)}
_POLAR_CODE_NAMES = {code: name for name, code in _POLAR_MODE_CODES.items()}
_BAYER_CODE_NAMES = {code: name for name, code in _BAYER_MODE_CODES.items()}
_POLAR_MATERIAL_MODE_CODES = {
    name: code for code, name in enumerate(POLAR_MATERIAL_MODES)
}
_POLAR_MATERIAL_CODE_NAMES = {
    code: name for name, code in _POLAR_MATERIAL_MODE_CODES.items()
}
_POLAR_MATERIAL_KEYS = frozenset(
    {
        "polar_material_mode",
        "polar_material_bands",
        "polar_material_strength",
    }
)
_ALLOWED_METADATA_KEYS = frozenset(
    {"polar_mode", "bayer_mode", "levels", "strength", "seed"}
).union(_POLAR_MATERIAL_KEYS)
_BAYER_PRESET_DEFAULTS = {
    "off": (2, 0.0),
    "subtle": (64, 0.30),
    "retro": (4, 1.0),
}
_PACK_STRUCT = struct.Struct("<8sIIBBHfQ")
_PACK_V2_TAIL_STRUCT = struct.Struct("<BBHf")

if _PACK_STRUCT.size != RENDER_PACK_BYTES:  # pragma: no cover - import invariant
    raise RuntimeError("render-substrate pack layout is not 32 bytes")
if RENDER_PACK_BYTES + _PACK_V2_TAIL_STRUCT.size != RENDER_PACK_V2_BYTES:
    raise RuntimeError("render-substrate v2 pack layout is not 40 bytes")


class RenderPackError(ValueError):
    """Invalid substrate-render metadata or malformed KCRP bytes."""


@dataclass(frozen=True)
class RenderSubstrateConfig:
    """Validated settings represented by one versioned fixed-size KCRP record."""

    polar_mode: str = "auto"
    bayer_mode: str = "subtle"
    levels: int = 64
    strength: float = 0.30
    seed: int = 0
    format_version: int = RENDER_PACK_VERSION
    polar_material_mode: str = "off"
    polar_material_bands: int = 1
    polar_material_strength: float = 0.0

    @property
    def polar_mode_code(self) -> int:
        return _POLAR_MODE_CODES[self.polar_mode]

    @property
    def bayer_mode_code(self) -> int:
        return _BAYER_MODE_CODES[self.bayer_mode]

    @property
    def bayer_enabled(self) -> bool:
        return self.bayer_mode != "off" and self.strength > 0.0

    @property
    def polar_material_mode_code(self) -> int:
        return _POLAR_MATERIAL_MODE_CODES[self.polar_material_mode]

    @property
    def polar_material_enabled(self) -> bool:
        return (
            self.polar_material_mode == "bands"
            and self.polar_material_strength > 0.0
        )


def _mode(
    raw: Any, *, label: str, codes: Mapping[str, int], default: str
) -> str:
    value = default if raw is None else raw
    if not isinstance(value, str) or value not in codes:
        choices = ", ".join(codes)
        raise RenderPackError(f"{label} must be one of: {choices}")
    return value


def _levels(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, Integral):
        raise RenderPackError("substrate_render.levels must be an integer from 2 to 256")
    value = int(raw)
    if not 2 <= value <= 256:
        raise RenderPackError("substrate_render.levels must be from 2 to 256")
    return value


def _strength(raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, Real):
        raise RenderPackError("substrate_render.strength must be a finite number from 0 to 1")
    value = float(raw)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise RenderPackError("substrate_render.strength must be a finite number from 0 to 1")
    return value


def _seed(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, Integral):
        raise RenderPackError("substrate_render.seed must be an unsigned 64-bit integer")
    value = int(raw)
    if not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
        raise RenderPackError("substrate_render.seed must be an unsigned 64-bit integer")
    return value


def _polar_material_bands(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, Integral):
        raise RenderPackError(
            "substrate_render.polar_material_bands must be an integer from 1 to 32"
        )
    value = int(raw)
    if not 1 <= value <= 32:
        raise RenderPackError(
            "substrate_render.polar_material_bands must be from 1 to 32"
        )
    return value


def _polar_material_strength(raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, Real):
        raise RenderPackError(
            "substrate_render.polar_material_strength must be a finite number from 0 to 1"
        )
    value = float(raw)
    if (
        not math.isfinite(value)
        or not 0.0 <= value <= 1.0
        or (value == 0.0 and math.copysign(1.0, value) < 0.0)
    ):
        raise RenderPackError(
            "substrate_render.polar_material_strength must be a finite positive-zero number from 0 to 1"
        )
    return value


def render_substrate_config_from_metadata(
    metadata: Mapping[str, Any],
) -> RenderSubstrateConfig | None:
    """Resolve the optional project metadata entry into canonical settings."""

    if RENDER_SUBSTRATE_METADATA_KEY not in metadata:
        return None
    raw = metadata[RENDER_SUBSTRATE_METADATA_KEY]
    if not isinstance(raw, Mapping):
        raise RenderPackError("project.metadata['substrate_render'] must be an object")

    unknown = set(raw).difference(_ALLOWED_METADATA_KEYS)
    if unknown:
        rendered = ", ".join(sorted((repr(key) for key in unknown)))
        raise RenderPackError(f"substrate_render has unknown key(s): {rendered}")

    polar_mode = _mode(
        raw.get("polar_mode"),
        label="substrate_render.polar_mode",
        codes=_POLAR_MODE_CODES,
        default="auto",
    )
    bayer_mode = _mode(
        raw.get("bayer_mode"),
        label="substrate_render.bayer_mode",
        codes=_BAYER_MODE_CODES,
        default="subtle",
    )

    if bayer_mode == "custom":
        missing = [name for name in ("levels", "strength") if name not in raw]
        if missing:
            raise RenderPackError(
                "substrate_render custom Bayer mode requires explicit "
                + " and ".join(missing)
            )
        levels = _levels(raw["levels"])
        strength = _strength(raw["strength"])
    else:
        default_levels, default_strength = _BAYER_PRESET_DEFAULTS[bayer_mode]
        levels = _levels(raw.get("levels", default_levels))
        strength = _strength(raw.get("strength", default_strength))
        if bayer_mode == "off" and strength != 0.0:
            raise RenderPackError(
                "substrate_render off Bayer mode requires strength exactly 0"
            )

    seed = _seed(raw.get("seed", 0))
    requested_polar_material = _POLAR_MATERIAL_KEYS.intersection(raw)
    if requested_polar_material:
        missing = sorted(_POLAR_MATERIAL_KEYS.difference(raw))
        if missing:
            raise RenderPackError(
                "substrate_render Polar Material v2 requires explicit "
                + ", ".join(missing)
            )
        polar_material_mode = _mode(
            raw["polar_material_mode"],
            label="substrate_render.polar_material_mode",
            codes=_POLAR_MATERIAL_MODE_CODES,
            default="off",
        )
        polar_material_bands = _polar_material_bands(
            raw["polar_material_bands"]
        )
        polar_material_strength = _polar_material_strength(
            raw["polar_material_strength"]
        )
        if polar_material_mode == "off" and polar_material_strength != 0.0:
            raise RenderPackError(
                "substrate_render Polar Material off mode requires strength exactly +0"
            )
        format_version = RENDER_PACK_VERSION_V2
    else:
        polar_material_mode = "off"
        polar_material_bands = 1
        polar_material_strength = 0.0
        format_version = RENDER_PACK_VERSION
    return RenderSubstrateConfig(
        polar_mode=polar_mode,
        bayer_mode=bayer_mode,
        levels=levels,
        strength=strength,
        seed=seed,
        format_version=format_version,
        polar_material_mode=polar_material_mode,
        polar_material_bands=polar_material_bands,
        polar_material_strength=polar_material_strength,
    )


def render_substrate_config_from_project(project: Any) -> RenderSubstrateConfig | None:
    metadata = getattr(project, "metadata", None)
    if not isinstance(metadata, Mapping):
        raise RenderPackError("project.metadata must be an object")
    return render_substrate_config_from_metadata(metadata)


def compile_render_substrate_pack_bytes(project: Any) -> bytes:
    """Compile optional ``substrate_render`` metadata into exact KCRP v1/v2."""

    config = render_substrate_config_from_project(project)
    if config is None:
        return b""
    result = _PACK_STRUCT.pack(
        RENDER_PACK_MAGIC,
        RENDER_PACK_ENDIAN,
        config.format_version,
        config.polar_mode_code,
        config.bayer_mode_code,
        config.levels,
        config.strength,
        config.seed,
    )
    expected_bytes = RENDER_PACK_BYTES
    if config.format_version == RENDER_PACK_VERSION_V2:
        result += _PACK_V2_TAIL_STRUCT.pack(
            config.polar_material_mode_code,
            config.polar_material_bands,
            0,
            config.polar_material_strength,
        )
        expected_bytes = RENDER_PACK_V2_BYTES
    if len(result) != expected_bytes:  # pragma: no cover - struct invariant
        raise RenderPackError(
            f"render-substrate v{config.format_version} pack is not exactly "
            f"{expected_bytes} bytes"
        )
    return result


def compile_render_pack_bytes(project: Any) -> bytes:
    """Compatibility-short name for :func:`compile_render_substrate_pack_bytes`."""

    return compile_render_substrate_pack_bytes(project)


def write_render_substrate_pack(project: Any, path: str | Path) -> Path | None:
    data = compile_render_substrate_pack_bytes(project)
    if not data:
        return None
    result = Path(path)
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_bytes(data)
    return result


def inspect_render_substrate_pack(
    data_or_path: bytes | bytearray | memoryview | str | Path,
) -> dict[str, Any]:
    """Strictly parse a complete KCRP record and return build diagnostics."""

    data = (
        Path(data_or_path).read_bytes()
        if isinstance(data_or_path, (str, Path))
        else bytes(data_or_path)
    )
    if len(data) < 16:
        raise RenderPackError("truncated render-substrate pack")
    magic, endian, version = struct.unpack_from("<8sII", data)
    if magic != RENDER_PACK_MAGIC:
        raise RenderPackError("render-substrate magic mismatch")
    if endian != RENDER_PACK_ENDIAN:
        raise RenderPackError("render-substrate endian marker mismatch")
    if version == RENDER_PACK_VERSION:
        expected_bytes = RENDER_PACK_BYTES
    elif version == RENDER_PACK_VERSION_V2:
        expected_bytes = RENDER_PACK_V2_BYTES
    else:
        raise RenderPackError("unsupported render-substrate version")
    if len(data) < expected_bytes:
        raise RenderPackError("truncated render-substrate pack")
    if len(data) > expected_bytes:
        raise RenderPackError(
            f"render-substrate pack trailing bytes: {len(data) - expected_bytes}"
        )

    (
        _magic,
        _endian,
        _version,
        polar_code,
        bayer_code,
        levels,
        strength,
        seed,
    ) = _PACK_STRUCT.unpack(data[:RENDER_PACK_BYTES])
    if polar_code not in _POLAR_CODE_NAMES:
        raise RenderPackError("render-substrate polar mode is invalid")
    if bayer_code not in _BAYER_CODE_NAMES:
        raise RenderPackError("render-substrate Bayer mode is invalid")
    if not 2 <= levels <= 256:
        raise RenderPackError("render-substrate Bayer levels are invalid")
    if not math.isfinite(strength) or not 0.0 <= strength <= 1.0:
        raise RenderPackError("render-substrate Bayer strength is invalid")

    polar_mode = _POLAR_CODE_NAMES[polar_code]
    bayer_mode = _BAYER_CODE_NAMES[bayer_code]
    if bayer_mode == "off" and strength != 0.0:
        raise RenderPackError("render-substrate off Bayer mode has nonzero strength")

    polar_material_mode = "off"
    polar_material_bands = 1
    polar_material_strength = 0.0
    if version == RENDER_PACK_VERSION_V2:
        (
            polar_material_code,
            polar_material_bands,
            reserved,
            polar_material_strength,
        ) = _PACK_V2_TAIL_STRUCT.unpack(data[RENDER_PACK_BYTES:])
        if polar_material_code not in _POLAR_MATERIAL_CODE_NAMES:
            raise RenderPackError("render-substrate Polar Material mode is invalid")
        if not 1 <= polar_material_bands <= 32:
            raise RenderPackError("render-substrate Polar Material bands are invalid")
        if reserved != 0:
            raise RenderPackError(
                "render-substrate Polar Material reserved field is nonzero"
            )
        if (
            not math.isfinite(polar_material_strength)
            or not 0.0 <= polar_material_strength <= 1.0
            or (
                polar_material_strength == 0.0
                and math.copysign(1.0, polar_material_strength) < 0.0
            )
        ):
            raise RenderPackError(
                "render-substrate Polar Material strength is invalid"
            )
        polar_material_mode = _POLAR_MATERIAL_CODE_NAMES[polar_material_code]
        if polar_material_mode == "off" and polar_material_strength != 0.0:
            raise RenderPackError(
                "render-substrate Polar Material off mode has nonzero strength"
            )

    return {
        "schema": "ugts-kc-render-substrate-inspection-3.9.2",
        "format_version": version,
        "byte_length": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "polar_mode": polar_mode,
        "polar_mode_code": polar_code,
        "bayer_mode": bayer_mode,
        "bayer_mode_code": bayer_code,
        "bayer_enabled": bayer_mode != "off" and strength > 0.0,
        "levels": levels,
        "strength": strength,
        "seed": seed,
        "polar_material_mode": polar_material_mode,
        "polar_material_mode_code": _POLAR_MATERIAL_MODE_CODES[
            polar_material_mode
        ],
        "polar_material_enabled": (
            polar_material_mode == "bands" and polar_material_strength > 0.0
        ),
        "polar_material_bands": polar_material_bands,
        "polar_material_strength": polar_material_strength,
    }


def inspect_render_pack(
    data_or_path: bytes | bytearray | memoryview | str | Path,
) -> dict[str, Any]:
    """Compatibility-short name for :func:`inspect_render_substrate_pack`."""

    return inspect_render_substrate_pack(data_or_path)
