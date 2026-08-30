from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import struct

import pytest

from ugts_kc3.chrono_substrate import (
    create_substrate_traversal_recipe,
    derive_substrate_traversal,
)
from ugts_kc3.cli import main as cli_main
from ugts_kc3.gsp4_camera_codeword import codeword_lineage, gsp4_mix32
from ugts_kc3.ugyuvs1 import Ugyuvs1Capture, Ugyuvs1Error, verify_ugsp4c


FILE_HEADER_BYTES = 512
STATIC_HEADER_BYTES = 256
COMMIT_SLOT_BYTES = 128
FRAME_HEADER_BYTES = 384
BLOCK_HEADER_BYTES = 192
TERMINAL_HEADER_BYTES = 192
STATIC_DIGEST_OFFSET = 208
COMMIT_DIGEST_OFFSET = 80
FRAME_CONTENT_DIGEST_OFFSET = 304
BLOCK_CONTENT_DIGEST_OFFSET = 104
TERMINAL_CONTENT_DIGEST_OFFSET = 144
INT64_MIN = -(1 << 63)

LINEAGE_DOMAIN = b"UGYUVS1-GSP4-codeword-lineage-v1\0"
RECIPE_DOMAIN = b"UGYUVS1-UGCODE24-420-seed-recipe-v1\0"
STATE_DOMAIN = b"UGYUVS1-executable-seed-state-v1\0"
OPERATOR_MEANING = (
    b"UGCODE24-420-v1:luma-address-codeword=[Y(x,y),U(floor(x/2),floor(y/2)),"
    b"V(floor(x/2),floor(y/2))];storage=UGTRV1-luma-order;"
    b"chroma-owner=even-x-even-y-once;novelty=mod256-mask-nonzero-values\0"
)


@dataclass(frozen=True)
class FixtureFrame:
    sensor_pts: int
    frame_number: int
    y: bytes
    u: bytes
    v: bytes
    metadata: bytes


@dataclass(frozen=True)
class BuiltFixture:
    data: bytes
    frames: tuple[FixtureFrame, ...]
    record_offset: int
    frame_offsets: tuple[int, ...]
    terminal_offset: int


def _sha(data: bytes | bytearray) -> bytes:
    return hashlib.sha256(data).digest()


