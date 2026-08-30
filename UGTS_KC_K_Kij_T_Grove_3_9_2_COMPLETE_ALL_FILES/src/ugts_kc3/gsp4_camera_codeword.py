"""Exact Camera2 YUV420 codewords for the UGTOMS/GSP4 seed path.

This module is deliberately independent of Android.  It is the Python oracle
for the phone's authoritative dense Y/U/V normalization, the logical
``UGCODE24-420`` raster, seed-regenerated traversal packing, and exact modular
novelty residuals.  It contains no image completion or colour conversion.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import struct
from typing import Sequence

from .scatter import combine_seed, stable_id


GSP4_CAMERA_LINEAGE_NAMESPACE = 0x7F0B2A27A8C27F83
PIXEL_PROFILE = "UGCODE24_420_CAMERA_EXACT"
AUTHORITY = "CAMERA2_DENSE_YUV420"


class Gsp4CameraCodewordError(ValueError):
    """Invalid camera evidence or non-bijective codeword data."""


def _as_bytes(value: bytes | bytearray | memoryview, label: str) -> bytes:
    try:
        return bytes(value)
    except (TypeError, ValueError) as error:
        raise Gsp4CameraCodewordError(f"{label} is not a byte buffer") from error


def _validate_dimensions(width: int, height: int) -> tuple[int, int, int, int]:
    if isinstance(width, bool) or isinstance(height, bool):
        raise Gsp4CameraCodewordError("camera dimensions must be integers")
    width = int(width)
    height = int(height)
    if not 2 <= width <= 65_534 or not 2 <= height <= 65_534:
        raise Gsp4CameraCodewordError("camera dimensions are outside the profile")
    if width & 1 or height & 1:
        raise Gsp4CameraCodewordError("UGCODE24-420 requires even dimensions")
    return width, height, width // 2, height // 2


@dataclass(frozen=True)
class DenseYuv420Frame:
    """One exact normalized Camera2 observation before substrate execution."""

    width: int
    height: int
    sensor_timestamp_ns: int
    y: bytes
    u: bytes
    v: bytes

    def __post_init__(self) -> None:
        width, height, chroma_width, chroma_height = _validate_dimensions(
            self.width, self.height
        )
        if not 0 <= int(self.sensor_timestamp_ns) < (1 << 63):
            raise Gsp4CameraCodewordError(
                "sensor timestamp must be a nonnegative signed int64"
            )
        y = _as_bytes(self.y, "Y plane")
        u = _as_bytes(self.u, "U plane")
        v = _as_bytes(self.v, "V plane")
        if len(y) != width * height:
            raise Gsp4CameraCodewordError("dense Y plane byte count mismatch")
        chroma_bytes = chroma_width * chroma_height
        if len(u) != chroma_bytes or len(v) != chroma_bytes:
            raise Gsp4CameraCodewordError("dense U/V plane byte count mismatch")
        object.__setattr__(self, "width", width)
        object.__setattr__(self, "height", height)
        object.__setattr__(self, "sensor_timestamp_ns", int(self.sensor_timestamp_ns))
        object.__setattr__(self, "y", y)
        object.__setattr__(self, "u", u)
        object.__setattr__(self, "v", v)

    @property
    def chroma_width(self) -> int:
        return self.width // 2

    @property
    def chroma_height(self) -> int:
        return self.height // 2

    @property
    def authoritative_bytes(self) -> int:
        return len(self.y) + len(self.u) + len(self.v)

    @property
    def pre_substrate_sha256(self) -> str:
        digest = hashlib.sha256()
        digest.update(struct.pack("<QII", self.sensor_timestamp_ns, self.width, self.height))
        digest.update(self.y)
        digest.update(self.u)
        digest.update(self.v)
        return digest.hexdigest()

    def codeword(self, x: int, y: int) -> tuple[int, int, int]:
        if not 0 <= int(x) < self.width or not 0 <= int(y) < self.height:
            raise Gsp4CameraCodewordError("codeword coordinate is outside the frame")
        x = int(x)
        y = int(y)
        luma = self.y[y * self.width + x]
        chroma = (y // 2) * self.chroma_width + (x // 2)
        return luma, self.u[chroma], self.v[chroma]


def _copy_strided_plane(
    source: bytes | bytearray | memoryview,
    *,
    row_stride: int,
    pixel_stride: int,
    origin_x: int,
    origin_y: int,
    width: int,
    height: int,
    label: str,
) -> bytes:
    raw = memoryview(source).cast("B")
    row_stride = int(row_stride)
    pixel_stride = int(pixel_stride)
    if row_stride <= 0 or pixel_stride <= 0:
        raise Gsp4CameraCodewordError(f"{label} strides must be positive")
    if min(origin_x, origin_y, width, height) < 0:
        raise Gsp4CameraCodewordError(f"{label} extent is invalid")
    if width == 0 or height == 0:
        return b""
    last = (
        (origin_y + height - 1) * row_stride
        + (origin_x + width - 1) * pixel_stride
    )
    if last >= len(raw):
        raise Gsp4CameraCodewordError(f"{label} stride extent exceeds its buffer")
    dense = bytearray(width * height)
    target = 0
    for row in range(height):
        source_row = (origin_y + row) * row_stride + origin_x * pixel_stride
        for column in range(width):
            dense[target] = raw[source_row + column * pixel_stride]
            target += 1
    return bytes(dense)


def normalize_yuv420_888(
    *,
    width: int,
    height: int,
    sensor_timestamp_ns: int,
    y_plane: bytes | bytearray | memoryview,
    u_plane: bytes | bytearray | memoryview,
    v_plane: bytes | bytearray | memoryview,
    y_row_stride: int,
    y_pixel_stride: int,
    u_row_stride: int,
    u_pixel_stride: int,
    v_row_stride: int,
    v_pixel_stride: int,
    crop_left: int = 0,
    crop_top: int = 0,
) -> DenseYuv420Frame:
    """Normalize a Camera2 three-plane buffer without YUV-to-RGB conversion."""

    width, height, chroma_width, chroma_height = _validate_dimensions(width, height)
    crop_left = int(crop_left)
    crop_top = int(crop_top)
    if crop_left < 0 or crop_top < 0 or crop_left & 1 or crop_top & 1:
        raise Gsp4CameraCodewordError(
            "UGCODE24-420 requires a nonnegative even crop origin"
        )
    y = _copy_strided_plane(
        y_plane,
        row_stride=y_row_stride,
        pixel_stride=y_pixel_stride,
        origin_x=crop_left,
        origin_y=crop_top,
        width=width,
        height=height,
        label="Y plane",
    )
    u = _copy_strided_plane(
        u_plane,
        row_stride=u_row_stride,
        pixel_stride=u_pixel_stride,
        origin_x=crop_left // 2,
        origin_y=crop_top // 2,
        width=chroma_width,
        height=chroma_height,
        label="U plane",
    )
    v = _copy_strided_plane(
        v_plane,
        row_stride=v_row_stride,
        pixel_stride=v_pixel_stride,
        origin_x=crop_left // 2,
        origin_y=crop_top // 2,
        width=chroma_width,
        height=chroma_height,
        label="V plane",
    )
    return DenseYuv420Frame(width, height, sensor_timestamp_ns, y, u, v)


def validate_traversal(traversal: Sequence[int], pixel_count: int) -> tuple[int, ...]:
    if len(traversal) != int(pixel_count):
        raise Gsp4CameraCodewordError("seed traversal length mismatch")
    result = tuple(int(value) for value in traversal)
    seen = bytearray(pixel_count)
    for value in result:
        if not 0 <= value < pixel_count:
            raise Gsp4CameraCodewordError("seed traversal address is outside the raster")
        if seen[value]:
            raise Gsp4CameraCodewordError("seed traversal repeats an address")
        seen[value] = 1
    return result


def pack_codeword420(frame: DenseYuv420Frame, traversal: Sequence[int]) -> bytes:
    """Pack Y plus canonical-owner U/V lanes in regenerated address order."""

    order = validate_traversal(traversal, frame.width * frame.height)
    output = bytearray(frame.authoritative_bytes)
    write = 0
    for address in order:
        y, x = divmod(address, frame.width)
        output[write] = frame.y[address]
        write += 1
        if not (x & 1 or y & 1):
            chroma = (y // 2) * frame.chroma_width + (x // 2)
            output[write] = frame.u[chroma]
            output[write + 1] = frame.v[chroma]
            write += 2
    if write != len(output):
        raise AssertionError("UGCODE24-420 owner packing changed")
    return bytes(output)


def unpack_codeword420(
    packed: bytes | bytearray | memoryview,
    *,
    width: int,
    height: int,
    sensor_timestamp_ns: int,
    traversal: Sequence[int],
) -> DenseYuv420Frame:
    """Invert canonical-owner storage into exact dense Y, U and V planes."""

    width, height, chroma_width, chroma_height = _validate_dimensions(width, height)
    order = validate_traversal(traversal, width * height)
    source = _as_bytes(packed, "UGCODE24-420 stream")
    expected = width * height + 2 * chroma_width * chroma_height
    if len(source) != expected:
        raise Gsp4CameraCodewordError("UGCODE24-420 stream byte count mismatch")
    y_plane = bytearray(width * height)
    u_plane = bytearray(chroma_width * chroma_height)
    v_plane = bytearray(chroma_width * chroma_height)
    read = 0
    for address in order:
        row, column = divmod(address, width)
        y_plane[address] = source[read]
        read += 1
        if not (column & 1 or row & 1):
            chroma = (row // 2) * chroma_width + (column // 2)
            u_plane[chroma] = source[read]
            v_plane[chroma] = source[read + 1]
            read += 2
    if read != len(source):
        raise AssertionError("UGCODE24-420 inverse owner packing changed")
    return DenseYuv420Frame(
        width,
        height,
        sensor_timestamp_ns,
        bytes(y_plane),
        bytes(u_plane),
        bytes(v_plane),
    )


def modular_residual(
    observed: bytes | bytearray | memoryview,
    predicted: bytes | bytearray | memoryview,
) -> bytes:
    """Return exact unsigned modulo-256 residual symbols."""

    actual = _as_bytes(observed, "observed codewords")
    prior = _as_bytes(predicted, "predicted codewords")
    if len(actual) != len(prior):
        raise Gsp4CameraCodewordError("prediction length mismatch")
    return bytes((value - guess) & 0xFF for value, guess in zip(actual, prior))


def apply_modular_residual(
    predicted: bytes | bytearray | memoryview,
    residual: bytes | bytearray | memoryview,
) -> bytes:
    """Invert :func:`modular_residual` exactly."""

    prior = _as_bytes(predicted, "predicted codewords")
    delta = _as_bytes(residual, "novelty residual")
    if len(prior) != len(delta):
        raise Gsp4CameraCodewordError("novelty residual length mismatch")
    return bytes((guess + difference) & 0xFF for guess, difference in zip(prior, delta))


def novelty_event_count(residual: bytes | bytearray | memoryview) -> int:
    """Count irreducible lane changes; exact zero is negative memory."""

    return sum(value != 0 for value in memoryview(residual).cast("B"))


def gsp4_mix32(value: int) -> int:
    """Exact GSP4/UGTS-GN 1.1 avalanche mixer used for route lineage."""

    value = int(value) & 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 0x846CA68B) & 0xFFFFFFFF
    value ^= value >> 16
    return value & 0xFFFFFFFF


def codeword_lineage(
    *, root_seed: int, recipe_seed: int, cartesian_address: int, frame_ordinal: int
) -> tuple[int, int]:
    """Regenerate GSP4 lineage seed/hash without per-codeword storage."""

    for label, value, limit in (
        ("root seed", root_seed, 1 << 64),
        ("recipe seed", recipe_seed, 1 << 64),
        ("Cartesian address", cartesian_address, 1 << 64),
        ("frame ordinal", frame_ordinal, 1 << 32),
    ):
        if isinstance(value, bool) or not 0 <= int(value) < limit:
            raise Gsp4CameraCodewordError(f"{label} is outside its unsigned domain")
    session = combine_seed(int(root_seed), int(recipe_seed))
    persistent = stable_id(
        session, GSP4_CAMERA_LINEAGE_NAMESPACE, int(cartesian_address)
    )
    lineage_seed = int(persistent) & 0xFFFFFFFF
    return lineage_seed, gsp4_mix32(lineage_seed ^ int(frame_ordinal))


__all__ = [
    "AUTHORITY",
    "DenseYuv420Frame",
    "GSP4_CAMERA_LINEAGE_NAMESPACE",
    "Gsp4CameraCodewordError",
    "PIXEL_PROFILE",
    "apply_modular_residual",
    "codeword_lineage",
    "gsp4_mix32",
    "modular_residual",
    "normalize_yuv420_888",
    "novelty_event_count",
    "pack_codeword420",
    "unpack_codeword420",
    "validate_traversal",
]
