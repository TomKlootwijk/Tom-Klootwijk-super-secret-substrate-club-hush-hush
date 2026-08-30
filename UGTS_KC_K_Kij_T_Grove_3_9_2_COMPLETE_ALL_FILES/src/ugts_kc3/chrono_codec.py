"""Integrated custom UGTOMS lossless chrono-raster frame ABI.

UGFRM2 stores exact residual evidence produced by the seed-regenerated UGLUT2
traversal and reversible prediction operators. Its entropy payload is the
codec-native UGRICE1/Rice/rANS stream. It contains neither a conventional
image/video bitstream nor a serialized per-pixel traversal.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import struct
from typing import Any, Iterable

from .chrono_entropy import (
    ChronoEntropyError,
    UGRICE_MAGIC,
    decode_adaptive_rice,
    optimize_adaptive_rice,
)
from .chrono_prediction import (
    PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER,
    PREDICTOR_CARTESIAN_MEDIAN_GREEN_SUBSTRATE_ORDER,
    PREDICTOR_NAMES,
    PREDICTOR_SUBSTRATE_MEDIAN_GREEN,
    PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN,
    SubstratePredictionPlan,
    decode_substrate_prediction_numpy,
    encode_substrate_prediction_numpy,
)


UGTC4D_MAGIC = b"UGTC4D1\0"
UGTC4D_EXTENSION = ".ugtc4d"

FRAME_MAGIC = b"UGFRM2\0\0"
FRAME_MAJOR = 2
FRAME_MINOR = 0
FRAME_HEADER_BYTES = 320
_FRAME_HEADER = struct.Struct(
    "<8sHHIIIIqqQQII32s32s32s32s32s32s32s28s"
)
_FRAME_CONTENT_DIGEST_OFFSET = 260

FRAME_CHECKPOINT = 1 << 0
NO_PREVIOUS_ORDINAL = 0xFFFFFFFF
MAX_FRAME_BYTES = 1 << 31


class ChronoCodecError(ValueError):
    """Malformed, noncanonical, or unverifiable UGTOMS codec data."""


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _digest(value: str, label: str) -> bytes:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ChronoCodecError(f"{label} must be lowercase SHA-256 hex")
    return bytes.fromhex(value)


def encode_run_tokens(data: bytes | bytearray | memoryview) -> bytes:
    """Canonical custom zero/repeat/literal coding for small metadata."""

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
            if candidate >= 3 or position - start + candidate > 64:
                break
            position += candidate
        literal = source[start:position]
        output.append(0x80 | (len(literal) - 1))
        output.extend(literal)
    return bytes(output)


def decode_run_tokens(
    data: bytes | bytearray | memoryview,
    *,
    expected_bytes: int,
    require_canonical: bool = True,
) -> bytes:
    """Bound and decode one custom metadata token stream."""

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
            output.extend(bytes(code + 1))
        elif kind == 1:
            if position >= len(source):
                raise ChronoCodecError("repeat token is truncated")
            value = source[position]
            position += 1
            if value == 0:
                raise ChronoCodecError("repeat token must not encode zero")
            output.extend(bytes((value,)) * (code + 3))
        elif kind == 2:
            end = position + code + 1
            if end > len(source):
                raise ChronoCodecError("literal token is truncated")
            output.extend(source[position:end])
            position = end
        else:
            raise ChronoCodecError("reserved UGTC4D run token encountered")
        if len(output) > expected_bytes:
            raise ChronoCodecError("run tokens exceed the declared logical length")
    if len(output) != expected_bytes:
        raise ChronoCodecError("run-token decoded length mismatch")
    result = bytes(output)
    if require_canonical and encode_run_tokens(result) != source:
        raise ChronoCodecError("run-token payload is not in canonical form")
    return result


@dataclass(frozen=True)
class EncodedSubstrateFrame:
    ordinal: int
    source_pts: int
    source_end_pts_exclusive: int
    flags: int
    predictor: int
    previous_ordinal: int
    logical_bytes: int
    uglut2_sha256: str
    traversal_recipe_sha256: str
    cartesian_sha256: str
    polar_sha256: str
    residual_sha256: str
    payload_sha256: str
    content_sha256: str
    payload: bytes

    @property
    def checkpoint(self) -> bool:
        return bool(self.flags & FRAME_CHECKPOINT)

    def _validate_fields(self) -> None:
        if not 0 <= int(self.ordinal) <= 0xFFFFFFFF:
            raise ChronoCodecError("UGFRM2 ordinal must fit uint32")
        if not -(1 << 63) <= int(self.source_pts) < (1 << 63):
            raise ChronoCodecError("UGFRM2 source PTS must fit int64")
        if not self.source_pts < self.source_end_pts_exclusive < (1 << 63):
            raise ChronoCodecError("UGFRM2 source interval is invalid")
        if self.flags & ~FRAME_CHECKPOINT:
            raise ChronoCodecError("UGFRM2 flags contain unsupported bits")
        if self.predictor not in PREDICTOR_NAMES:
            raise ChronoCodecError("UGFRM2 predictor is unsupported")
        intra = self.predictor in (
            PREDICTOR_SUBSTRATE_MEDIAN_GREEN,
            PREDICTOR_CARTESIAN_MEDIAN_GREEN_SUBSTRATE_ORDER,
            PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER,
        )
        if intra:
            if not self.checkpoint or self.previous_ordinal != NO_PREVIOUS_ORDINAL:
                raise ChronoCodecError("UGFRM2 intra frame must be an independent checkpoint")
        elif self.predictor == PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN:
            if self.checkpoint or not 0 <= self.previous_ordinal < self.ordinal:
                raise ChronoCodecError("UGFRM2 temporal dependency is invalid")
        if not 3 <= self.logical_bytes <= MAX_FRAME_BYTES or self.logical_bytes % 3:
            raise ChronoCodecError("UGFRM2 logical RGB byte count is invalid")
        for label, value in (
            ("UGLUT2 dependency", self.uglut2_sha256),
            ("traversal recipe", self.traversal_recipe_sha256),
            ("Cartesian RGB", self.cartesian_sha256),
            ("polar RGB", self.polar_sha256),
            ("residual", self.residual_sha256),
            ("payload", self.payload_sha256),
            ("content", self.content_sha256),
        ):
            _digest(value, label)
        if not self.payload.startswith(UGRICE_MAGIC):
            raise ChronoCodecError("UGFRM2 payload is not codec-native UGRICE1")
        if _sha256(self.payload).hex() != self.payload_sha256:
            raise ChronoCodecError("UGFRM2 payload SHA-256 field mismatch")

    def _header(self, content_digest: bytes) -> bytes:
        return _FRAME_HEADER.pack(
            FRAME_MAGIC,
            FRAME_MAJOR,
            FRAME_MINOR,
            FRAME_HEADER_BYTES,
            int(self.ordinal),
            int(self.flags),
            int(self.predictor),
            int(self.source_pts),
            int(self.source_end_pts_exclusive),
            int(self.logical_bytes),
            len(self.payload),
            int(self.previous_ordinal),
            0,
            _digest(self.uglut2_sha256, "UGLUT2 dependency"),
            _digest(self.traversal_recipe_sha256, "traversal recipe"),
            _digest(self.cartesian_sha256, "Cartesian RGB"),
            _digest(self.polar_sha256, "polar RGB"),
            _digest(self.residual_sha256, "residual"),
            _digest(self.payload_sha256, "payload"),
            content_digest,
            bytes(28),
        )

    def to_bytes(self) -> bytes:
        self._validate_fields()
        unsigned = self._header(bytes(32))
        content = _sha256(unsigned + self.payload)
        if content.hex() != self.content_sha256:
            raise ChronoCodecError("UGFRM2 content SHA-256 field mismatch")
        return self._header(content) + self.payload


def _cartesian_from_polar(polar: Any, plan: SubstratePredictionPlan) -> Any:
    import numpy as np

    result = np.empty((plan.pixel_count, 3), dtype=np.uint8)
    result[plan.traversal.astype(np.int64)] = polar
    return result.reshape(plan.height, plan.width, 3)


def encode_substrate_frame(
    polar_rgb: Any,
    plan: SubstratePredictionPlan,
    *,
    uglut2_bytes: bytes,
    traversal_recipe_bytes: bytes,
    ordinal: int,
    source_pts: int,
    source_end_pts_exclusive: int,
    predictor: int = PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER,
    previous_polar_rgb: Any | None = None,
    previous_ordinal: int | None = None,
    residual_bytes: bytes | bytearray | memoryview | None = None,
    entropy_block_sizes: Iterable[int] = (65_536, 131_072),
) -> EncodedSubstrateFrame:
    """Encode and independently replay-check one exact substrate frame."""

    import numpy as np

    polar = np.asarray(polar_rgb)
    if polar.shape != (plan.pixel_count, 3) or polar.dtype != np.uint8:
        raise ChronoCodecError("UGFRM2 polar RGB shape/type mismatch")
    previous = None if previous_polar_rgb is None else np.asarray(previous_polar_rgb)
    if predictor == PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN:
        if previous_ordinal is None:
            raise ChronoCodecError("temporal UGFRM2 frame needs a previous ordinal")
        stored_previous = int(previous_ordinal)
        flags = 0
    else:
        if previous_ordinal is not None:
            raise ChronoCodecError("intra UGFRM2 frame cannot reference a previous ordinal")
        stored_previous = NO_PREVIOUS_ORDINAL
        flags = FRAME_CHECKPOINT
    generated = (
        encode_substrate_prediction_numpy(
            polar,
            plan,
            predictor=predictor,
            previous_polar_rgb=previous,
        )
        if residual_bytes is None
        else bytes(residual_bytes)
    )
    if len(generated) != plan.pixel_count * 3:
        raise ChronoCodecError("UGFRM2 residual byte count mismatch")
    replayed = decode_substrate_prediction_numpy(
        generated,
        plan,
        predictor=predictor,
        previous_polar_rgb=previous,
    )
    if not np.array_equal(replayed, polar):
        raise ChronoCodecError("UGFRM2 residual replay does not reproduce polar RGB")
    payload, _entropy_stats = optimize_adaptive_rice(
        generated, block_sizes=tuple(entropy_block_sizes)
    )
    cartesian = _cartesian_from_polar(polar, plan)
    provisional = EncodedSubstrateFrame(
        int(ordinal),
        int(source_pts),
        int(source_end_pts_exclusive),
        flags,
        int(predictor),
        stored_previous,
        plan.pixel_count * 3,
        _sha256(bytes(uglut2_bytes)).hex(),
        _sha256(bytes(traversal_recipe_bytes)).hex(),
        _sha256(cartesian.tobytes()).hex(),
        _sha256(polar.tobytes()).hex(),
        _sha256(generated).hex(),
        _sha256(payload).hex(),
        "0" * 64,
        payload,
    )
    result = replace(
        provisional,
        content_sha256=_sha256(provisional._header(bytes(32)) + payload).hex(),
    )
    result.to_bytes()
    return result


def decode_substrate_frame(
    data: bytes | bytearray | memoryview,
    plan: SubstratePredictionPlan,
    *,
    uglut2_bytes: bytes,
    traversal_recipe_bytes: bytes,
    previous_polar_rgb: Any | None = None,
    expected_previous_ordinal: int | None = None,
) -> tuple[EncodedSubstrateFrame, Any, Any]:
    """Strictly decode one UGFRM2 to polar and Cartesian RGB8 arrays."""

    raw = bytes(data)
    if len(raw) < FRAME_HEADER_BYTES or _FRAME_HEADER.size != FRAME_HEADER_BYTES:
        raise ChronoCodecError("UGFRM2 header is truncated or its ABI drifted")
    try:
        fields = _FRAME_HEADER.unpack_from(raw)
    except struct.error as error:
        raise ChronoCodecError("UGFRM2 header is malformed") from error
    (
        magic,
        major,
        minor,
        header_bytes,
        ordinal,
        flags,
        predictor,
        source_pts,
        source_end_pts,
        logical_bytes,
        payload_bytes,
        previous_ordinal,
        reserved,
        uglut_digest,
        traversal_digest,
        cartesian_digest,
        polar_digest,
        residual_digest,
        payload_digest,
        content_digest,
        reserved_tail,
    ) = fields
    if magic != FRAME_MAGIC or (major, minor) != (FRAME_MAJOR, FRAME_MINOR):
        raise ChronoCodecError("unsupported UGFRM2 magic/version")
    if header_bytes != FRAME_HEADER_BYTES or reserved or reserved_tail != bytes(28):
        raise ChronoCodecError("UGFRM2 header/reserved bytes are invalid")
    if len(raw) != FRAME_HEADER_BYTES + payload_bytes:
        raise ChronoCodecError("UGFRM2 payload length mismatch")
    if uglut_digest != _sha256(bytes(uglut2_bytes)):
        raise ChronoCodecError("UGFRM2 UGLUT2 dependency mismatch")
    if traversal_digest != _sha256(bytes(traversal_recipe_bytes)):
        raise ChronoCodecError("UGFRM2 traversal recipe dependency mismatch")
    unsigned = bytearray(raw)
    unsigned[
        _FRAME_CONTENT_DIGEST_OFFSET : _FRAME_CONTENT_DIGEST_OFFSET + 32
    ] = bytes(32)
    if _sha256(bytes(unsigned)) != content_digest:
        raise ChronoCodecError("UGFRM2 content SHA-256 mismatch")
    payload = raw[FRAME_HEADER_BYTES:]
    if _sha256(payload) != payload_digest:
        raise ChronoCodecError("UGFRM2 payload SHA-256 mismatch")
    try:
        residual = decode_adaptive_rice(payload)
    except ChronoEntropyError as error:
        raise ChronoCodecError(f"UGFRM2 entropy payload failed: {error}") from error
    if len(residual) != logical_bytes or _sha256(residual) != residual_digest:
        raise ChronoCodecError("UGFRM2 residual length/SHA-256 mismatch")
    if predictor == PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN:
        if expected_previous_ordinal is None or previous_ordinal != expected_previous_ordinal:
            raise ChronoCodecError("UGFRM2 previous ordinal does not match replay")
        previous = previous_polar_rgb
    else:
        if expected_previous_ordinal is not None or previous_polar_rgb is not None:
            raise ChronoCodecError("UGFRM2 independent checkpoint received a dependency")
        previous = None
    polar = decode_substrate_prediction_numpy(
        residual,
        plan,
        predictor=predictor,
        previous_polar_rgb=previous,
    )
    cartesian = _cartesian_from_polar(polar, plan)
    if _sha256(polar.tobytes()) != polar_digest:
        raise ChronoCodecError("UGFRM2 polar RGB SHA-256 mismatch")
    if _sha256(cartesian.tobytes()) != cartesian_digest:
        raise ChronoCodecError("UGFRM2 Cartesian RGB SHA-256 mismatch")
    record = EncodedSubstrateFrame(
        ordinal,
        source_pts,
        source_end_pts,
        flags,
        predictor,
        previous_ordinal,
        logical_bytes,
        uglut_digest.hex(),
        traversal_digest.hex(),
        cartesian_digest.hex(),
        polar_digest.hex(),
        residual_digest.hex(),
        payload_digest.hex(),
        content_digest.hex(),
        payload,
    )
    if record.to_bytes() != raw:
        raise ChronoCodecError("UGFRM2 is not in canonical form")
    return record, polar, cartesian


class DecodedStreamHasher:
    """Incrementally bind exact Cartesian RGB8, PTS, intervals, and profile."""

    def __init__(
        self, *, width: int, height: int, time_base_num: int, time_base_den: int
    ) -> None:
        if width < 1 or height < 1 or time_base_num < 1 or time_base_den < 1:
            raise ChronoCodecError("decoded stream profile is invalid")
        self.width = int(width)
        self.height = int(height)
        self._next = 0
        self._digest = hashlib.sha256()
        self._digest.update(b"UGTC4D-decoded-cartesian-rgb8-stream-v2\0")
        self._digest.update(
            struct.pack("<IIQQ", width, height, time_base_num, time_base_den)
        )

    def update(
        self,
        ordinal: int,
        source_pts: int,
        source_end_pts_exclusive: int,
        cartesian_rgb: bytes | bytearray | memoryview,
    ) -> None:
        if int(ordinal) != self._next:
            raise ChronoCodecError("decoded stream ordinals must be dense from zero")
        value = bytes(cartesian_rgb)
        if len(value) != self.width * self.height * 3:
            raise ChronoCodecError("decoded Cartesian frame byte count mismatch")
        if source_end_pts_exclusive <= source_pts:
            raise ChronoCodecError("decoded stream source interval is invalid")
        self._digest.update(
            struct.pack(
                "<IqqQ",
                int(ordinal),
                int(source_pts),
                int(source_end_pts_exclusive),
                len(value),
            )
        )
        self._digest.update(value)
        self._next += 1

    def hexdigest(self) -> str:
        if self._next == 0:
            raise ChronoCodecError("decoded stream must contain at least one frame")
        return self._digest.hexdigest()


def decoded_stream_sha256(
    frames: Iterable[tuple[int, int, int, bytes | bytearray | memoryview]],
    *,
    width: int,
    height: int,
    time_base_num: int,
    time_base_den: int,
) -> str:
    hasher = DecodedStreamHasher(
        width=width,
        height=height,
        time_base_num=time_base_num,
        time_base_den=time_base_den,
    )
    for ordinal, pts, end_pts, rgb in frames:
        hasher.update(ordinal, pts, end_pts, rgb)
    return hasher.hexdigest()


__all__ = [
    "ChronoCodecError",
    "DecodedStreamHasher",
    "EncodedSubstrateFrame",
    "FRAME_CHECKPOINT",
    "FRAME_HEADER_BYTES",
    "FRAME_MAGIC",
    "NO_PREVIOUS_ORDINAL",
    "UGTC4D_EXTENSION",
    "UGTC4D_MAGIC",
    "decode_run_tokens",
    "decode_substrate_frame",
    "decoded_stream_sha256",
    "encode_run_tokens",
    "encode_substrate_frame",
]
