from __future__ import annotations

import hashlib
import random
import struct

import pytest

import ugts_kc3.chrono_entropy as entropy
from ugts_kc3.chrono_entropy import (
    BLOCK_RANS,
    BLOCK_RICE,
    ChronoEntropyError,
    UGRICE_HEADER_BYTES,
    UGRICE_MAGIC,
    decode_adaptive_rice,
    encode_adaptive_rice,
    inspect_adaptive_rice,
    optimize_adaptive_rice,
)


def _random_bytes(size: int) -> bytes:
    generator = random.Random(7727)
    return generator.randbytes(size)


def _resign(raw: bytearray) -> bytes:
    """Recompute integrity lanes so tests reach semantic validation."""
    payload = bytes(raw[UGRICE_HEADER_BYTES:])
    struct.pack_into("<Q", raw, 36, len(payload))
    raw[76:108] = hashlib.sha256(payload).digest()
    raw[108:140] = bytes(32)
    raw[108:140] = hashlib.sha256(bytes(raw)).digest()
    return bytes(raw)


@pytest.mark.parametrize(
    "source",
    [
        b"",
        b"\x00",
        bytes(255),
        bytes(256),
        bytes(257),
        bytes(range(256)) * 3,
        b"\xff\x00\x01\xfe" * 500,
        pytest.param(_random_bytes(20_000), id="seeded-random-20000"),
    ],
)
def test_round_trip_is_exact_and_deterministic(source: bytes) -> None:
    first = encode_adaptive_rice(source, block_bytes=256)
    second = encode_adaptive_rice(source, block_bytes=256)

    assert first == second
    assert first[:8] == UGRICE_MAGIC
    assert decode_adaptive_rice(first) == source


def test_known_zero_rice_code_is_msb_first() -> None:
    encoded = encode_adaptive_rice(bytes(8), block_bytes=256)
    method, k, reserved, bits = struct.unpack_from("<BBHI", encoded, UGRICE_HEADER_BYTES)

    assert (method, k, reserved, bits) == (BLOCK_RICE, 0, 0, 8)
    assert encoded[UGRICE_HEADER_BYTES + 8 :] == b"\xff"


def test_signed_modulo_mapping_makes_minus_one_small() -> None:
    encoded = encode_adaptive_rice(b"\xff" * 8, block_bytes=256)
    method, k, reserved, bits = struct.unpack_from("<BBHI", encoded, UGRICE_HEADER_BYTES)

    assert (method, k, reserved, bits) == (BLOCK_RICE, 0, 0, 16)
    assert encoded[UGRICE_HEADER_BYTES + 8 :] == b"UU"
    assert decode_adaptive_rice(encoded) == b"\xff" * 8


def test_incompressible_blocks_fall_back_to_raw() -> None:
    source = bytes(range(256)) * 4
    encoded = encode_adaptive_rice(source, block_bytes=256)
    stats = inspect_adaptive_rice(encoded)

    assert stats.raw_blocks == 4
    assert stats.rice_blocks == 0
    assert stats.payload_bytes == len(source) + 4 * 8
    assert decode_adaptive_rice(encoded) == source


def test_blocks_adapt_independently() -> None:
    source = bytes(256) + bytes(range(256))
    stats = inspect_adaptive_rice(encode_adaptive_rice(source, block_bytes=256))

    assert stats.block_count == 2
    assert stats.rice_blocks == 1
    assert stats.raw_blocks == 1
    assert stats.rice_k_counts == ((0, 1),)


def test_codec_native_rans_is_exact_and_selected_for_skewed_bytes() -> None:
    generator = random.Random(991)
    source = bytes(generator.randrange(16) for _ in range(20_000))
    encoded = encode_adaptive_rice(source, block_bytes=4096)
    stats = inspect_adaptive_rice(encoded)

    assert stats.rans_blocks == stats.block_count
    assert stats.rice_blocks == 0
    assert stats.raw_blocks == 0
    assert len(encoded) < len(source)
    assert decode_adaptive_rice(encoded) == source


