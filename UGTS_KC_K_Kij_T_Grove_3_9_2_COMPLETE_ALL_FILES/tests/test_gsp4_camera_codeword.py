from __future__ import annotations

import hashlib
import struct

import pytest

from ugts_kc3.gsp4_camera_codeword import (
    DenseYuv420Frame,
    Gsp4CameraCodewordError,
    apply_modular_residual,
    codeword_lineage,
    gsp4_mix32,
    modular_residual,
    normalize_yuv420_888,
    novelty_event_count,
    pack_codeword420,
    unpack_codeword420,
)


def _fixture() -> DenseYuv420Frame:
    return DenseYuv420Frame(
        4,
        4,
        123_456_789,
        bytes(range(16)),
        bytes((40, 41, 42, 43)),
        bytes((90, 91, 92, 93)),
    )


def test_codeword420_owner_pack_is_bijective() -> None:
    frame = _fixture()
    traversal = (15, 0, 5, 10, 3, 12, 6, 9, 1, 14, 4, 11, 2, 13, 7, 8)

    packed = pack_codeword420(frame, traversal)

    assert len(packed) == 24
    assert packed[:4] == bytes((15, 0, 40, 90))
    assert unpack_codeword420(
        packed,
        width=4,
        height=4,
        sensor_timestamp_ns=frame.sensor_timestamp_ns,
        traversal=traversal,
    ) == frame
    assert frame.codeword(0, 0) == (0, 40, 90)
    assert frame.codeword(1, 1) == (5, 40, 90)
    assert frame.codeword(3, 2) == (11, 43, 93)


def test_camera2_stride_normalization_is_exact() -> None:
    # Four useful Y values per row with two padding bytes. Chroma is interleaved
    # through pixel_stride=2 but remains represented as distinct AImage planes.
    y = bytes((0, 1, 2, 3, 250, 251, 4, 5, 6, 7, 252, 253,
               8, 9, 10, 11, 254, 255, 12, 13, 14, 15, 248, 249))
    u = bytes((40, 200, 41, 201, 202, 203, 42, 204, 43, 205, 206, 207))
    v = bytes((90, 210, 91, 211, 212, 213, 92, 214, 93, 215, 216, 217))

    frame = normalize_yuv420_888(
        width=4,
        height=4,
        sensor_timestamp_ns=88,
        y_plane=y,
        u_plane=u,
        v_plane=v,
        y_row_stride=6,
        y_pixel_stride=1,
        u_row_stride=6,
        u_pixel_stride=2,
        v_row_stride=6,
        v_pixel_stride=2,
    )

    assert frame.y == bytes(range(16))
    assert frame.u == bytes((40, 41, 42, 43))
    assert frame.v == bytes((90, 91, 92, 93))


def test_pre_substrate_digest_binds_time_dimensions_and_all_planes() -> None:
    frame = _fixture()
    expected = hashlib.sha256(
        struct.pack("<QII", 123_456_789, 4, 4) + frame.y + frame.u + frame.v
    ).hexdigest()
    assert frame.pre_substrate_sha256 == expected


def test_modular_novelty_round_trip_and_negative_memory() -> None:
    previous = bytes((0, 255, 128, 44, 9, 9))
    observed = bytes((0, 0, 127, 40, 9, 250))
    residual = modular_residual(observed, previous)

    assert residual == bytes((0, 1, 255, 252, 0, 241))
    assert novelty_event_count(residual) == 4
    assert apply_modular_residual(previous, residual) == observed


def test_gsp4_lineage_is_seed_addressed_and_frame_routed() -> None:
    assert gsp4_mix32(0) == 0
    assert gsp4_mix32(1) == 0x688990C0
    first = codeword_lineage(
        root_seed=0x0123456789ABCDEF,
        recipe_seed=1,
        cartesian_address=17,
        frame_ordinal=3,
    )
    repeated = codeword_lineage(
        root_seed=0x0123456789ABCDEF,
        recipe_seed=1,
        cartesian_address=17,
        frame_ordinal=3,
    )
    next_frame = codeword_lineage(
        root_seed=0x0123456789ABCDEF,
        recipe_seed=1,
        cartesian_address=17,
        frame_ordinal=4,
    )
    assert first == repeated
    assert first[0] == next_frame[0]
    assert first[1] != next_frame[1]


@pytest.mark.parametrize(
    ("width", "height", "message"),
    ((3, 4, "even dimensions"), (4, 3, "even dimensions"), (0, 4, "outside")),
)
def test_invalid_camera_dimensions_fail_closed(
    width: int, height: int, message: str
) -> None:
    with pytest.raises(Gsp4CameraCodewordError, match=message):
        DenseYuv420Frame(width, height, 0, b"", b"", b"")


def test_bad_traversal_and_bad_extent_fail_closed() -> None:
    frame = _fixture()
    with pytest.raises(Gsp4CameraCodewordError, match="repeats"):
        pack_codeword420(frame, [0] * 16)
    with pytest.raises(Gsp4CameraCodewordError, match="byte count"):
        unpack_codeword420(
            b"short", width=4, height=4, sensor_timestamp_ns=0,
            traversal=tuple(range(16))
        )
    with pytest.raises(Gsp4CameraCodewordError, match="extent exceeds"):
        normalize_yuv420_888(
            width=4,
            height=4,
            sensor_timestamp_ns=0,
            y_plane=b"x",
            u_plane=b"x",
            v_plane=b"x",
            y_row_stride=4,
            y_pixel_stride=1,
            u_row_stride=2,
            u_pixel_stride=1,
            v_row_stride=2,
            v_pixel_stride=1,
        )

