"""Deterministic custom entropy coding for UGTOMS residual byte streams.

``UGRICE1`` is deliberately small and self-contained.  It does not wrap or
invoke DEFLATE, Zstandard, an image codec, or a video codec.  Each block is
stored verbatim, as a Golomb--Rice bitstream after the reversible modulo-256
signed/zigzag residual mapping, or as a codec-native static byte-rANS stream.
The encoder chooses the byte-smallest representation independently for every
block.

The binary form is canonical: block size, Rice parameter, raw fallback,
padding, reserved fields, lengths, and all digest preimages have exactly one
accepted representation.  A strict decoder rejects a byte stream which
decodes successfully but was not produced by the canonical encoder.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import math
import struct
from typing import Iterable


UGRICE_MAGIC = b"UGRICE1\0"
UGRICE_MAJOR = 1
UGRICE_MINOR = 0
UGRICE_HEADER_BYTES = 160

# magic, version, header bytes, flags, logical bytes, block bytes/count,
# payload bytes, decoded/payload/content SHA-256, reserved.
_STREAM_HEADER = struct.Struct("<8sHHIIQIIQ32s32s32s20s")
_CONTENT_DIGEST_OFFSET = 108

# method, Rice k, reserved, exact encoded bit count.
_BLOCK_HEADER = struct.Struct("<BBHI")

UGRICE_FLAG_SIGNED_MOD256_ZIGZAG = 1 << 0
_SUPPORTED_FLAGS = UGRICE_FLAG_SIGNED_MOD256_ZIGZAG

BLOCK_RAW = 0
BLOCK_RICE = 1
BLOCK_RANS = 2

RANS_SCALE_BITS = 12
RANS_TOTAL_FREQUENCY = 1 << RANS_SCALE_BITS
RANS_BYTE_L = 1 << 23

MIN_BLOCK_BYTES = 256
MAX_BLOCK_BYTES = 1 << 20
DEFAULT_BLOCK_BYTES = 1 << 14
MAX_LOGICAL_BYTES = 1 << 34


class ChronoEntropyError(ValueError):
    """A malformed, noncanonical, or unsupported UGRICE1 stream."""


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _validate_block_bytes(block_bytes: int) -> int:
    if isinstance(block_bytes, bool) or not isinstance(block_bytes, int):
        raise ChronoEntropyError("UGRICE1 block size must be an integer")
    if not MIN_BLOCK_BYTES <= block_bytes <= MAX_BLOCK_BYTES:
        raise ChronoEntropyError(
            f"UGRICE1 block size must be in [{MIN_BLOCK_BYTES}, {MAX_BLOCK_BYTES}]"
        )
    if block_bytes & (block_bytes - 1):
        raise ChronoEntropyError("UGRICE1 block size must be a power of two")
    return block_bytes


def _map_residual_byte(value: int) -> int:
    """Map a modulo-256 residual to unsigned zigzag without information loss."""
    return value << 1 if value <= 127 else ((256 - value) << 1) - 1


def _unmap_residual_byte(value: int) -> int:
    return value >> 1 if not value & 1 else (256 - ((value + 1) >> 1)) & 0xFF


def _rice_bit_count(mapped: bytes | bytearray, k: int) -> int:
    return sum((value >> k) + 1 + k for value in mapped)


try:  # Optional acceleration; it cannot alter the binary result.
    import numpy as _np
    from numba import njit as _njit
except ImportError:  # pragma: no cover - exercised on minimal installations.
    _np = None
    _njit = None


if _njit is not None:

    @_njit(cache=True)
    def _encode_rice_numba(mapped, k, bit_count):  # pragma: no cover - JIT body
        output = _np.zeros((bit_count + 7) // 8, dtype=_np.uint8)
        bit_position = 0
        mask = (1 << k) - 1
        for value_raw in mapped:
            value = int(value_raw)
            quotient = value >> k
            # Unary is q zero bits followed by one.  The output was zeroed, so
            # only the terminator and set remainder bits need writes.
            bit_position += quotient
            output[bit_position >> 3] |= 1 << (7 - (bit_position & 7))
            bit_position += 1
            remainder = value & mask
            for shift in range(k - 1, -1, -1):
                if remainder & (1 << shift):
                    output[bit_position >> 3] |= 1 << (7 - (bit_position & 7))
                bit_position += 1
        return output

    @_njit(cache=True)
    def _decode_rice_numba(payload, bit_count, k, symbol_count):  # pragma: no cover
        output = _np.empty(symbol_count, dtype=_np.uint8)
        bit_position = 0
        status = 0
        for index in range(symbol_count):
            quotient = 0
            while True:
                if bit_position >= bit_count:
                    status = 1  # truncated unary code
                    return output, bit_position, status
                bit = (int(payload[bit_position >> 3]) >> (7 - (bit_position & 7))) & 1
                bit_position += 1
                if bit:
                    break
                quotient += 1
                if quotient > (255 >> k):
                    status = 2  # symbol outside the byte alphabet
                    return output, bit_position, status
            remainder = 0
            for _unused in range(k):
                if bit_position >= bit_count:
                    status = 1
                    return output, bit_position, status
                bit = (int(payload[bit_position >> 3]) >> (7 - (bit_position & 7))) & 1
                bit_position += 1
                remainder = (remainder << 1) | bit
            value = (quotient << k) | remainder
            if value > 255:
                status = 2
                return output, bit_position, status
            output[index] = value
        return output, bit_position, status

    @_njit(cache=True)
    def _encode_rans_numba(source, frequencies, starts):  # pragma: no cover
        # Byte-rANS emits at most one renormalization byte per input byte for
        # this scale/lower-bound pair.
        reverse_output = _np.empty(len(source) + 8, dtype=_np.uint8)
        output_count = 0
        state = RANS_BYTE_L
        for index in range(len(source) - 1, -1, -1):
            symbol = int(source[index])
            frequency = int(frequencies[symbol])
            start = int(starts[symbol])
            maximum = ((RANS_BYTE_L >> RANS_SCALE_BITS) << 8) * frequency
            while state >= maximum:
                reverse_output[output_count] = state & 0xFF
                output_count += 1
                state >>= 8
            state = (
                (state // frequency) << RANS_SCALE_BITS
            ) + (state % frequency) + start
        return state, reverse_output[:output_count]

    @_njit(cache=True)
    def _decode_rans_numba(
        encoded, state, frequencies, starts, lookup, symbol_count
    ):  # pragma: no cover
        output = _np.empty(symbol_count, dtype=_np.uint8)
        position = 0
        status = 0
        for index in range(symbol_count):
            slot = state & (RANS_TOTAL_FREQUENCY - 1)
            symbol = int(lookup[slot])
            if symbol < 0:
                status = 1
                return output, position, state, status
            output[index] = symbol
            state = int(frequencies[symbol]) * (state >> RANS_SCALE_BITS) + (
                slot - int(starts[symbol])
            )
            while state < RANS_BYTE_L:
                if position >= len(encoded):
                    status = 2
                    return output, position, state, status
                state = (state << 8) | int(encoded[position])
                position += 1
        return output, position, state, status


def _mapped_bytes(source: bytes) -> bytes:
    if _np is None or len(source) < 1024:
        return bytes(_map_residual_byte(value) for value in source)
    values = _np.frombuffer(source, dtype=_np.uint8).astype(_np.uint16)
    mapped = _np.where(values <= 127, values << 1, ((256 - values) << 1) - 1)
    return mapped.astype(_np.uint8).tobytes()


def _best_rice_parameter(mapped: bytes) -> tuple[int, int]:
    """Return ``(k, exact_bits)`` with deterministic low-k tie breaking."""
    if not mapped:
        raise ChronoEntropyError("a UGRICE1 Rice block cannot be empty")
    if _np is not None and len(mapped) >= 1024:
        values = _np.frombuffer(mapped, dtype=_np.uint8).astype(_np.uint64)
        counts = [int((values >> k).sum()) + len(mapped) * (k + 1) for k in range(8)]
    else:
        counts = [_rice_bit_count(mapped, k) for k in range(8)]
    return min(enumerate(counts), key=lambda item: (item[1], item[0]))


def _encode_rice_bits(mapped: bytes, k: int, bit_count: int) -> bytes:
    if _njit is not None and _np is not None and len(mapped) >= 1024:
        values = _np.frombuffer(mapped, dtype=_np.uint8)
        return _encode_rice_numba(values, k, bit_count).tobytes()
    output = bytearray((bit_count + 7) // 8)
    bit_position = 0
    mask = (1 << k) - 1
    for value in mapped:
        quotient = value >> k
        bit_position += quotient
        output[bit_position >> 3] |= 1 << (7 - (bit_position & 7))
        bit_position += 1
        remainder = value & mask
        for shift in range(k - 1, -1, -1):
            if remainder & (1 << shift):
                output[bit_position >> 3] |= 1 << (7 - (bit_position & 7))
            bit_position += 1
    if bit_position != bit_count:
        raise AssertionError("UGRICE1 internal bit count mismatch")
    return bytes(output)


def _decode_rice_bits(payload: bytes, bit_count: int, k: int, symbols: int) -> bytes:
    if _njit is not None and _np is not None and symbols >= 1024:
        encoded = _np.frombuffer(payload, dtype=_np.uint8)
        mapped, consumed, status = _decode_rice_numba(encoded, bit_count, k, symbols)
        if status == 1:
            raise ChronoEntropyError("UGRICE1 Rice block has a truncated codeword")
        if status == 2:
            raise ChronoEntropyError("UGRICE1 Rice symbol exceeds the byte alphabet")
        if int(consumed) != bit_count:
            raise ChronoEntropyError("UGRICE1 Rice block has unused coded bits")
        values = mapped.astype(_np.uint16)
        decoded = _np.where(
            (values & 1) == 0,
            values >> 1,
            (256 - ((values + 1) >> 1)) & 0xFF,
        )
        return decoded.astype(_np.uint8).tobytes()

    result = bytearray(symbols)
    bit_position = 0
    for index in range(symbols):
        quotient = 0
        while True:
            if bit_position >= bit_count:
                raise ChronoEntropyError("UGRICE1 Rice block has a truncated codeword")
            bit = (payload[bit_position >> 3] >> (7 - (bit_position & 7))) & 1
            bit_position += 1
            if bit:
                break
            quotient += 1
            if quotient > 255 >> k:
                raise ChronoEntropyError("UGRICE1 Rice symbol exceeds the byte alphabet")
        remainder = 0
        for _unused in range(k):
            if bit_position >= bit_count:
                raise ChronoEntropyError("UGRICE1 Rice block has a truncated codeword")
            bit = (payload[bit_position >> 3] >> (7 - (bit_position & 7))) & 1
            bit_position += 1
            remainder = (remainder << 1) | bit
        value = (quotient << k) | remainder
        if value > 255:
            raise ChronoEntropyError("UGRICE1 Rice symbol exceeds the byte alphabet")
        result[index] = _unmap_residual_byte(value)
    if bit_position != bit_count:
        raise ChronoEntropyError("UGRICE1 Rice block has unused coded bits")
    return bytes(result)


def _encode_uleb128(value: int) -> bytes:
    if not 0 <= value <= RANS_TOTAL_FREQUENCY:
        raise AssertionError("UGRICE1 internal rANS frequency is outside its domain")
    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        output.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(output)


def _decode_uleb128(payload: bytes, position: int) -> tuple[int, int]:
    start = position
    value = 0
    shift = 0
    for _index in range(2):
        if position >= len(payload):
            raise ChronoEntropyError("UGRICE1 rANS frequency table is truncated")
        byte = payload[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            if _encode_uleb128(value) != payload[start:position]:
                raise ChronoEntropyError("UGRICE1 rANS frequency varint is noncanonical")
            if not 1 <= value < RANS_TOTAL_FREQUENCY:
                raise ChronoEntropyError("UGRICE1 rANS frequency is outside its domain")
            return value, position
        shift += 7
    raise ChronoEntropyError("UGRICE1 rANS frequency varint is too long")


def _normalize_rans_frequencies(source: bytes) -> tuple[tuple[int, ...], tuple[int, ...]]:
    if not source:
        raise ChronoEntropyError("a UGRICE1 rANS block cannot be empty")
    if _np is not None:
        counts_array = _np.bincount(_np.frombuffer(source, dtype=_np.uint8), minlength=256)
        counts = tuple(int(value) for value in counts_array)
    else:  # pragma: no cover - minimal installation fallback.
        counter = Counter(source)
        counts = tuple(counter.get(symbol, 0) for symbol in range(256))
    used = tuple(symbol for symbol, count in enumerate(counts) if count)
    remaining = RANS_TOTAL_FREQUENCY - len(used)
    frequencies = [0] * 256
    remainders = []
    allocated = 0
    size = len(source)
    for symbol in used:
        numerator = counts[symbol] * remaining
        extra = numerator // size
        frequencies[symbol] = 1 + extra
        allocated += extra
        remainders.append((numerator % size, symbol))
    leftovers = remaining - allocated
    # Largest-remainder allocation with a stable low-symbol tie break.
    remainders.sort(key=lambda item: (-item[0], item[1]))
    for _remainder, symbol in remainders[:leftovers]:
        frequencies[symbol] += 1
    if sum(frequencies) != RANS_TOTAL_FREQUENCY:
        raise AssertionError("UGRICE1 internal rANS normalization failed")
    starts = [0] * 256
    cumulative = 0
    for symbol, frequency in enumerate(frequencies):
        starts[symbol] = cumulative
        cumulative += frequency
    return tuple(frequencies), tuple(starts)


def _serialize_rans_table(frequencies: tuple[int, ...]) -> bytes:
    used = tuple(symbol for symbol, frequency in enumerate(frequencies) if frequency)
    if not used:
        raise AssertionError("UGRICE1 internal rANS table is empty")
    presence = bytearray(32)
    for symbol in used:
        presence[symbol >> 3] |= 1 << (symbol & 7)
    result = bytearray(presence)
    # The final present symbol is implied by the fixed total.
    for symbol in used[:-1]:
        result.extend(_encode_uleb128(frequencies[symbol]))
    return bytes(result)


def _parse_rans_table(
    payload: bytes,
) -> tuple[tuple[int, ...], tuple[int, ...], int]:
    if len(payload) < 36:
        raise ChronoEntropyError("UGRICE1 rANS block is truncated before its table/state")
    presence = payload[:32]
    used = tuple(
        symbol
        for symbol in range(256)
        if presence[symbol >> 3] & (1 << (symbol & 7))
    )
    if not used:
        raise ChronoEntropyError("UGRICE1 rANS symbol table is empty")
    frequencies = [0] * 256
    position = 32
    cumulative = 0
    for symbol in used[:-1]:
        frequency, position = _decode_uleb128(payload, position)
        frequencies[symbol] = frequency
        cumulative += frequency
        if cumulative >= RANS_TOTAL_FREQUENCY:
            raise ChronoEntropyError("UGRICE1 rANS frequencies exceed their fixed total")
    final_frequency = RANS_TOTAL_FREQUENCY - cumulative
    if not 1 <= final_frequency <= RANS_TOTAL_FREQUENCY:
        raise ChronoEntropyError("UGRICE1 rANS final frequency is invalid")
    frequencies[used[-1]] = final_frequency
    starts = [0] * 256
    cumulative = 0
    for symbol, frequency in enumerate(frequencies):
        starts[symbol] = cumulative
        cumulative += frequency
    return tuple(frequencies), tuple(starts), position


def _encode_rans(source: bytes) -> bytes:
    frequencies, starts = _normalize_rans_frequencies(source)
    table = _serialize_rans_table(frequencies)
    if _njit is not None and _np is not None and len(source) >= 1024:
        source_array = _np.frombuffer(source, dtype=_np.uint8)
        frequency_array = _np.asarray(frequencies, dtype=_np.int64)
        start_array = _np.asarray(starts, dtype=_np.int64)
        state, reverse_output = _encode_rans_numba(
            source_array, frequency_array, start_array
        )
        renormalized = reverse_output[::-1].tobytes()
    else:
        state = RANS_BYTE_L
        reverse_output = bytearray()
        for symbol in reversed(source):
            frequency = frequencies[symbol]
            maximum = ((RANS_BYTE_L >> RANS_SCALE_BITS) << 8) * frequency
            while state >= maximum:
                reverse_output.append(state & 0xFF)
                state >>= 8
            state = (
                (state // frequency) << RANS_SCALE_BITS
            ) + (state % frequency) + starts[symbol]
        renormalized = bytes(reversed(reverse_output))
    if not RANS_BYTE_L <= int(state) <= 0xFFFFFFFF:
        raise AssertionError("UGRICE1 internal rANS final state is invalid")
    return table + struct.pack("<I", int(state)) + renormalized


def _decode_rans(payload: bytes, symbols: int) -> bytes:
    frequencies, starts, position = _parse_rans_table(payload)
    if position + 4 > len(payload):
        raise ChronoEntropyError("UGRICE1 rANS block is truncated before its state")
    state = struct.unpack_from("<I", payload, position)[0]
    position += 4
    if state < RANS_BYTE_L:
        raise ChronoEntropyError("UGRICE1 rANS initial state is below its lower bound")
    encoded = payload[position:]
    lookup = [-1] * RANS_TOTAL_FREQUENCY
    for symbol, frequency in enumerate(frequencies):
        start = starts[symbol]
        for slot in range(start, start + frequency):
            lookup[slot] = symbol
    if _njit is not None and _np is not None and symbols >= 1024:
        output, consumed, final_state, status = _decode_rans_numba(
            _np.frombuffer(encoded, dtype=_np.uint8),
            state,
            _np.asarray(frequencies, dtype=_np.int64),
            _np.asarray(starts, dtype=_np.int64),
            _np.asarray(lookup, dtype=_np.int16),
            symbols,
        )
        if status == 1:
            raise ChronoEntropyError("UGRICE1 rANS state selected an empty slot")
        if status == 2:
            raise ChronoEntropyError("UGRICE1 rANS renormalization bytes are truncated")
        result = output.tobytes()
    else:
        output = bytearray(symbols)
        consumed = 0
        for index in range(symbols):
            slot = state & (RANS_TOTAL_FREQUENCY - 1)
            symbol = lookup[slot]
            if symbol < 0:
                raise ChronoEntropyError("UGRICE1 rANS state selected an empty slot")
            output[index] = symbol
            state = frequencies[symbol] * (state >> RANS_SCALE_BITS) + (
                slot - starts[symbol]
            )
            while state < RANS_BYTE_L:
                if consumed >= len(encoded):
                    raise ChronoEntropyError(
                        "UGRICE1 rANS renormalization bytes are truncated"
                    )
                state = (state << 8) | encoded[consumed]
                consumed += 1
        final_state = state
        result = bytes(output)
    if int(consumed) != len(encoded):
        raise ChronoEntropyError("UGRICE1 rANS block has trailing renormalization bytes")
    if int(final_state) != RANS_BYTE_L:
        raise ChronoEntropyError("UGRICE1 rANS terminal state is noncanonical")
    return result


@dataclass(frozen=True)
class AdaptiveRiceStats:
    """Measured properties of one canonical UGRICE1 stream."""

    logical_bytes: int
    encoded_bytes: int
    payload_bytes: int
    block_bytes: int
    block_count: int
    rice_blocks: int
    rans_blocks: int
    raw_blocks: int
    rice_k_counts: tuple[tuple[int, int], ...]

    @property
    def ratio_to_logical(self) -> float:
        return self.encoded_bytes / self.logical_bytes if self.logical_bytes else math.inf


def _encode_payload(source: bytes, block_bytes: int) -> tuple[bytes, AdaptiveRiceStats]:
    payload = bytearray()
    rice_blocks = 0
    rans_blocks = 0
    raw_blocks = 0
    k_counts: Counter[int] = Counter()
    for start in range(0, len(source), block_bytes):
        block = source[start : start + block_bytes]
        mapped = _mapped_bytes(block)
        k, rice_bits = _best_rice_parameter(mapped)
        rice_coded = _encode_rice_bits(mapped, k, rice_bits)
        rans_coded = _encode_rans(block)
        # File size is authoritative.  Method number is the deterministic tie
        # break: RAW, then Rice, then rANS.
        method, coded = min(
            (
                (BLOCK_RAW, block),
                (BLOCK_RICE, rice_coded),
                (BLOCK_RANS, rans_coded),
            ),
            key=lambda item: (len(item[1]), item[0]),
        )
        if method == BLOCK_RICE:
            payload.extend(_BLOCK_HEADER.pack(BLOCK_RICE, k, 0, rice_bits))
            payload.extend(coded)
            rice_blocks += 1
            k_counts[k] += 1
        elif method == BLOCK_RANS:
            payload.extend(_BLOCK_HEADER.pack(BLOCK_RANS, 0, 0, len(coded) * 8))
            payload.extend(coded)
            rans_blocks += 1
        else:
            payload.extend(_BLOCK_HEADER.pack(BLOCK_RAW, 0, 0, len(block) * 8))
            payload.extend(block)
            raw_blocks += 1
    block_count = (len(source) + block_bytes - 1) // block_bytes
    stats = AdaptiveRiceStats(
        logical_bytes=len(source),
        encoded_bytes=0,
        payload_bytes=len(payload),
        block_bytes=block_bytes,
        block_count=block_count,
        rice_blocks=rice_blocks,
        rans_blocks=rans_blocks,
        raw_blocks=raw_blocks,
        rice_k_counts=tuple(sorted(k_counts.items())),
    )
    return bytes(payload), stats


def encode_adaptive_rice(
    data: bytes | bytearray | memoryview,
    *,
    block_bytes: int = DEFAULT_BLOCK_BYTES,
) -> bytes:
    """Encode arbitrary bytes as one canonical, independently decodable stream."""
    source = bytes(data)
    block_bytes = _validate_block_bytes(block_bytes)
    if len(source) > MAX_LOGICAL_BYTES:
        raise ChronoEntropyError("UGRICE1 logical byte count exceeds its safety limit")
    payload, stats = _encode_payload(source, block_bytes)
    flags = UGRICE_FLAG_SIGNED_MOD256_ZIGZAG
    decoded_digest = _sha256(source)
    payload_digest = _sha256(payload)
    unsigned_header = _STREAM_HEADER.pack(
        UGRICE_MAGIC,
        UGRICE_MAJOR,
        UGRICE_MINOR,
        UGRICE_HEADER_BYTES,
        flags,
        len(source),
        block_bytes,
        stats.block_count,
        len(payload),
        decoded_digest,
        payload_digest,
        bytes(32),
        bytes(20),
    )
    content_digest = _sha256(unsigned_header + payload)
    return _STREAM_HEADER.pack(
        UGRICE_MAGIC,
        UGRICE_MAJOR,
        UGRICE_MINOR,
        UGRICE_HEADER_BYTES,
        flags,
        len(source),
        block_bytes,
        stats.block_count,
        len(payload),
        decoded_digest,
        payload_digest,
        content_digest,
        bytes(20),
    ) + payload


def _parse_header(raw: bytes) -> tuple[int, int, int, bytes, bytes, bytes]:
    if len(raw) < UGRICE_HEADER_BYTES:
        raise ChronoEntropyError("UGRICE1 is truncated before its header")
    if _STREAM_HEADER.size != UGRICE_HEADER_BYTES:
        raise AssertionError("UGRICE1 header declaration does not match its struct")
    (
        magic,
        major,
        minor,
        header_bytes,
        flags,
        logical_bytes,
        block_bytes,
        block_count,
        payload_bytes,
        decoded_digest,
        payload_digest,
        content_digest,
        reserved,
    ) = _STREAM_HEADER.unpack_from(raw)
    if magic != UGRICE_MAGIC:
        raise ChronoEntropyError("UGRICE1 magic mismatch")
    if (major, minor) != (UGRICE_MAJOR, UGRICE_MINOR):
        raise ChronoEntropyError(f"unsupported UGRICE1 version {major}.{minor}")
    if header_bytes != UGRICE_HEADER_BYTES:
        raise ChronoEntropyError("UGRICE1 header byte count mismatch")
    if flags != UGRICE_FLAG_SIGNED_MOD256_ZIGZAG:
        raise ChronoEntropyError("UGRICE1 flags are unsupported or noncanonical")
    if reserved != bytes(20):
        raise ChronoEntropyError("UGRICE1 reserved header bytes are nonzero")
    _validate_block_bytes(block_bytes)
    if logical_bytes > MAX_LOGICAL_BYTES:
        raise ChronoEntropyError("UGRICE1 logical byte count exceeds its safety limit")
    expected_blocks = (logical_bytes + block_bytes - 1) // block_bytes
    if block_count != expected_blocks:
        raise ChronoEntropyError("UGRICE1 block count does not match the logical length")
    maximum_payload = logical_bytes + block_count * _BLOCK_HEADER.size
    if payload_bytes > maximum_payload:
        raise ChronoEntropyError("UGRICE1 payload exceeds the raw-fallback bound")
    if len(raw) != header_bytes + payload_bytes:
        raise ChronoEntropyError("UGRICE1 payload length mismatch")
    payload = raw[header_bytes:]
    if _sha256(payload) != payload_digest:
        raise ChronoEntropyError("UGRICE1 payload SHA-256 mismatch")
    unsigned = bytearray(raw)
    unsigned[_CONTENT_DIGEST_OFFSET : _CONTENT_DIGEST_OFFSET + 32] = bytes(32)
    if _sha256(bytes(unsigned)) != content_digest:
        raise ChronoEntropyError("UGRICE1 content SHA-256 mismatch")
    return logical_bytes, block_bytes, block_count, decoded_digest, payload, content_digest


def decode_adaptive_rice(
    data: bytes | bytearray | memoryview,
    *,
    require_canonical: bool = True,
) -> bytes:
    """Strictly parse and reconstruct a UGRICE1 stream."""
    raw = bytes(data)
    logical_bytes, block_bytes, block_count, decoded_digest, payload, _digest = (
        _parse_header(raw)
    )
    output = bytearray()
    position = 0
    for block_index in range(block_count):
        if position + _BLOCK_HEADER.size > len(payload):
            raise ChronoEntropyError("UGRICE1 is truncated before a block header")
        method, k, reserved, encoded_bits = _BLOCK_HEADER.unpack_from(payload, position)
        position += _BLOCK_HEADER.size
        if reserved:
            raise ChronoEntropyError("UGRICE1 block reserved field is nonzero")
        remaining = logical_bytes - len(output)
        symbols = min(block_bytes, remaining)
        if symbols <= 0:
            raise ChronoEntropyError("UGRICE1 contains an excess block")
        if method == BLOCK_RAW:
            if k or encoded_bits != symbols * 8:
                raise ChronoEntropyError("UGRICE1 RAW block metadata is noncanonical")
            coded_bytes = symbols
        elif method == BLOCK_RICE:
            if k > 7:
                raise ChronoEntropyError("UGRICE1 Rice parameter is outside [0, 7]")
            if not 0 < encoded_bits < symbols * 8:
                raise ChronoEntropyError("UGRICE1 Rice block cannot beat RAW storage")
            coded_bytes = (encoded_bits + 7) // 8
        elif method == BLOCK_RANS:
            if k or encoded_bits & 7:
                raise ChronoEntropyError("UGRICE1 rANS block metadata is noncanonical")
            if not 0 < encoded_bits < symbols * 8:
                raise ChronoEntropyError("UGRICE1 rANS block cannot beat RAW storage")
            coded_bytes = encoded_bits // 8
        else:
            raise ChronoEntropyError("UGRICE1 block method is unsupported")
        end = position + coded_bytes
        if end > len(payload):
            raise ChronoEntropyError("UGRICE1 block payload is truncated")
        block_payload = payload[position:end]
        position = end
        if method == BLOCK_RICE and encoded_bits & 7:
            unused = 8 - (encoded_bits & 7)
            if block_payload[-1] & ((1 << unused) - 1):
                raise ChronoEntropyError("UGRICE1 Rice padding bits must be zero")
        if method == BLOCK_RAW:
            output.extend(block_payload)
        elif method == BLOCK_RICE:
            output.extend(_decode_rice_bits(block_payload, encoded_bits, k, symbols))
        else:
            output.extend(_decode_rans(block_payload, symbols))
    if position != len(payload):
        raise ChronoEntropyError("UGRICE1 payload has trailing bytes")
    result = bytes(output)
    if len(result) != logical_bytes:
        raise ChronoEntropyError("UGRICE1 decoded byte count mismatch")
    if _sha256(result) != decoded_digest:
        raise ChronoEntropyError("UGRICE1 decoded SHA-256 mismatch")
    if require_canonical and encode_adaptive_rice(result, block_bytes=block_bytes) != raw:
        raise ChronoEntropyError("UGRICE1 stream is not in canonical form")
    return result


def inspect_adaptive_rice(data: bytes | bytearray | memoryview) -> AdaptiveRiceStats:
    """Verify one stream and return exact size/method statistics."""
    raw = bytes(data)
    decoded = decode_adaptive_rice(raw)
    _logical, block_bytes, block_count, _decoded_sha, payload, _digest = _parse_header(raw)
    rice_blocks = 0
    rans_blocks = 0
    raw_blocks = 0
    k_counts: Counter[int] = Counter()
    position = 0
    remaining = len(decoded)
    for _block_index in range(block_count):
        method, k, _reserved, bits = _BLOCK_HEADER.unpack_from(payload, position)
        position += _BLOCK_HEADER.size
        symbols = min(block_bytes, remaining)
        position += symbols if method == BLOCK_RAW else (bits + 7) // 8
        remaining -= symbols
        if method == BLOCK_RAW:
            raw_blocks += 1
        elif method == BLOCK_RICE:
            rice_blocks += 1
            k_counts[k] += 1
        else:
            rans_blocks += 1
    return AdaptiveRiceStats(
        logical_bytes=len(decoded),
        encoded_bytes=len(raw),
        payload_bytes=len(payload),
        block_bytes=block_bytes,
        block_count=block_count,
        rice_blocks=rice_blocks,
        rans_blocks=rans_blocks,
        raw_blocks=raw_blocks,
        rice_k_counts=tuple(sorted(k_counts.items())),
    )


def optimize_adaptive_rice(
    data: bytes | bytearray | memoryview,
    *,
    block_sizes: Iterable[int] = (1 << 10, 1 << 12, 1 << 14, 1 << 16),
) -> tuple[bytes, AdaptiveRiceStats]:
    """Choose the byte-smallest stream from explicitly bounded block sizes."""
    source = bytes(data)
    sizes = tuple(dict.fromkeys(_validate_block_bytes(value) for value in block_sizes))
    if not sizes:
        raise ChronoEntropyError("UGRICE1 optimization requires at least one block size")
    candidates = []
    for block_bytes in sizes:
        encoded = encode_adaptive_rice(source, block_bytes=block_bytes)
        candidates.append((len(encoded), block_bytes, encoded))
    _length, _block_bytes, result = min(candidates, key=lambda item: (item[0], item[1]))
    return result, inspect_adaptive_rice(result)


__all__ = [
    "AdaptiveRiceStats",
    "BLOCK_RANS",
    "BLOCK_RAW",
    "BLOCK_RICE",
    "ChronoEntropyError",
    "DEFAULT_BLOCK_BYTES",
    "UGRICE_HEADER_BYTES",
    "UGRICE_MAGIC",
    "decode_adaptive_rice",
    "encode_adaptive_rice",
    "inspect_adaptive_rice",
    "optimize_adaptive_rice",
]