def test_accelerated_and_reference_paths_are_binary_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if entropy._njit is None:
        pytest.skip("Numba is not installed")
    generator = random.Random(8841)
    source = bytes(generator.randrange(32) for _ in range(4096))
    accelerated = encode_adaptive_rice(source, block_bytes=4096)

    monkeypatch.setattr(entropy, "_njit", None)
    reference = encode_adaptive_rice(source, block_bytes=4096)

    assert reference == accelerated
    assert decode_adaptive_rice(reference) == source


def test_single_symbol_rans_has_no_renormalization_bytes() -> None:
    encoded = encode_adaptive_rice(bytes(512), block_bytes=512)
    method, parameter, reserved, bits = struct.unpack_from(
        "<BBHI", encoded, UGRICE_HEADER_BYTES
    )

    assert (method, parameter, reserved) == (BLOCK_RANS, 0, 0)
    assert bits == 36 * 8  # 32-byte presence map + uint32 state.
    assert decode_adaptive_rice(encoded) == bytes(512)


def test_rans_empty_symbol_table_is_rejected_after_valid_resigning() -> None:
    raw = bytearray(encode_adaptive_rice(bytes(512), block_bytes=512))
    table_offset = UGRICE_HEADER_BYTES + 8
    raw[table_offset : table_offset + 32] = bytes(32)

    with pytest.raises(ChronoEntropyError, match="symbol table is empty"):
        decode_adaptive_rice(_resign(raw), require_canonical=False)


def test_rans_state_below_lower_bound_is_rejected() -> None:
    raw = bytearray(encode_adaptive_rice(bytes(512), block_bytes=512))
    state_offset = UGRICE_HEADER_BYTES + 8 + 32
    raw[state_offset : state_offset + 4] = bytes(4)

    with pytest.raises(ChronoEntropyError, match="below its lower bound"):
        decode_adaptive_rice(_resign(raw), require_canonical=False)


def test_rans_trailing_renormalization_byte_is_rejected() -> None:
    raw = bytearray(encode_adaptive_rice(bytes(512), block_bytes=512))
    bits_offset = UGRICE_HEADER_BYTES + 4
    bits = struct.unpack_from("<I", raw, bits_offset)[0]
    struct.pack_into("<I", raw, bits_offset, bits + 8)
    raw.append(0)

    with pytest.raises(ChronoEntropyError, match="trailing renormalization"):
        decode_adaptive_rice(_resign(raw), require_canonical=False)


def test_optimizer_returns_smallest_then_lowest_block_size() -> None:
    source = bytes(10_000) + bytes(range(256)) * 20
    sizes = (256, 1024, 4096)
    candidates = {
        size: encode_adaptive_rice(source, block_bytes=size) for size in sizes
    }
    encoded, stats = optimize_adaptive_rice(source, block_sizes=reversed(sizes))
    expected_size, expected_block = min(
        (len(value), size) for size, value in candidates.items()
    )

    assert len(encoded) == expected_size
    assert stats.block_bytes == expected_block
    assert decode_adaptive_rice(encoded) == source


@pytest.mark.parametrize("block_bytes", [0, 255, 257, 1 << 21, True])
def test_invalid_block_sizes_are_rejected(block_bytes: int) -> None:
    with pytest.raises(ChronoEntropyError):
        encode_adaptive_rice(b"abc", block_bytes=block_bytes)


def test_truncation_and_trailing_data_are_rejected() -> None:
    encoded = encode_adaptive_rice(bytes(500), block_bytes=256)

    with pytest.raises(ChronoEntropyError, match="payload length"):
        decode_adaptive_rice(encoded[:-1])
    with pytest.raises(ChronoEntropyError, match="payload length"):
        decode_adaptive_rice(encoded + b"\x00")


