"""Custom UGTOMS chrono-geometry codec primitives.

This module intentionally does not call an image or video codec.  It provides
the reversible spatial transform and exact frame coding used by the UGTC4D
lossless evidence profile:

* the existing UGLUT2/LogPolarProfile defines the polar chart;
* UGPXLUT1 stores a complete polar-to-Cartesian pixel permutation;
* UGFRM1 stores one exact polar-ordered RGB frame using codec-native
  prediction and canonical run tokens.

Geometry and the outer multi-section UGTC4D container are separate layers.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import struct
from typing import Any, Iterable, Sequence

from .packed_kinematics import PolarLookupTable


UGTC4D_MAGIC = b"UGTC4D1\0"
UGTC4D_EXTENSION = ".ugtc4d"

PIXEL_LUT_MAGIC = b"UGPXLUT1"
PIXEL_LUT_MAJOR = 1
PIXEL_LUT_MINOR = 0
_PIXEL_LUT_HEADER = struct.Struct("<8sHHIII2d32s32s32s")

POLAR_PERMUTATION_OPERATOR = (
    b"UGPXLUT1-permutation-v1\0"
    b"pixel-center-xy;explicit-core;rho20-closed-theta18-periodic;"
    b"ring=nearest-canonical-UGLUT2-binary16-radius;"
    b"sector=max-normalized-dot-canonical-UGLUT2-binary16-direction-neighbor4;"
    b"sort=core-ring-sector-rho20-theta18-row-column"
)
POLAR_PERMUTATION_OPERATOR_SHA256 = hashlib.sha256(
    POLAR_PERMUTATION_OPERATOR
).hexdigest()

FRAME_MAGIC = b"UGFRM1\0\0"
FRAME_MAJOR = 1
FRAME_MINOR = 0
FRAME_HEADER_BYTES = 224
_FRAME_HEADER = struct.Struct(
    "<8sHHIIIIqQQII32s32s32s32s32s4s"
)
_FRAME_CONTENT_DIGEST_OFFSET = 188

FRAME_CHECKPOINT = 1 << 0
NO_PREVIOUS_ORDINAL = 0xFFFFFFFF

PREDICTOR_RAW = 0
PREDICTOR_POLAR_SPATIAL_SUB = 1
PREDICTOR_TEMPORAL_XOR = 2
PREDICTOR_TEMPORAL_SUB = 3
PREDICTOR_TEMPORAL_SPATIAL_SUB = 4

_PREDICTOR_NAMES = {
    PREDICTOR_RAW: "RAW",
    PREDICTOR_POLAR_SPATIAL_SUB: "POLAR_SPATIAL_SUB_MOD256",
    PREDICTOR_TEMPORAL_XOR: "TEMPORAL_XOR",
    PREDICTOR_TEMPORAL_SUB: "TEMPORAL_SUB_MOD256",
    PREDICTOR_TEMPORAL_SPATIAL_SUB: "TEMPORAL_THEN_POLAR_SPATIAL_SUB_MOD256",
}

MAX_FRAME_BYTES = 1 << 31
MAX_PIXEL_COUNT = 1 << 30


class ChronoCodecError(ValueError):
    """A malformed, noncanonical or unsupported UGTC4D codec primitive."""


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _require_rgb_bytes(value: bytes | bytearray | memoryview, expected: int) -> bytes:
    result = bytes(value)
    if expected < 0 or expected > MAX_FRAME_BYTES:
        raise ChronoCodecError("frame byte count exceeds the UGFRM1 safety limit")
    if len(result) != expected:
        raise ChronoCodecError(
            f"RGB byte count mismatch: expected {expected}, got {len(result)}"
        )
    return result


@dataclass(frozen=True)
class PolarPixelPermutation:
    """A complete polar-ordinal to Cartesian-pixel bijection."""

    width: int
    height: int
    center_x: float
    center_y: float
    uglut2_sha256: str
    operator_sha256: str
    polar_to_cartesian: tuple[int, ...]

    @property
    def pixel_count(self) -> int:
        return self.width * self.height

    def validate(self) -> None:
        if not 1 <= int(self.width) <= 65_535:
            raise ChronoCodecError("UGPXLUT1 width must be in [1, 65535]")
        if not 1 <= int(self.height) <= 65_535:
            raise ChronoCodecError("UGPXLUT1 height must be in [1, 65535]")
        if self.pixel_count > MAX_PIXEL_COUNT:
            raise ChronoCodecError("UGPXLUT1 pixel count exceeds its safety limit")
        if not math.isfinite(self.center_x) or not math.isfinite(self.center_y):
            raise ChronoCodecError("UGPXLUT1 chart center must be finite")
        if not (-0.5 <= self.center_x <= self.width - 0.5):
            raise ChronoCodecError("UGPXLUT1 center_x is outside the source raster")
        if not (-0.5 <= self.center_y <= self.height - 0.5):
            raise ChronoCodecError("UGPXLUT1 center_y is outside the source raster")
        if (
            len(self.uglut2_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.uglut2_sha256)
        ):
            raise ChronoCodecError("UGPXLUT1 UGLUT2 digest must be lowercase SHA-256")
        if self.operator_sha256 != POLAR_PERMUTATION_OPERATOR_SHA256:
            raise ChronoCodecError("UGPXLUT1 permutation operator digest mismatch")
        if len(self.polar_to_cartesian) != self.pixel_count:
            raise ChronoCodecError("UGPXLUT1 permutation length mismatch")
        seen = bytearray(self.pixel_count)
        for value in self.polar_to_cartesian:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ChronoCodecError("UGPXLUT1 permutation entries must be integers")
            if not 0 <= value < self.pixel_count:
                raise ChronoCodecError("UGPXLUT1 permutation entry is out of range")
            if seen[value]:
                raise ChronoCodecError("UGPXLUT1 permutation contains a duplicate pixel")
            seen[value] = 1
        if not all(seen):
            raise ChronoCodecError("UGPXLUT1 permutation leaves a pixel uncovered")

    def inverse(self) -> tuple[int, ...]:
        self.validate()
        result = [0] * self.pixel_count
        for polar_index, cartesian_index in enumerate(self.polar_to_cartesian):
            result[cartesian_index] = polar_index
        return tuple(result)

    def to_bytes(self) -> bytes:
        self.validate()
        payload = struct.pack(
            f"<{self.pixel_count}I", *self.polar_to_cartesian
        )
        return _PIXEL_LUT_HEADER.pack(
            PIXEL_LUT_MAGIC,
            PIXEL_LUT_MAJOR,
            PIXEL_LUT_MINOR,
            self.width,
            self.height,
            self.pixel_count,
            self.center_x,
            self.center_y,
            bytes.fromhex(self.uglut2_sha256),
            bytes.fromhex(self.operator_sha256),
            _sha256(payload),
        ) + payload

    @classmethod
    def from_bytes(
        cls, data: bytes | bytearray | memoryview, *, uglut2_bytes: bytes | None = None
    ) -> "PolarPixelPermutation":
        raw = bytes(data)
        if len(raw) < _PIXEL_LUT_HEADER.size:
            raise ChronoCodecError("UGPXLUT1 is truncated before its header")
        (
            magic,
            major,
            minor,
            width,
            height,
            pixel_count,
            center_x,
            center_y,
            uglut2_digest,
            operator_digest,
            payload_digest,
        ) = _PIXEL_LUT_HEADER.unpack_from(raw)
        if magic != PIXEL_LUT_MAGIC:
            raise ChronoCodecError("UGPXLUT1 magic mismatch")
        if (major, minor) != (PIXEL_LUT_MAJOR, PIXEL_LUT_MINOR):
            raise ChronoCodecError(f"unsupported UGPXLUT1 version {major}.{minor}")
        if width * height != pixel_count or not 1 <= pixel_count <= MAX_PIXEL_COUNT:
            raise ChronoCodecError("UGPXLUT1 dimensions/pixel count are invalid")
        expected = _PIXEL_LUT_HEADER.size + pixel_count * 4
        if len(raw) != expected:
            raise ChronoCodecError(
                f"UGPXLUT1 length mismatch: expected {expected}, got {len(raw)}"
            )
        payload = raw[_PIXEL_LUT_HEADER.size :]
        if _sha256(payload) != payload_digest:
            raise ChronoCodecError("UGPXLUT1 payload SHA-256 mismatch")
        if uglut2_bytes is not None:
            try:
                PolarLookupTable.from_bytes(uglut2_bytes)
            except ValueError as error:
                raise ChronoCodecError(f"UGPXLUT1 dependency is not valid UGLUT2: {error}") from error
            if _sha256(uglut2_bytes) != uglut2_digest:
                raise ChronoCodecError("UGPXLUT1 UGLUT2 dependency hash mismatch")
        values = tuple(item[0] for item in struct.iter_unpack("<I", payload))
        result = cls(
            width,
            height,
            center_x,
            center_y,
            uglut2_digest.hex(),
            operator_digest.hex(),
            values,
        )
        result.validate()
        if result.to_bytes() != raw:
            raise ChronoCodecError("UGPXLUT1 is not in canonical form")
        return result


def generate_polar_pixel_permutation(
    width: int,
    height: int,
    uglut2_bytes: bytes,
    *,
    center_x: float | None = None,
    center_y: float | None = None,
) -> PolarPixelPermutation:
    """Generate the exact all-pixel polar ordering bound to one UGLUT2.

    The explicit stored permutation is the cross-platform authority.  Direct
    logarithm/atan2 evaluation is an authoring operation only; Android and
    other readers never have to reproduce transcendental boundary rounding.
    """

    if not 1 <= int(width) <= 65_535 or not 1 <= int(height) <= 65_535:
        raise ChronoCodecError("polar permutation dimensions must fit uint16")
    width, height = int(width), int(height)
    if width * height > MAX_PIXEL_COUNT:
        raise ChronoCodecError("polar permutation exceeds its safety limit")
    try:
        import numpy as np
    except ImportError as error:
        raise ChronoCodecError("polar permutation generation requires NumPy") from error
    try:
        lut = PolarLookupTable.from_bytes(bytes(uglut2_bytes))
    except ValueError as error:
        raise ChronoCodecError(f"polar permutation requires valid UGLUT2: {error}") from error
    canonical_lut = PolarLookupTable.generate(
        lut.profile, lut.resolution
    ).to_bytes()
    if canonical_lut != bytes(uglut2_bytes):
        raise ChronoCodecError(
            "polar permutation requires the canonical generated UGLUT2 binary16 lanes"
        )
    cx = (width - 1) * 0.5 if center_x is None else float(center_x)
    cy = (height - 1) * 0.5 if center_y is None else float(center_y)
    if not math.isfinite(cx) or not math.isfinite(cy):
        raise ChronoCodecError("polar permutation center must be finite")

    cartesian = np.arange(width * height, dtype=np.uint32)
    x = (cartesian % width).astype(np.float64)
    y = (cartesian // width).astype(np.float64)
    dx = x - cx
    dy = y - cy
    radius = np.hypot(dx, dy)
    core = radius < lut.profile.core_radius
    safe_radius = np.maximum(radius, lut.profile.core_radius)
    rho = np.log(safe_radius / lut.profile.r0)
    rho = np.clip(rho, lut.profile.rho_min, lut.profile.rho_max)
    rho_unit = (rho - lut.profile.rho_min) / (
        lut.profile.rho_max - lut.profile.rho_min
    )
    rho_code = np.rint(rho_unit * ((1 << 20) - 1)).astype(np.uint32)
    rho_code[core] = 0
    theta = np.mod(np.arctan2(dy, dx), math.tau)
    theta_code = np.floor(theta * ((1 << 18) / math.tau)).astype(np.uint32)
    theta_code &= (1 << 18) - 1
    theta_code[core] = 0
    # Literal UGLUT2 values determine the primary ring and sector.  This is
    # intentionally stronger than using only its profile/resolution metadata.
    # The exact resulting permutation is stored, so readers do not repeat this
    # floating authoring operation.
    lut_radii = np.asarray(lut.radii, dtype=np.float64)
    if np.any(np.diff(lut_radii) < 0.0):
        raise ChronoCodecError("canonical UGLUT2 radii are not monotone")
    upper = np.searchsorted(lut_radii, radius, side="left")
    upper = np.clip(upper, 0, lut.resolution - 1)
    lower = np.maximum(0, upper - 1)
    lower_error = np.abs(radius - lut_radii[lower])
    upper_error = np.abs(radius - lut_radii[upper])
    ring = np.where(upper_error < lower_error, upper, lower).astype(np.uint32)
    ring[core] = 0

    base_sector = (
        theta_code.astype(np.uint64) * lut.resolution // (1 << 18)
    ).astype(np.int64)
    candidates = np.stack(
        [
            (base_sector - 1) % lut.resolution,
            base_sector % lut.resolution,
            (base_sector + 1) % lut.resolution,
            (base_sector + 2) % lut.resolution,
        ],
        axis=1,
    )
    candidates.sort(axis=1)
    lut_sine = np.asarray(lut.sine, dtype=np.float64)
    lut_cosine = np.asarray(lut.cosine, dtype=np.float64)
    lengths = np.hypot(lut_sine, lut_cosine)
    if np.any(lengths <= 1.0e-9):
        raise ChronoCodecError("canonical UGLUT2 contains a zero direction")
    lut_sine /= lengths
    lut_cosine /= lengths
    safe = np.where(core, 1.0, radius)
    unit_x = dx / safe
    unit_y = dy / safe
    scores = (
        lut_cosine[candidates] * unit_x[:, None]
        + lut_sine[candidates] * unit_y[:, None]
    )
    sector = candidates[
        np.arange(width * height, dtype=np.int64), np.argmax(scores, axis=1)
    ].astype(np.uint32)
    sector[core] = 0
    # np.lexsort uses the final key as primary.  Row/column are retained as
    # the complete deterministic tie-break for quantized chart collisions.
    order = np.lexsort(
        (
            x.astype(np.uint32),
            y.astype(np.uint32),
            theta_code,
            rho_code,
            sector,
            ring,
            (~core).astype(np.uint8),
        )
    ).astype(np.uint32)
    result = PolarPixelPermutation(
        width,
        height,
        cx,
        cy,
        _sha256(bytes(uglut2_bytes)).hex(),
        POLAR_PERMUTATION_OPERATOR_SHA256,
        tuple(int(value) for value in order),
    )
    # Round trip through the binary ABI so generation and inspection share all
    # safety/canonicalization checks.
    return PolarPixelPermutation.from_bytes(
        result.to_bytes(), uglut2_bytes=bytes(uglut2_bytes)
    )


def gather_rgb_polar_numpy(frame: Any, permutation: PolarPixelPermutation) -> Any:
    """Gather one Cartesian RGB8 image into exact polar permutation order."""
    try:
        import numpy as np
    except ImportError as error:
        raise ChronoCodecError("polar RGB gather requires NumPy") from error
    permutation.validate()
    array = np.asarray(frame)
    expected = (permutation.height, permutation.width, 3)
    if array.shape != expected or array.dtype != np.uint8:
        raise ChronoCodecError(f"frame must be RGB uint8 with shape {expected}")
    indices = np.asarray(permutation.polar_to_cartesian, dtype=np.int64)
    return array.reshape(-1, 3)[indices].copy()


def scatter_rgb_polar_numpy(polar: Any, permutation: PolarPixelPermutation) -> Any:
    """Scatter one polar-ordered RGB8 plane back to Cartesian order."""
    try:
        import numpy as np
    except ImportError as error:
        raise ChronoCodecError("polar RGB scatter requires NumPy") from error
    permutation.validate()
    array = np.asarray(polar)
    expected = (permutation.pixel_count, 3)
    if array.shape != expected or array.dtype != np.uint8:
        raise ChronoCodecError(f"polar frame must be RGB uint8 with shape {expected}")
    result = np.empty(expected, dtype=np.uint8)
    indices = np.asarray(permutation.polar_to_cartesian, dtype=np.int64)
    result[indices] = array
    return result.reshape(permutation.height, permutation.width, 3)


def gather_rgb_polar_cuda(
    frames: Sequence[Any], permutation: PolarPixelPermutation, *, max_vram_mib: int
) -> tuple[Any, dict[str, Any]]:
    """Exact CUDA gather for one or more RGB8 frames.

    Entropy/token coding remains CPU work in profile 0.1.  This operation is
    byte-exact and is checked against the NumPy oracle by its callers.
    """
    try:
        import numpy as np
        import torch
    except ImportError as error:
        raise ChronoCodecError("CUDA polar gather requires NumPy and PyTorch") from error
    if not torch.cuda.is_available():
        raise ChronoCodecError("PyTorch reports no CUDA device")
    if not frames:
        return np.empty((0, permutation.pixel_count, 3), dtype=np.uint8), {
            "backend": "torch-cuda-polar-permutation",
            "batch_frames": 0,
            "peak_mib": 0.0,
        }
    permutation.validate()
    source = np.stack([np.asarray(frame) for frame in frames], axis=0)
    expected = (len(frames), permutation.height, permutation.width, 3)
    if source.shape != expected or source.dtype != np.uint8:
        raise ChronoCodecError(f"CUDA frame batch must be RGB uint8 with shape {expected}")
    device = torch.device("cuda:0")
    properties = torch.cuda.get_device_properties(device)
    limit = int(max_vram_mib) * 1024 * 1024
    if limit <= 0 or limit > int(properties.total_memory):
        raise ChronoCodecError("CUDA workspace limit is invalid for the selected device")
    estimated = source.nbytes * 2 + permutation.pixel_count * 8
    if estimated > limit:
        raise ChronoCodecError("CUDA polar gather batch exceeds the declared workspace")
    torch.cuda.reset_peak_memory_stats(device)
    tensor = torch.as_tensor(source, device=device).reshape(len(frames), -1, 3)
    indices = torch.as_tensor(
        permutation.polar_to_cartesian, device=device, dtype=torch.int64
    )
    output = tensor[:, indices, :].contiguous()
    result = output.cpu().numpy()
    torch.cuda.synchronize(device)
    peak = float(torch.cuda.max_memory_allocated(device)) / (1024 * 1024)
    if peak > max_vram_mib:
        raise ChronoCodecError("CUDA polar gather exceeded its declared workspace")
    return result, {
        "backend": "torch-cuda-polar-permutation",
        "device": torch.cuda.get_device_name(device),
        "compute_capability": list(torch.cuda.get_device_capability(device)),
        "batch_frames": len(frames),
        "workspace_limit_mib": int(max_vram_mib),
        "peak_mib": peak,
        "integer_byte_exact": True,
    }


def encode_run_tokens(data: bytes | bytearray | memoryview) -> bytes:
    """Canonical custom zero/repeat/literal token coding.

    Token bytes:

    * ``00llllll``: 1..64 zero bytes;
    * ``01llllll value``: 3..66 repeats of a nonzero byte;
    * ``10llllll bytes...``: 1..64 literal bytes;
    * ``11xxxxxx``: reserved and invalid.
    """
    source = bytes(data)
    output = bytearray()
    size = len(source)
    position = 0

    def repeated_length(offset: int, maximum: int = 66) -> int:
        value = source[offset]
        end = min(size, offset + maximum)
        index = offset + 1
        while index < end and source[index] == value:
            index += 1
        return index - offset

    while position < size:
        value = source[position]
        if value == 0:
            length = repeated_length(position, 64)
            output.append(length - 1)
            position += length
            continue
        repeat = repeated_length(position, 66)
        if repeat >= 3:
            output.append(0x40 | (repeat - 3))
            output.append(value)
            position += repeat
            continue
        start = position
        position += repeat
        while position < size and position - start < 64:
            if source[position] == 0:
                break
            candidate = repeated_length(position, 66)
            if candidate >= 3:
                break
            if position - start + candidate > 64:
                break
            position += candidate
        literal = source[start:position]
        if not literal or len(literal) > 64:
            raise AssertionError("UGTC4D literal token construction failed")
        output.append(0x80 | (len(literal) - 1))
        output.extend(literal)
    return bytes(output)


def decode_run_tokens(
    data: bytes | bytearray | memoryview,
    *,
    expected_bytes: int,
    require_canonical: bool = True,
) -> bytes:
    """Decode and bound one custom run-token payload."""
    source = bytes(data)
    if not 0 <= int(expected_bytes) <= MAX_FRAME_BYTES:
        raise ChronoCodecError("decoded token byte limit is invalid")
    output = bytearray()
    position = 0
    while position < len(source):
        control = source[position]
        position += 1
        kind = control >> 6
        code = control & 0x3F
        if kind == 0:
            length = code + 1
            output.extend(bytes(length))
        elif kind == 1:
            length = code + 3
            if position >= len(source):
                raise ChronoCodecError("repeat token is truncated")
            value = source[position]
            position += 1
            if value == 0:
                raise ChronoCodecError("repeat token must not encode zero")
            output.extend(bytes((value,)) * length)
        elif kind == 2:
            length = code + 1
            end = position + length
            if end > len(source):
                raise ChronoCodecError("literal token is truncated")
            output.extend(source[position:end])
            position = end
        else:
            raise ChronoCodecError("reserved UGTC4D run token encountered")
        if len(output) > expected_bytes:
            raise ChronoCodecError("run tokens expand beyond the declared frame length")
    if len(output) != expected_bytes:
        raise ChronoCodecError(
            f"run-token decoded length mismatch: expected {expected_bytes}, got {len(output)}"
        )
    result = bytes(output)
    if require_canonical and encode_run_tokens(result) != source:
        raise ChronoCodecError("run-token payload is not in canonical form")
    return result


def _spatial_sub_mod256(source: bytes) -> bytes:
    result = bytearray(len(source))
    for index, value in enumerate(source):
        predictor = source[index - 3] if index >= 3 else 0
        result[index] = (value - predictor) & 0xFF
    return bytes(result)


def _spatial_add_mod256(residual: bytes) -> bytes:
    result = bytearray(len(residual))
    for index, value in enumerate(residual):
        predictor = result[index - 3] if index >= 3 else 0
        result[index] = (value + predictor) & 0xFF
    return bytes(result)


def _apply_predictor(current: bytes, previous: bytes | None, predictor: int) -> bytes:
    if predictor == PREDICTOR_RAW:
        return current
    if predictor == PREDICTOR_POLAR_SPATIAL_SUB:
        return _spatial_sub_mod256(current)
    if previous is None or len(previous) != len(current):
        raise ChronoCodecError("temporal predictor requires an equal-length previous frame")
    if predictor == PREDICTOR_TEMPORAL_XOR:
        return bytes(left ^ right for left, right in zip(current, previous))
    temporal = bytes((left - right) & 0xFF for left, right in zip(current, previous))
    if predictor == PREDICTOR_TEMPORAL_SUB:
        return temporal
    if predictor == PREDICTOR_TEMPORAL_SPATIAL_SUB:
        return _spatial_sub_mod256(temporal)
    raise ChronoCodecError(f"unsupported UGFRM1 predictor {predictor}")


def _reverse_predictor(residual: bytes, previous: bytes | None, predictor: int) -> bytes:
    if predictor == PREDICTOR_RAW:
        return residual
    if predictor == PREDICTOR_POLAR_SPATIAL_SUB:
        return _spatial_add_mod256(residual)
    if previous is None or len(previous) != len(residual):
        raise ChronoCodecError("temporal frame is missing its exact previous frame")
    if predictor == PREDICTOR_TEMPORAL_XOR:
        return bytes(left ^ right for left, right in zip(residual, previous))
    temporal = (
        _spatial_add_mod256(residual)
        if predictor == PREDICTOR_TEMPORAL_SPATIAL_SUB
        else residual
    )
    if predictor not in (PREDICTOR_TEMPORAL_SUB, PREDICTOR_TEMPORAL_SPATIAL_SUB):
        raise ChronoCodecError(f"unsupported UGFRM1 predictor {predictor}")
    return bytes((left + right) & 0xFF for left, right in zip(temporal, previous))


@dataclass(frozen=True)
class EncodedPolarFrame:
    ordinal: int
    source_pts: int
    flags: int
    predictor: int
    previous_ordinal: int
    decoded_sha256: str
    payload_sha256: str
    content_sha256: str
    logical_bytes: int
    payload: bytes

    @property
    def checkpoint(self) -> bool:
        return bool(self.flags & FRAME_CHECKPOINT)

    def to_bytes(self) -> bytes:
        if self.predictor not in _PREDICTOR_NAMES:
            raise ChronoCodecError("UGFRM1 predictor is unknown")
        if self.flags & ~FRAME_CHECKPOINT:
            raise ChronoCodecError("UGFRM1 flags contain unsupported bits")
        if self.checkpoint:
            if self.previous_ordinal != NO_PREVIOUS_ORDINAL:
                raise ChronoCodecError("UGFRM1 checkpoint must not reference a previous frame")
            if self.predictor not in (PREDICTOR_RAW, PREDICTOR_POLAR_SPATIAL_SUB):
                raise ChronoCodecError("UGFRM1 checkpoint uses a temporal predictor")
        elif self.previous_ordinal == NO_PREVIOUS_ORDINAL:
            raise ChronoCodecError("UGFRM1 delta frame has no previous ordinal")
        payload_digest = _sha256(self.payload)
        if payload_digest.hex() != self.payload_sha256:
            raise ChronoCodecError("UGFRM1 payload digest field mismatch")
        decoded_digest = bytes.fromhex(self.decoded_sha256)
        if len(decoded_digest) != 32:
            raise ChronoCodecError("UGFRM1 decoded digest field is invalid")
        unsigned_header = _FRAME_HEADER.pack(
            FRAME_MAGIC,
            FRAME_MAJOR,
            FRAME_MINOR,
            FRAME_HEADER_BYTES,
            self.ordinal,
            self.flags,
            self.predictor,
            self.source_pts,
            self.logical_bytes,
            len(self.payload),
            self.previous_ordinal,
            0,
            decoded_digest,
            payload_digest,
            bytes(32),
            bytes(4),
        )
        content_digest = _sha256(unsigned_header + self.payload)
        if content_digest.hex() != self.content_sha256:
            raise ChronoCodecError("UGFRM1 content digest field mismatch")
        return _FRAME_HEADER.pack(
            FRAME_MAGIC,
            FRAME_MAJOR,
            FRAME_MINOR,
            FRAME_HEADER_BYTES,
            self.ordinal,
            self.flags,
            self.predictor,
            self.source_pts,
            self.logical_bytes,
            len(self.payload),
            self.previous_ordinal,
            0,
            decoded_digest,
            payload_digest,
            content_digest,
            bytes(4),
        ) + self.payload


def encode_polar_frame(
    polar_rgb_bytes: bytes | bytearray | memoryview,
    *,
    ordinal: int,
    source_pts: int,
    previous_polar_rgb_bytes: bytes | bytearray | memoryview | None = None,
    previous_ordinal: int | None = None,
    checkpoint: bool = False,
) -> EncodedPolarFrame:
    """Choose the smallest canonical predictor/token payload for one frame."""
    current = bytes(polar_rgb_bytes)
    if not current or len(current) > MAX_FRAME_BYTES or len(current) % 3:
        raise ChronoCodecError("polar RGB frame must contain a bounded whole number of RGB pixels")
    if not 0 <= int(ordinal) <= 0xFFFFFFFF:
        raise ChronoCodecError("UGFRM1 ordinal must fit uint32")
    if not -(1 << 63) <= int(source_pts) < (1 << 63):
        raise ChronoCodecError("UGFRM1 source PTS must fit int64")
    previous = None if previous_polar_rgb_bytes is None else bytes(previous_polar_rgb_bytes)
    if checkpoint:
        if previous_ordinal is not None:
            raise ChronoCodecError("checkpoint frame must not declare a previous ordinal")
        candidates = (PREDICTOR_RAW, PREDICTOR_POLAR_SPATIAL_SUB)
        stored_previous = NO_PREVIOUS_ORDINAL
        flags = FRAME_CHECKPOINT
    else:
        if previous is None or len(previous) != len(current):
            raise ChronoCodecError("delta frame requires an equal-length previous polar frame")
        if previous_ordinal is None or not 0 <= int(previous_ordinal) < int(ordinal):
            raise ChronoCodecError("delta frame previous ordinal is invalid")
        candidates = (
            PREDICTOR_POLAR_SPATIAL_SUB,
            PREDICTOR_TEMPORAL_XOR,
            PREDICTOR_TEMPORAL_SUB,
            PREDICTOR_TEMPORAL_SPATIAL_SUB,
        )
        stored_previous = int(previous_ordinal)
        flags = 0
    encoded_candidates = []
    for predictor in candidates:
        transformed = _apply_predictor(current, previous, predictor)
        payload = encode_run_tokens(transformed)
        encoded_candidates.append((len(payload), predictor, payload))
    _size, predictor, payload = min(encoded_candidates, key=lambda item: (item[0], item[1]))
    decoded_digest = _sha256(current)
    payload_digest = _sha256(payload)
    unsigned_header = _FRAME_HEADER.pack(
        FRAME_MAGIC,
        FRAME_MAJOR,
        FRAME_MINOR,
        FRAME_HEADER_BYTES,
        int(ordinal),
        flags,
        predictor,
        int(source_pts),
        len(current),
        len(payload),
        stored_previous,
        0,
        decoded_digest,
        payload_digest,
        bytes(32),
        bytes(4),
    )
    content_digest = _sha256(unsigned_header + payload)
    result = EncodedPolarFrame(
        int(ordinal),
        int(source_pts),
        flags,
        predictor,
        stored_previous,
        decoded_digest.hex(),
        payload_digest.hex(),
        content_digest.hex(),
        len(current),
        payload,
    )
    # Exercise the binary writer and its independent field checks now.
    result.to_bytes()
    return result


def decode_polar_frame(
    data: bytes | bytearray | memoryview,
    *,
    previous_polar_rgb_bytes: bytes | bytearray | memoryview | None = None,
    expected_previous_ordinal: int | None = None,
) -> tuple[EncodedPolarFrame, bytes]:
    """Parse, verify, and exactly reconstruct one UGFRM1 record."""
    raw = bytes(data)
    if len(raw) < FRAME_HEADER_BYTES:
        raise ChronoCodecError("UGFRM1 is truncated before its header")
    try:
        (
            magic,
            major,
            minor,
            header_bytes,
            ordinal,
            flags,
            predictor,
            source_pts,
            logical_bytes,
            payload_bytes,
            previous_ordinal,
            reserved,
            decoded_digest,
            payload_digest,
            content_digest,
            reserved_tail,
        ) = _FRAME_HEADER.unpack_from(raw)
    except struct.error as error:
        raise ChronoCodecError("UGFRM1 header is malformed") from error
    if magic != FRAME_MAGIC:
        raise ChronoCodecError("UGFRM1 magic mismatch")
    if (major, minor) != (FRAME_MAJOR, FRAME_MINOR):
        raise ChronoCodecError(f"unsupported UGFRM1 version {major}.{minor}")
    if header_bytes != FRAME_HEADER_BYTES or _FRAME_HEADER.size != FRAME_HEADER_BYTES:
        raise ChronoCodecError("UGFRM1 header ABI mismatch")
    if flags & ~FRAME_CHECKPOINT or reserved or reserved_tail != bytes(4):
        raise ChronoCodecError("UGFRM1 flags/reserved fields are invalid")
    if predictor not in _PREDICTOR_NAMES:
        raise ChronoCodecError("UGFRM1 predictor is unknown")
    if not 1 <= logical_bytes <= MAX_FRAME_BYTES or logical_bytes % 3:
        raise ChronoCodecError("UGFRM1 logical RGB byte count is invalid")
    if payload_bytes > MAX_FRAME_BYTES or len(raw) != header_bytes + payload_bytes:
        raise ChronoCodecError("UGFRM1 payload length mismatch")
    payload = raw[header_bytes:]
    if _sha256(payload) != payload_digest:
        raise ChronoCodecError("UGFRM1 payload SHA-256 mismatch")
    unsigned = bytearray(raw)
    # content digest starts at byte 124 in the fixed v1 header.
    unsigned[124:156] = bytes(32)
    if _sha256(bytes(unsigned)) != content_digest:
        raise ChronoCodecError("UGFRM1 content SHA-256 mismatch")
    checkpoint = bool(flags & FRAME_CHECKPOINT)
    if checkpoint:
        if previous_ordinal != NO_PREVIOUS_ORDINAL:
            raise ChronoCodecError("UGFRM1 checkpoint references a previous frame")
        if predictor not in (PREDICTOR_RAW, PREDICTOR_POLAR_SPATIAL_SUB):
            raise ChronoCodecError("UGFRM1 checkpoint uses a temporal predictor")
        previous = None
        if previous_polar_rgb_bytes is not None or expected_previous_ordinal is not None:
            raise ChronoCodecError("UGFRM1 checkpoint must decode independently")
    else:
        if previous_ordinal == NO_PREVIOUS_ORDINAL:
            raise ChronoCodecError("UGFRM1 delta frame has no previous ordinal")
        if expected_previous_ordinal is None or previous_ordinal != expected_previous_ordinal:
            raise ChronoCodecError("UGFRM1 previous ordinal does not match the replay chain")
        previous = _require_rgb_bytes(previous_polar_rgb_bytes or b"", logical_bytes)
    residual = decode_run_tokens(payload, expected_bytes=logical_bytes)
    decoded = _reverse_predictor(residual, previous, predictor)
    if _sha256(decoded) != decoded_digest:
        raise ChronoCodecError("UGFRM1 decoded RGB SHA-256 mismatch")
    record = EncodedPolarFrame(
        ordinal,
        source_pts,
        flags,
        predictor,
        previous_ordinal,
        decoded_digest.hex(),
        payload_digest.hex(),
        content_digest.hex(),
        logical_bytes,
        payload,
    )
    if record.to_bytes() != raw:
        raise ChronoCodecError("UGFRM1 is not in canonical form")
    return record, decoded


def decoded_stream_sha256(
    frames: Iterable[tuple[int, int, bytes | bytearray | memoryview]]
) -> str:
    """Hash exact `(ordinal, PTS, RGB length, RGB bytes)` records."""
    digest = hashlib.sha256()
    previous_ordinal = -1
    for ordinal, source_pts, rgb in frames:
        if int(ordinal) != previous_ordinal + 1:
            raise ChronoCodecError("decoded stream ordinals must be dense from zero")
        value = bytes(rgb)
        if not value or len(value) > MAX_FRAME_BYTES or len(value) % 3:
            raise ChronoCodecError("decoded stream frame byte count is invalid")
        digest.update(struct.pack("<IqQ", int(ordinal), int(source_pts), len(value)))
        digest.update(value)
        previous_ordinal = int(ordinal)
    if previous_ordinal < 0:
        raise ChronoCodecError("decoded stream must contain at least one frame")
    return digest.hexdigest()


def inspect_polar_pixel_permutation(
    data: bytes | bytearray | memoryview, *, uglut2_bytes: bytes
) -> dict[str, Any]:
    value = PolarPixelPermutation.from_bytes(data, uglut2_bytes=uglut2_bytes)
    payload = bytes(data)[_PIXEL_LUT_HEADER.size :]
    return {
        "schema": "ugtoms-polar-pixel-permutation-inspection-0.1",
        "magic": PIXEL_LUT_MAGIC.decode("ascii"),
        "version": f"{PIXEL_LUT_MAJOR}.{PIXEL_LUT_MINOR}",
        "width": value.width,
        "height": value.height,
        "center_x": value.center_x,
        "center_y": value.center_y,
        "pixel_count": value.pixel_count,
        "permutation": "polar_ordinal_to_cartesian_pixel_index",
        "bijection_verified": True,
        "all_pixels_covered_once": True,
        "uglut2_sha256": value.uglut2_sha256,
        "operator_sha256": value.operator_sha256,
        "payload_sha256": _sha256(payload).hex(),
        "bytes": len(bytes(data)),
    }


__all__ = [
    "ChronoCodecError",
    "EncodedPolarFrame",
    "FRAME_CHECKPOINT",
    "FRAME_HEADER_BYTES",
    "FRAME_MAGIC",
    "NO_PREVIOUS_ORDINAL",
    "PIXEL_LUT_MAGIC",
    "PREDICTOR_POLAR_SPATIAL_SUB",
    "PREDICTOR_RAW",
    "PREDICTOR_TEMPORAL_SPATIAL_SUB",
    "PREDICTOR_TEMPORAL_SUB",
    "PREDICTOR_TEMPORAL_XOR",
    "PolarPixelPermutation",
    "UGTC4D_EXTENSION",
    "UGTC4D_MAGIC",
    "decode_polar_frame",
    "decode_run_tokens",
    "decoded_stream_sha256",
    "encode_polar_frame",
    "encode_run_tokens",
    "gather_rgb_polar_cuda",
    "gather_rgb_polar_numpy",
    "generate_polar_pixel_permutation",
    "inspect_polar_pixel_permutation",
    "scatter_rgb_polar_numpy",
]
