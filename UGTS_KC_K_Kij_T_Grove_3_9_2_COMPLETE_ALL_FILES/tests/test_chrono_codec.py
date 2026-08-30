from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
import pytest

from ugts_kc3.chrono_codec import (
    ChronoCodecError,
    DecodedStreamHasher,
    FRAME_CHECKPOINT,
    decode_run_tokens,
    decode_substrate_frame,
    encode_run_tokens,
    encode_substrate_frame,
)
from ugts_kc3.chrono_prediction import (
    PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER,
    build_substrate_prediction_plan,
)
from ugts_kc3.chrono_substrate import (
    create_substrate_traversal_recipe,
    derive_substrate_traversal,
    gather_rgb_substrate_numpy,
)
from ugts_kc3.packed_kinematics import LogPolarProfile, PolarLookupTable


@pytest.mark.parametrize(
    "raw",
    [b"", b"\0", bytes(400), b"abc", b"a" * 500, bytes(range(256)) * 3],
)
def test_custom_metadata_tokens_round_trip(raw: bytes) -> None:
    encoded = encode_run_tokens(raw)
    assert decode_run_tokens(encoded, expected_bytes=len(raw)) == raw


def test_custom_metadata_tokens_fail_closed() -> None:
    with pytest.raises(ChronoCodecError, match="reserved"):
        decode_run_tokens(b"\xc0", expected_bytes=0)
    with pytest.raises(ChronoCodecError, match="truncated"):
        decode_run_tokens(b"\x40", expected_bytes=3)
    with pytest.raises(ChronoCodecError, match="canonical"):
        decode_run_tokens(b"\x00\x00", expected_bytes=2)


def _fixture() -> tuple[bytes, bytes, object, np.ndarray]:
    profile = LogPolarProfile(1.0, math.log(0.5), math.log(32.0), 0.5)
    lut = PolarLookupTable.generate(profile, 16).to_bytes()
    recipe = create_substrate_traversal_recipe(
        23, 17, lut, root_seed=0x1867BAFA7C80C31F, recipe_seed=1
    )
    traversal = derive_substrate_traversal(recipe, lut)
    plan = build_substrate_prediction_plan(recipe, lut, traversal=traversal)
    y, x = np.indices((17, 23), dtype=np.uint16)
    cartesian = np.stack(
        ((x * 7 + y * 3), (x * 2 + y * 13), (x * 11 + y * 5)), axis=2
    ).astype(np.uint8)
    polar = gather_rgb_substrate_numpy(
        cartesian, recipe, lut, traversal=traversal
    )
    return lut, recipe.to_bytes(), plan, polar


def test_integrated_frame_round_trip_verifies_cartesian_rgb() -> None:
    lut, recipe, plan, polar = _fixture()
    record = encode_substrate_frame(
        polar,
        plan,
        uglut2_bytes=lut,
        traversal_recipe_bytes=recipe,
        ordinal=0,
        source_pts=0,
        source_end_pts_exclusive=39_824,
        entropy_block_sizes=(256, 1024),
    )
    assert record.flags == FRAME_CHECKPOINT
    assert record.predictor == PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER
    parsed, decoded_polar, decoded_cartesian = decode_substrate_frame(
        record.to_bytes(),
        plan,
        uglut2_bytes=lut,
        traversal_recipe_bytes=recipe,
    )
    assert parsed == record
    assert np.array_equal(decoded_polar, polar)
    assert hashlib.sha256(decoded_cartesian.tobytes()).hexdigest() == record.cartesian_sha256


def test_frame_binds_shared_lut_recipe_payload_and_content() -> None:
    lut, recipe, plan, polar = _fixture()
    record = encode_substrate_frame(
        polar,
        plan,
        uglut2_bytes=lut,
        traversal_recipe_bytes=recipe,
        ordinal=0,
        source_pts=5,
        source_end_pts_exclusive=8,
        entropy_block_sizes=(256,),
    )
    raw = bytearray(record.to_bytes())
    raw[-1] ^= 1
    with pytest.raises(ChronoCodecError, match="content SHA-256"):
        decode_substrate_frame(
            raw,
            plan,
            uglut2_bytes=lut,
            traversal_recipe_bytes=recipe,
        )
    with pytest.raises(ChronoCodecError, match="UGLUT2 dependency"):
        decode_substrate_frame(
            record.to_bytes(),
            plan,
            uglut2_bytes=lut[:-1] + bytes((lut[-1] ^ 1,)),
            traversal_recipe_bytes=recipe,
        )


def test_decoded_stream_hash_binds_cartesian_time_and_profile() -> None:
    first = DecodedStreamHasher(width=1, height=1, time_base_num=1, time_base_den=1000)
    first.update(0, 0, 40, b"\x01\x02\x03")
    second = DecodedStreamHasher(width=1, height=1, time_base_num=1, time_base_den=1000)
    second.update(0, 0, 41, b"\x01\x02\x03")
    assert first.hexdigest() != second.hexdigest()


def test_codec_module_has_no_conventional_media_payload_or_pixel_map() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "ugts_kc3" / "chrono_codec.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "import zlib",
        "import av",
        "import cv2",
        "ffmpeg",
        "libx264",
        "PolarPixelPermutation",
        "UGPXLUT1",
    ):
        assert forbidden not in source