@pytest.mark.parametrize(
    ("offset", "value", "message"),
    [
        (0, 0, "magic"),
        (8, 2, "version"),
        (12, 0, "header byte count"),
        (16, 0, "flags"),
        (140, 1, "reserved"),
    ],
)
def test_header_semantic_tampering_is_rejected(
    offset: int, value: int, message: str
) -> None:
    raw = bytearray(encode_adaptive_rice(bytes(500), block_bytes=256))
    raw[offset] = value

    with pytest.raises(ChronoEntropyError, match=message):
        decode_adaptive_rice(raw)


def test_payload_and_content_digest_tampering_are_rejected() -> None:
    raw = bytearray(encode_adaptive_rice(bytes(500), block_bytes=256))
    raw[-1] ^= 1
    with pytest.raises(ChronoEntropyError, match="payload SHA-256"):
        decode_adaptive_rice(raw)

    raw = bytearray(encode_adaptive_rice(bytes(500), block_bytes=256))
    raw[108] ^= 1
    with pytest.raises(ChronoEntropyError, match="content SHA-256"):
        decode_adaptive_rice(raw)


@pytest.mark.parametrize(
    ("byte_offset", "replacement", "message"),
    [
        (0, 3, "method"),
        (1, 8, "parameter"),
        (2, 1, "reserved"),
    ],
)
def test_invalid_block_header_is_rejected_after_valid_resigning(
    byte_offset: int, replacement: int, message: str
) -> None:
    raw = bytearray(encode_adaptive_rice(bytes(512), block_bytes=256))
    raw[UGRICE_HEADER_BYTES + byte_offset] = replacement
    resigned = _resign(raw)

    with pytest.raises(ChronoEntropyError, match=message):
        decode_adaptive_rice(resigned)


def test_nonzero_padding_is_rejected_after_valid_resigning() -> None:
    raw = bytearray(encode_adaptive_rice(bytes(257), block_bytes=512))
    method, _k, _reserved, bits = struct.unpack_from(
        "<BBHI", raw, UGRICE_HEADER_BYTES
    )
    assert method == BLOCK_RICE and bits == 257
    raw[-1] |= 1

    with pytest.raises(ChronoEntropyError, match="padding bits"):
        decode_adaptive_rice(_resign(raw))


def test_alternate_valid_rice_parameter_is_rejected_as_noncanonical() -> None:
    source = bytes(512)
    canonical = encode_adaptive_rice(source, block_bytes=512)
    mapped = bytes(512)
    alternate_bits = 512 * 2
    alternate_coded = entropy._encode_rice_bits(mapped, 1, alternate_bits)
    alternate_payload = (
        struct.pack("<BBHI", BLOCK_RICE, 1, 0, alternate_bits) + alternate_coded
    )
    raw = bytearray(canonical[:UGRICE_HEADER_BYTES] + alternate_payload)
    alternate = _resign(raw)

    assert decode_adaptive_rice(alternate, require_canonical=False) == source
    with pytest.raises(ChronoEntropyError, match="not in canonical form"):
        decode_adaptive_rice(alternate)


def test_rice_codeword_overflow_is_rejected() -> None:
    source = bytes(256)
    canonical = encode_adaptive_rice(source, block_bytes=256)
    # q=256 is outside the byte alphabet at k=0, followed by enough one-bit
    # zero codewords that this remains within the declared sub-RAW bit bound.
    bits = 512
    coded = bytearray((bits + 7) // 8)
    coded[256 >> 3] |= 1 << (7 - (256 & 7))
    for bit_position in range(257, 512):
        coded[bit_position >> 3] |= 1 << (7 - (bit_position & 7))
    payload = struct.pack("<BBHI", BLOCK_RICE, 0, 0, bits) + coded
    raw = bytearray(canonical[:UGRICE_HEADER_BYTES] + payload)

    with pytest.raises(ChronoEntropyError, match="byte alphabet"):
        decode_adaptive_rice(_resign(raw), require_canonical=False)