def _put_u16(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<H", data, offset, value)


def _put_u32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", data, offset, value)


def _put_u64(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<Q", data, offset, value)


def _put_i64(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<q", data, offset, value)


def _put_digest(data: bytearray, offset: int, digest: bytes) -> None:
    assert len(digest) == 32
    data[offset : offset + 32] = digest


def _hash_zero(data: bytes | bytearray, offset: int) -> bytes:
    copy = bytearray(data)
    copy[offset : offset + 32] = bytes(32)
    return _sha(copy)


def _uleb(value: int) -> bytes:
    result = bytearray()
    while True:
        lane = value & 0x7F
        value >>= 7
        result.append(lane | (0x80 if value else 0))
        if not value:
            return bytes(result)


def _select_representation(
    logical: bytes,
    *,
    forced: int | None = None,
) -> tuple[int, bytes, bytes]:
    mask = bytearray((len(logical) + 7) // 8)
    values = bytearray()
    gaps = bytearray()
    next_ordinal = 0
    for index, value in enumerate(logical):
        if value:
            mask[index >> 3] |= 1 << (index & 7)
            values.append(value)
            gaps.extend(_uleb(index - next_ordinal))
            next_ordinal = index + 1
    candidates: dict[int, tuple[bytes, bytes]] = {
        0: (b"", b""),
        1: (b"", logical),
        2: (bytes(mask), bytes(values)),
        3: (bytes(gaps), bytes(values)),
    }
    if forced is not None:
        return forced, *candidates[forced]
    if not values:
        return 0, b"", b""
    selected = 1
    selected_bytes = len(logical)
    for representation in (2, 3):
        auxiliary, stored = candidates[representation]
        if len(auxiliary) + len(stored) < selected_bytes:
            selected = representation
            selected_bytes = len(auxiliary) + len(stored)
    return selected, *candidates[selected]


def _commit(
    generation: int,
    *,
    finalized: bool,
    frame_count: int,
    committed_end: int,
    last_pts: int,
    terminal: bytes,
) -> bytes:
    slot = bytearray(COMMIT_SLOT_BYTES)
    slot[:8] = b"UGCMIT1\0"
    _put_u64(slot, 8, generation)
    _put_u32(slot, 16, int(finalized))
    _put_u64(slot, 24, frame_count)
    _put_u64(slot, 32, committed_end)
    _put_i64(slot, 40, last_pts)
    _put_digest(slot, 48, terminal)
    _put_digest(slot, COMMIT_DIGEST_OFFSET, _hash_zero(slot, COMMIT_DIGEST_OFFSET))
    return bytes(slot)


def _fixture_frames(width: int, height: int) -> tuple[FixtureFrame, ...]:
    y = bytes((index * 29 + 17) & 255 or 1 for index in range(width * height))
    c_bytes = width * height // 4
    u = bytes((index * 31 + 53) & 255 or 2 for index in range(c_bytes))
    v = bytes((index * 67 + 101) & 255 or 3 for index in range(c_bytes))
    frame0 = FixtureFrame(1_000_000_000, 700, y, u, v, b"\x01\x00camera")
    frame1 = FixtureFrame(
        frame0.sensor_pts + 33_333_333,
        701,
        frame0.y,
        frame0.u,
        frame0.v,
        b"\x01\x00same",
    )
    y2 = bytearray(frame1.y)
    y2[0] = (y2[0] + 7) & 255
    frame2 = FixtureFrame(
        frame1.sensor_pts + 33_333_333,
        702,
        bytes(y2),
        frame1.u,
        frame1.v,
        b"\x01\x00sparse",
    )
    y3 = bytearray(frame2.y)
    for index in range(0, len(y3), 4):
        y3[index] = (y3[index] + 1) & 255
    frame3 = FixtureFrame(
        frame2.sensor_pts + 33_333_333,
        703,
        bytes(y3),
        frame2.u,
        frame2.v,
        b"\x01\x00mask",
    )
    return frame0, frame1, frame2, frame3


def _build_fixture(*, force_frame2_representation: int | None = None) -> BuiltFixture:
    width = 8
    height = 6
    checkpoint_interval = 10
    block_luma = width * height
    lut_path = (
        Path(__file__).parents[1]
        / "native"
        / "host_tests"
        / "fixtures"
        / "uglut2_native_fixture.bin"
    )
    lut = lut_path.read_bytes()
    root_seed = int.from_bytes(
        _sha(b"UGYUVS1 independent Python fixture authority v1")[:8], "little"
    )
    recipe_seed = 1
    recipe = create_substrate_traversal_recipe(
        width,
        height,
        lut,
        root_seed=root_seed,
        recipe_seed=recipe_seed,
    )
    traversal = tuple(
        int(value) for value in derive_substrate_traversal(recipe, lut)
    )
    uglut_sha = _sha(lut)
    traversal_sha = bytes.fromhex(recipe.traversal_sha256)
    recipe_sha = _sha(
        RECIPE_DOMAIN
        + struct.pack("<IIIQQ", width, height, 1, root_seed, recipe_seed)
        + uglut_sha
        + traversal_sha
    )
    record_offset = (FILE_HEADER_BYTES + len(lut) + 63) // 64 * 64
    header = bytearray(FILE_HEADER_BYTES)
    header[:8] = b"UGYUVS1\0"
    _put_u16(header, 8, 1)
    _put_u32(header, 12, FILE_HEADER_BYTES)
    _put_u32(header, 16, 1)
    _put_u32(header, 20, width)
    _put_u32(header, 24, height)
    _put_u32(header, 28, width // 2)
    _put_u32(header, 32, height // 2)
    _put_u32(header, 36, 1)
    _put_u32(header, 40, 8)
    _put_u32(header, 44, checkpoint_interval)
    _put_u32(header, 48, block_luma)
    _put_u32(header, 52, len(lut))
    _put_u64(header, 56, root_seed)
    _put_u64(header, 64, recipe_seed)
    _put_u64(header, 72, record_offset)
    _put_digest(header, 80, uglut_sha)
    _put_digest(header, 112, traversal_sha)
    _put_digest(header, 144, recipe_sha)
    _put_digest(header, 176, _sha(OPERATOR_MEANING))
    static = header[:STATIC_HEADER_BYTES]
    _put_digest(header, STATIC_DIGEST_OFFSET, _hash_zero(static, STATIC_DIGEST_OFFSET))
    static_sha = bytes(header[STATIC_DIGEST_OFFSET : STATIC_DIGEST_OFFSET + 32])

    frames = _fixture_frames(width, height)
    prefix = bytearray(header)
    prefix.extend(lut)
    prefix.extend(bytes(record_offset - len(prefix)))
    frame_offsets: list[int] = []
    chain_sha = bytes(32)
    previous: FixtureFrame | None = None
    for ordinal, frame in enumerate(frames):
        frame_offsets.append(len(prefix))
        checkpoint = ordinal % checkpoint_interval == 0
        base_y = bytes(width * height) if checkpoint else previous.y
        base_u = bytes(width * height // 4) if checkpoint else previous.u
        base_v = bytes(width * height // 4) if checkpoint else previous.v
        residual = bytearray()
        lineage = bytearray(LINEAGE_DOMAIN)
        lineage.extend(struct.pack("<III", ordinal, 0, block_luma))
        for address in traversal:
            row, column = divmod(address, width)
            residual.append((frame.y[address] - base_y[address]) & 255)
            lineage_seed, routed = codeword_lineage(
                root_seed=root_seed,
                recipe_seed=recipe_seed,
                cartesian_address=address,
                frame_ordinal=ordinal,
            )
            assert routed == gsp4_mix32(lineage_seed ^ ordinal)
            lineage.extend(struct.pack("<II", lineage_seed, routed))
            if not (row & 1 or column & 1):
                chroma = (row // 2) * (width // 2) + column // 2
                residual.append((frame.u[chroma] - base_u[chroma]) & 255)
                residual.append((frame.v[chroma] - base_v[chroma]) & 255)
        logical = bytes(residual)
        forced = force_frame2_representation if ordinal == 2 else None
        representation, auxiliary, values = _select_representation(
            logical,
            forced=forced,
        )
        block = bytearray(BLOCK_HEADER_BYTES)
        block[:8] = b"UGNBLK1\0"
        _put_u16(block, 8, 1)
        _put_u32(block, 12, BLOCK_HEADER_BYTES)
        _put_u32(block, 24, block_luma)
        _put_u32(block, 28, len(logical))
        _put_u32(block, 32, len(auxiliary))
        _put_u32(block, 36, len(values))
        _put_digest(block, 40, _sha(logical))
        _put_digest(block, 72, _sha(values))
        _put_u32(block, 136, 4 if checkpoint else 2)
        _put_u32(block, 140, representation)
        _put_digest(block, 144, _sha(lineage))
        block_payload = auxiliary + values
        _put_digest(
            block,
            BLOCK_CONTENT_DIGEST_OFFSET,
            _hash_zero(block + block_payload, BLOCK_CONTENT_DIGEST_OFFSET),
        )
        novelty = bytes(block) + block_payload
        payload = novelty + frame.metadata

        previous_ordinal = 0xFFFFFFFF if checkpoint else ordinal - 1
        state = bytearray(STATE_DOMAIN)
        state.extend(static_sha)
        state.extend(recipe_sha)
        state.extend(
            struct.pack(
                "<IIQq",
                ordinal,
                previous_ordinal,
                frame.sensor_pts,
                frame.frame_number,
            )
        )
        state.extend(_sha(base_y))
        state.extend(_sha(base_u))
        state.extend(_sha(base_v))
        frame_header = bytearray(FRAME_HEADER_BYTES)
        frame_header[:8] = b"UGYFRM1\0"
        _put_u16(frame_header, 8, 1)
        _put_u32(frame_header, 12, FRAME_HEADER_BYTES)
        _put_u32(frame_header, 16, int(checkpoint))
        _put_u32(frame_header, 20, ordinal)
        _put_u32(frame_header, 24, previous_ordinal)
        _put_u32(frame_header, 28, 1)
        _put_i64(frame_header, 32, frame.sensor_pts)
        _put_i64(frame_header, 40, frame.frame_number)
        _put_u64(frame_header, 48, len(payload))
        _put_u64(frame_header, 56, len(novelty))
        _put_u64(frame_header, 64, len(frame.metadata))
        _put_u64(frame_header, 72, len(logical))
        _put_digest(frame_header, 80, _sha(frame.y))
        _put_digest(frame_header, 112, _sha(frame.u))
        _put_digest(frame_header, 144, _sha(frame.v))
        _put_digest(frame_header, 176, _sha(logical))
        _put_digest(frame_header, 208, _sha(frame.metadata))
        _put_digest(frame_header, 240, chain_sha)
        _put_digest(frame_header, 272, _sha(state))
        pre_substrate = _sha(
            struct.pack("<QII", frame.sensor_pts, width, height)
            + frame.y
            + frame.u
            + frame.v
        )
        _put_digest(frame_header, 336, pre_substrate)
        _put_u64(frame_header, 368, len(logical) - logical.count(0))
        _put_digest(
            frame_header,
            FRAME_CONTENT_DIGEST_OFFSET,
            _hash_zero(frame_header + payload, FRAME_CONTENT_DIGEST_OFFSET),
        )
        chain_sha = bytes(
            frame_header[
                FRAME_CONTENT_DIGEST_OFFSET : FRAME_CONTENT_DIGEST_OFFSET + 32
            ]
        )
        prefix.extend(frame_header)
        prefix.extend(payload)
        previous = frame

    pre_terminal_end = len(prefix)
    terminal_offset = len(prefix)
    terminal = bytearray(TERMINAL_HEADER_BYTES)
    terminal[:8] = b"UGYEND1\0"
    _put_u16(terminal, 8, 1)
    _put_u32(terminal, 12, TERMINAL_HEADER_BYTES)
    _put_u64(terminal, 24, len(frames))
    _put_u64(terminal, 32, pre_terminal_end)
    _put_i64(terminal, 40, frames[-1].sensor_pts)
    _put_digest(terminal, 48, chain_sha)
    _put_digest(terminal, 80, static_sha)
    _put_digest(terminal, 112, recipe_sha)
    _put_digest(
        terminal,
        TERMINAL_CONTENT_DIGEST_OFFSET,
        _hash_zero(terminal, TERMINAL_CONTENT_DIGEST_OFFSET),
    )
    terminal_sha = bytes(
        terminal[
            TERMINAL_CONTENT_DIGEST_OFFSET : TERMINAL_CONTENT_DIGEST_OFFSET + 32
        ]
    )
    prefix.extend(terminal)
    prior = _commit(
        5,
        finalized=False,
        frame_count=len(frames),
        committed_end=pre_terminal_end,
        last_pts=frames[-1].sensor_pts,
        terminal=chain_sha,
    )
    final = _commit(
        6,
        finalized=True,
        frame_count=len(frames),
        committed_end=len(prefix),
        last_pts=frames[-1].sensor_pts,
        terminal=terminal_sha,
    )
    prefix[256 : 256 + COMMIT_SLOT_BYTES] = prior
    prefix[384 : 384 + COMMIT_SLOT_BYTES] = final
    return BuiltFixture(
        bytes(prefix),
        frames,
        record_offset,
        tuple(frame_offsets),
        terminal_offset,
    )


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def test_python_verifier_replays_all_canonical_modes_exactly(tmp_path: Path) -> None:
    fixture = _build_fixture()
    path = _write(tmp_path / "exact.ugsp4c", fixture.data)

    result = verify_ugsp4c(path)

    assert result.inspection.finalized
    assert result.inspection.selected_commit_slot == 1
    assert result.inspection.generation == 6
    assert result.inspection.uncommitted_tail_bytes == 0
    assert result.inspection.committed_frames == 4
    assert result.representation_counts == (1, 1, 1, 1)
    assert result.total_authoritative_bytes == 4 * 8 * 6 * 3 // 2
    decoded = list(Ugyuvs1Capture(path, require_final=True).iter_frames())
    assert len(decoded) == len(fixture.frames)
    for actual, expected in zip(decoded, fixture.frames):
        assert actual.sensor_timestamp_ns == expected.sensor_pts
        assert actual.frame_number == expected.frame_number
        assert actual.y == expected.y
        assert actual.u == expected.u
        assert actual.v == expected.v
        assert actual.canonical_metadata == expected.metadata
        assert actual.dense.pre_substrate_sha256 == actual.pre_substrate_sha256


def test_newest_valid_commit_falls_back_to_durable_partial_prefix(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture()
    damaged = bytearray(fixture.data)
    damaged[384 + COMMIT_DIGEST_OFFSET] ^= 0x80
    path = _write(tmp_path / "capture.ugsp4c.partial", bytes(damaged))

    result = verify_ugsp4c(path, allow_partial=True)

    assert result.inspection.selected_commit_slot == 0
    assert result.inspection.generation == 5
    assert result.inspection.recovered_incomplete
    assert result.inspection.uncommitted_tail_bytes == TERMINAL_HEADER_BYTES
    assert len(result.frames) == 4
    with pytest.raises(Ugyuvs1Error, match="FINAL"):
        verify_ugsp4c(path)


def test_completed_extension_requires_final_and_both_bad_slots_fail(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture()
    no_final = bytearray(fixture.data)
    no_final[384 + COMMIT_DIGEST_OFFSET] ^= 1
    final_path = _write(tmp_path / "not_final.ugsp4c", bytes(no_final))
    with pytest.raises(Ugyuvs1Error, match="FINAL"):
        Ugyuvs1Capture(final_path)

    no_commits = bytearray(no_final)
    no_commits[256 + COMMIT_DIGEST_OFFSET] ^= 1
    partial_path = _write(tmp_path / "no_commit.partial", bytes(no_commits))
    with pytest.raises(Ugyuvs1Error, match="neither crash-safe commit"):
        Ugyuvs1Capture(partial_path)


def test_frame_payload_and_terminal_corruption_fail_closed(tmp_path: Path) -> None:
    fixture = _build_fixture()
    payload_corrupt = bytearray(fixture.data)
    payload_corrupt[fixture.frame_offsets[0] + FRAME_HEADER_BYTES + BLOCK_HEADER_BYTES] ^= 0x5A
    payload_path = _write(tmp_path / "payload_corrupt.ugsp4c", bytes(payload_corrupt))
    with pytest.raises(Ugyuvs1Error, match="frame content SHA-256"):
        verify_ugsp4c(payload_path)

    terminal_corrupt = bytearray(fixture.data)
    terminal_corrupt[fixture.terminal_offset + 24] ^= 1
    terminal_path = _write(
        tmp_path / "terminal_corrupt.ugsp4c", bytes(terminal_corrupt)
    )
    with pytest.raises(Ugyuvs1Error, match="terminal record"):
        verify_ugsp4c(terminal_path)


def test_noncanonical_block_representation_fails_even_when_hash_bound(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(force_frame2_representation=2)
    path = _write(tmp_path / "noncanonical.ugsp4c", fixture.data)
    with pytest.raises(Ugyuvs1Error, match="canonical byte-smallest"):
        verify_ugsp4c(path)


def test_verify_ugsp4c_cli_writes_same_receipt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fixture = _build_fixture()
    path = _write(tmp_path / "cli.ugsp4c", fixture.data)
    receipt = tmp_path / "receipt.json"

    assert cli_main(["verify-ugsp4c", str(path), "--output", str(receipt)]) == 0

    stdout = json.loads(capsys.readouterr().out)
    stored = json.loads(receipt.read_text(encoding="utf-8"))
    assert stdout == stored
    assert stdout["status"] == "PASS"
    assert stdout["profile"] == "UGCODE24_420_CAMERA_EXACT"


@pytest.mark.skipif(
    "UGYUVS1_CPP_FIXTURE" not in os.environ,
    reason="set UGYUVS1_CPP_FIXTURE to cross-check a persistent native fixture",
)
def test_persistent_native_cpp_fixture_cross_language() -> None:
    path = Path(os.environ["UGYUVS1_CPP_FIXTURE"])

    result = verify_ugsp4c(path)

    assert result.inspection.committed_frames == 4
    assert result.total_novelty_events == 100_469
    known_native_artifacts = {
        "22ac87ed1ffeecd50b7eb2609ac8326ec002e0414cc0d3c3dd940271446216d1": 114_845,
        "d373b547e24bd2f8548ec190b29fa16a64627ba2c00661d499158828812a0b20": 125_601,
    }
    assert result.file_sha256 in known_native_artifacts
    assert result.inspection.actual_bytes == known_native_artifacts[result.file_sha256]
    assert (
        result.frames[0]["pre_substrate_sha256"]
        == "eccb2f605f75783d5d128b673796f87e58c185ad364f256c464c2c0f291633f0"
    )
