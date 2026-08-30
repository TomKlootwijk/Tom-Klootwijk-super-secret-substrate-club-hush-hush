"""UGTC4D custom multi-section container.

The container is deliberately simple and independently verifiable.  It does
not wrap ZIP, Matroska, ISO BMFF, DEFLATE, or another media/container codec.
Section payloads are either raw UGTC4D records or the custom canonical run
tokens defined in :mod:`ugts_kc3.chrono_codec`.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import struct
from typing import Any, Iterable, Mapping

from .chrono_codec import (
    ChronoCodecError,
    UGTC4D_MAGIC,
    decode_run_tokens,
    encode_run_tokens,
)


UGTC4D_MAJOR = 1
UGTC4D_MINOR = 0
UGTC4D_ENDIAN = 0x01020304
UGTC4D_HEADER_BYTES = 256
UGTC4D_DIRECTORY_ENTRY_BYTES = 112
UGTC4D_ALIGNMENT = 64

UGTC4D_FLAG_LOSSLESS_RGB8 = 1 << 0
UGTC4D_FLAG_CUSTOM_PREDICTION = 1 << 1
UGTC4D_FLAG_UGLUT2_POLAR = 1 << 2
UGTC4D_FLAG_CHRONO_GEOMETRY = 1 << 3

SECTION_FLAG_RUN_TOKENS = 1 << 0
SECTION_FLAG_OPTIONAL = 1 << 1

_HEADER = struct.Struct(
    "<8sHHIIIIIIHHIIqqQQ6dIIQQ32s32s32s8s"
)
_DIRECTORY_ENTRY = struct.Struct("<8sIIQQQQQ32s16s8s")

_CONTENT_DIGEST_OFFSET = 216

MAX_UGTC4D_BYTES = 1 << 40
MAX_UGTC4D_SECTIONS = 1_000_000
MAX_SECTION_BYTES = 1 << 36


def _align(value: int, alignment: int = UGTC4D_ALIGNMENT) -> int:
    return (int(value) + alignment - 1) // alignment * alignment


def _digest_hex(value: str, label: str) -> bytes:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ChronoCodecError(f"{label} must be lowercase SHA-256 hex")
    return bytes.fromhex(value)


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _kind_bytes(kind: str) -> bytes:
    if not isinstance(kind, str) or not 1 <= len(kind) <= 8:
        raise ChronoCodecError("UGTC4D section kind must use 1..8 ASCII characters")
    try:
        encoded = kind.encode("ascii")
    except UnicodeEncodeError as error:
        raise ChronoCodecError("UGTC4D section kind must be ASCII") from error
    if any(character < 0x30 or character > 0x5A for character in encoded):
        raise ChronoCodecError(
            "UGTC4D section kind must use uppercase ASCII letters/digits"
        )
    return encoded.ljust(8, b"\0")


def _kind_text(value: bytes) -> str:
    raw = value.rstrip(b"\0")
    if not raw or value != raw.ljust(8, b"\0"):
        raise ChronoCodecError("UGTC4D directory kind padding is noncanonical")
    try:
        result = raw.decode("ascii")
    except UnicodeDecodeError as error:
        raise ChronoCodecError("UGTC4D directory kind is not ASCII") from error
    if _kind_bytes(result) != value:
        raise ChronoCodecError("UGTC4D directory kind is noncanonical")
    return result


def _semantic_address(
    kind_bytes: bytes,
    version: int,
    flags: int,
    record_start: int,
    record_count: int,
    logical_bytes: int,
    stored_digest: bytes,
) -> bytes:
    preimage = (
        b"UGTC4D-section-semantics-v1\0"
        + kind_bytes
        + struct.pack(
            "<IIQQQ", version, flags, record_start, record_count, logical_bytes
        )
        + stored_digest
    )
    return hashlib.sha256(preimage).digest()[:16]


@dataclass(frozen=True)
class Ugtc4dSection:
    kind: str
    version: int
    flags: int
    record_start: int
    record_count: int
    logical_bytes: int
    stored: bytes

    @classmethod
    def raw(
        cls,
        kind: str,
        data: bytes | bytearray | memoryview,
        *,
        version: int = 1,
        flags: int = 0,
        record_start: int = 0,
        record_count: int = 1,
    ) -> "Ugtc4dSection":
        value = bytes(data)
        return cls(
            kind,
            version,
            flags & ~SECTION_FLAG_RUN_TOKENS,
            record_start,
            record_count,
            len(value),
            value,
        )

    @classmethod
    def run_coded(
        cls,
        kind: str,
        logical: bytes | bytearray | memoryview,
        *,
        version: int = 1,
        flags: int = 0,
        record_start: int = 0,
        record_count: int = 1,
    ) -> "Ugtc4dSection":
        value = bytes(logical)
        return cls(
            kind,
            version,
            flags | SECTION_FLAG_RUN_TOKENS,
            record_start,
            record_count,
            len(value),
            encode_run_tokens(value),
        )

    @classmethod
    def canonical_json(
        cls,
        kind: str,
        value: Mapping[str, Any],
        *,
        version: int = 1,
        flags: int = 0,
        record_start: int = 0,
        record_count: int = 1,
    ) -> "Ugtc4dSection":
        return cls.run_coded(
            kind,
            _canonical_json_bytes(value),
            version=version,
            flags=flags,
            record_start=record_start,
            record_count=record_count,
        )

    def validate(self) -> None:
        _kind_bytes(self.kind)
        if not 1 <= int(self.version) <= 0xFFFFFFFF:
            raise ChronoCodecError("UGTC4D section version is invalid")
        if self.flags & ~(SECTION_FLAG_RUN_TOKENS | SECTION_FLAG_OPTIONAL):
            raise ChronoCodecError("UGTC4D section flags contain unsupported bits")
        if not 0 <= int(self.record_start) <= (1 << 64) - 1:
            raise ChronoCodecError("UGTC4D section record start is invalid")
        if not 1 <= int(self.record_count) <= (1 << 64) - 1:
            raise ChronoCodecError("UGTC4D section record count is invalid")
        if not 0 <= int(self.logical_bytes) <= MAX_SECTION_BYTES:
            raise ChronoCodecError("UGTC4D section logical byte count is invalid")
        if len(self.stored) > MAX_SECTION_BYTES:
            raise ChronoCodecError("UGTC4D section stored byte count exceeds its limit")
        logical = self.logical()
        if len(logical) != self.logical_bytes:
            raise ChronoCodecError("UGTC4D section logical byte count mismatch")

    def logical(self) -> bytes:
        if self.flags & SECTION_FLAG_RUN_TOKENS:
            return decode_run_tokens(
                self.stored, expected_bytes=self.logical_bytes, require_canonical=True
            )
        if len(self.stored) != self.logical_bytes:
            raise ChronoCodecError("raw UGTC4D section stored/logical size mismatch")
        return bytes(self.stored)

    @property
    def stored_sha256(self) -> bytes:
        return hashlib.sha256(self.stored).digest()

    @property
    def semantic_address(self) -> bytes:
        return _semantic_address(
            _kind_bytes(self.kind),
            self.version,
            self.flags,
            self.record_start,
            self.record_count,
            self.logical_bytes,
            self.stored_sha256,
        )


@dataclass(frozen=True)
class Ugtc4dHeader:
    flags: int
    width: int
    height: int
    frame_count: int
    checkpoint_interval: int
    first_source_pts: int
    end_source_pts_exclusive: int
    time_base_num: int
    time_base_den: int
    center_x: float
    center_y: float
    r0: float
    core_radius: float
    rho_min: float
    rho_max: float
    lut_resolution: int
    source_sha256: str
    decoded_stream_sha256: str

    def validate(self) -> None:
        required = (
            UGTC4D_FLAG_LOSSLESS_RGB8
            | UGTC4D_FLAG_CUSTOM_PREDICTION
            | UGTC4D_FLAG_UGLUT2_POLAR
            | UGTC4D_FLAG_CHRONO_GEOMETRY
        )
        if self.flags != required:
            raise ChronoCodecError("UGTC4D 0.1 header flags do not select the literal profile")
        if not 1 <= self.width <= 65_535 or not 1 <= self.height <= 65_535:
            raise ChronoCodecError("UGTC4D dimensions must fit uint16")
        if not 1 <= self.frame_count <= 1_000_000:
            raise ChronoCodecError("UGTC4D frame count is invalid")
        if not 1 <= self.checkpoint_interval <= self.frame_count:
            raise ChronoCodecError("UGTC4D checkpoint interval is invalid")
        if self.end_source_pts_exclusive <= self.first_source_pts:
            raise ChronoCodecError("UGTC4D source PTS interval is invalid")
        if not 1 <= self.time_base_num <= (1 << 63) - 1:
            raise ChronoCodecError("UGTC4D time-base numerator is invalid")
        if not 1 <= self.time_base_den <= (1 << 63) - 1:
            raise ChronoCodecError("UGTC4D time-base denominator is invalid")
        if any(
            not math.isfinite(value)
            for value in (
                self.center_x,
                self.center_y,
                self.r0,
                self.core_radius,
                self.rho_min,
                self.rho_max,
            )
        ):
            raise ChronoCodecError("UGTC4D chart values must be finite")
        if self.r0 <= 0 or self.core_radius <= 0 or self.rho_min >= self.rho_max:
            raise ChronoCodecError("UGTC4D log-polar profile is invalid")
        if not 16 <= self.lut_resolution <= 4096:
            raise ChronoCodecError("UGTC4D UGLUT2 resolution is invalid")
        _digest_hex(self.source_sha256, "source_sha256")
        _digest_hex(self.decoded_stream_sha256, "decoded_stream_sha256")


@dataclass(frozen=True)
class Ugtc4dInspection:
    header: Ugtc4dHeader
    sections: tuple[Ugtc4dSection, ...]
    content_sha256: str
    byte_length: int

    def sections_of_kind(self, kind: str) -> tuple[Ugtc4dSection, ...]:
        return tuple(section for section in self.sections if section.kind == kind)


def build_ugtc4d_bytes(
    header: Ugtc4dHeader, sections: Iterable[Ugtc4dSection]
) -> bytes:
    """Build a complete canonical UGTC4D file in memory.

    The streaming file writer uses the same ABI; this bounded helper is the
    independent test/oracle path.
    """
    header.validate()
    ordered = sorted(
        tuple(sections), key=lambda item: (_kind_bytes(item.kind), item.record_start)
    )
    if not 1 <= len(ordered) <= MAX_UGTC4D_SECTIONS:
        raise ChronoCodecError("UGTC4D section count is invalid")
    previous_key: tuple[bytes, int] | None = None
    for section in ordered:
        section.validate()
        key = (_kind_bytes(section.kind), section.record_start)
        if previous_key is not None and key <= previous_key:
            raise ChronoCodecError("UGTC4D sections are not uniquely canonical")
        previous_key = key

    output = bytearray(UGTC4D_HEADER_BYTES)
    entries: list[bytes] = []
    for section in ordered:
        offset = _align(len(output))
        output.extend(bytes(offset - len(output)))
        output.extend(section.stored)
        entries.append(
            _DIRECTORY_ENTRY.pack(
                _kind_bytes(section.kind),
                section.version,
                section.flags,
                offset,
                len(section.stored),
                section.logical_bytes,
                section.record_start,
                section.record_count,
                section.stored_sha256,
                section.semantic_address,
                bytes(8),
            )
        )
    directory_offset = _align(len(output))
    output.extend(bytes(directory_offset - len(output)))
    directory = b"".join(entries)
    output.extend(directory)
    if len(output) > MAX_UGTC4D_BYTES:
        raise ChronoCodecError("UGTC4D output exceeds its safety limit")
    raw_header = _HEADER.pack(
        UGTC4D_MAGIC,
        UGTC4D_MAJOR,
        UGTC4D_MINOR,
        UGTC4D_ENDIAN,
        UGTC4D_HEADER_BYTES,
        header.flags,
        header.width,
        header.height,
        1,  # RGB8
        3,
        8,
        header.frame_count,
        header.checkpoint_interval,
        header.first_source_pts,
        header.end_source_pts_exclusive,
        header.time_base_num,
        header.time_base_den,
        header.center_x,
        header.center_y,
        header.r0,
        header.core_radius,
        header.rho_min,
        header.rho_max,
        header.lut_resolution,
        len(ordered),
        directory_offset,
        len(directory),
        _digest_hex(header.source_sha256, "source_sha256"),
        _digest_hex(header.decoded_stream_sha256, "decoded_stream_sha256"),
        bytes(32),
        bytes(8),
    )
    if len(raw_header) != UGTC4D_HEADER_BYTES:
        raise AssertionError("UGTC4D header struct size drift")
    output[:UGTC4D_HEADER_BYTES] = raw_header
    content_digest = hashlib.sha256(output).digest()
    output[_CONTENT_DIGEST_OFFSET : _CONTENT_DIGEST_OFFSET + 32] = content_digest
    result = bytes(output)
    # Require the independent parser to accept the emitted bytes.
    inspect_ugtc4d_bytes(result)
    return result


def inspect_ugtc4d_bytes(
    data: bytes | bytearray | memoryview,
    *,
    required_kinds: Iterable[str] = (
        "MANIFEST",
        "OPERATOR",
        "UGLUT2",
        "POLARPIX",
        "FRAME",
        "OBSERVE",
        "HYPOTHES",
        "GEOMETRY",
        "NOVELTY",
        "CHECKPNT",
        "SCENE3D",
    ),
) -> Ugtc4dInspection:
    raw = bytes(data)
    if not UGTC4D_HEADER_BYTES <= len(raw) <= MAX_UGTC4D_BYTES:
        raise ChronoCodecError("UGTC4D byte length is outside its safety domain")
    if _HEADER.size != UGTC4D_HEADER_BYTES:
        raise AssertionError("UGTC4D header struct size drift")
    try:
        (
            magic,
            major,
            minor,
            endian,
            header_bytes,
            flags,
            width,
            height,
            color_model,
            channels,
            bit_depth,
            frame_count,
            checkpoint_interval,
            first_pts,
            end_pts,
            time_num,
            time_den,
            center_x,
            center_y,
            r0,
            core_radius,
            rho_min,
            rho_max,
            lut_resolution,
            section_count,
            directory_offset,
            directory_bytes,
            source_digest,
            decoded_digest,
            content_digest,
            reserved,
        ) = _HEADER.unpack_from(raw)
    except struct.error as error:
        raise ChronoCodecError("UGTC4D header is malformed") from error
    if magic != UGTC4D_MAGIC:
        raise ChronoCodecError("UGTC4D magic mismatch")
    if (major, minor) != (UGTC4D_MAJOR, UGTC4D_MINOR):
        raise ChronoCodecError(f"unsupported UGTC4D version {major}.{minor}")
    if endian != UGTC4D_ENDIAN or header_bytes != UGTC4D_HEADER_BYTES:
        raise ChronoCodecError("UGTC4D endian/header ABI mismatch")
    if (color_model, channels, bit_depth) != (1, 3, 8):
        raise ChronoCodecError("UGTC4D 0.1 requires packed RGB8")
    if reserved != bytes(8):
        raise ChronoCodecError("UGTC4D header reserved bytes are nonzero")
    if not 1 <= section_count <= MAX_UGTC4D_SECTIONS:
        raise ChronoCodecError("UGTC4D section count is invalid")
    if directory_bytes != section_count * UGTC4D_DIRECTORY_ENTRY_BYTES:
        raise ChronoCodecError("UGTC4D directory byte count is invalid")
    if directory_offset % UGTC4D_ALIGNMENT:
        raise ChronoCodecError("UGTC4D directory is not aligned")
    if directory_offset < header_bytes or directory_offset + directory_bytes != len(raw):
        raise ChronoCodecError("UGTC4D directory range is invalid")
    unsigned = bytearray(raw)
    unsigned[_CONTENT_DIGEST_OFFSET : _CONTENT_DIGEST_OFFSET + 32] = bytes(32)
    if hashlib.sha256(unsigned).digest() != content_digest:
        raise ChronoCodecError("UGTC4D whole-file SHA-256 mismatch")

    header = Ugtc4dHeader(
        flags,
        width,
        height,
        frame_count,
        checkpoint_interval,
        first_pts,
        end_pts,
        time_num,
        time_den,
        center_x,
        center_y,
        r0,
        core_radius,
        rho_min,
        rho_max,
        lut_resolution,
        source_digest.hex(),
        decoded_digest.hex(),
    )
    header.validate()

    sections: list[Ugtc4dSection] = []
    occupied: list[tuple[int, int]] = []
    previous_key: tuple[bytes, int] | None = None
    offset = directory_offset
    for _index in range(section_count):
        (
            kind_raw,
            version,
            section_flags,
            stored_offset,
            stored_bytes,
            logical_bytes,
            record_start,
            record_count,
            stored_digest,
            semantic_address,
            entry_reserved,
        ) = _DIRECTORY_ENTRY.unpack_from(raw, offset)
        offset += UGTC4D_DIRECTORY_ENTRY_BYTES
        kind = _kind_text(kind_raw)
        key = (kind_raw, record_start)
        if previous_key is not None and key <= previous_key:
            raise ChronoCodecError("UGTC4D directory entries are not canonical")
        previous_key = key
        if entry_reserved != bytes(8):
            raise ChronoCodecError("UGTC4D directory reserved bytes are nonzero")
        if stored_offset % UGTC4D_ALIGNMENT:
            raise ChronoCodecError("UGTC4D section is not aligned")
        stored_end = stored_offset + stored_bytes
        if (
            stored_offset < header_bytes
            or stored_end > directory_offset
            or stored_bytes > MAX_SECTION_BYTES
        ):
            raise ChronoCodecError("UGTC4D section range is invalid")
        for prior_start, prior_end in occupied:
            if stored_offset < prior_end and prior_start < stored_end:
                raise ChronoCodecError("UGTC4D sections overlap")
        occupied.append((stored_offset, stored_end))
        stored = raw[stored_offset:stored_end]
        if hashlib.sha256(stored).digest() != stored_digest:
            raise ChronoCodecError("UGTC4D section SHA-256 mismatch")
        expected_address = _semantic_address(
            kind_raw,
            version,
            section_flags,
            record_start,
            record_count,
            logical_bytes,
            stored_digest,
        )
        if semantic_address != expected_address:
            raise ChronoCodecError("UGTC4D section semantic address mismatch")
        section = Ugtc4dSection(
            kind,
            version,
            section_flags,
            record_start,
            record_count,
            logical_bytes,
            stored,
        )
        section.validate()
        sections.append(section)

    kinds = {section.kind for section in sections}
    missing = sorted(set(required_kinds) - kinds)
    if missing:
        raise ChronoCodecError("UGTC4D is missing required sections: " + ", ".join(missing))
    frames = [section for section in sections if section.kind == "FRAME"]
    if len(frames) != frame_count:
        raise ChronoCodecError("UGTC4D FRAME section count disagrees with its header")
    if [section.record_start for section in frames] != list(range(frame_count)):
        raise ChronoCodecError("UGTC4D FRAME records are not dense from zero")
    if any(section.record_count != 1 for section in frames):
        raise ChronoCodecError("UGTC4D FRAME section record counts must equal one")

    return Ugtc4dInspection(header, tuple(sections), content_digest.hex(), len(raw))


def decoded_json_section(section: Ugtc4dSection) -> dict[str, Any]:
    """Decode one canonical JSON section and require canonical reserialization."""
    logical = section.logical()
    try:
        value = json.loads(logical.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ChronoCodecError(f"UGTC4D {section.kind} section is not valid JSON") from error
    if not isinstance(value, dict):
        raise ChronoCodecError(f"UGTC4D {section.kind} JSON root must be an object")
    if _canonical_json_bytes(value) != logical:
        raise ChronoCodecError(f"UGTC4D {section.kind} JSON is not canonical")
    return value


__all__ = [
    "SECTION_FLAG_OPTIONAL",
    "SECTION_FLAG_RUN_TOKENS",
    "UGTC4D_ALIGNMENT",
    "UGTC4D_DIRECTORY_ENTRY_BYTES",
    "UGTC4D_FLAG_CHRONO_GEOMETRY",
    "UGTC4D_FLAG_CUSTOM_PREDICTION",
    "UGTC4D_FLAG_LOSSLESS_RGB8",
    "UGTC4D_FLAG_UGLUT2_POLAR",
    "UGTC4D_HEADER_BYTES",
    "Ugtc4dHeader",
    "Ugtc4dInspection",
    "Ugtc4dSection",
    "build_ugtc4d_bytes",
    "decoded_json_section",
    "inspect_ugtc4d_bytes",
]
