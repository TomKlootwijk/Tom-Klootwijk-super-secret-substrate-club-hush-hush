from __future__ import annotations

import hashlib
from pathlib import Path
import random

from ugts_kc3.chrono_substrate import (
    create_substrate_traversal_recipe,
    derive_substrate_coordinate_codes,
    derive_substrate_traversal,
)
from ugts_kc3.full_substrate_camera import (
    FullSubstrateCameraProgram,
    corrected_morton_key,
    frame_kinematics,
    klein_address,
    klb37_even_parity,
    make_klb37,
    median_predictor,
    q15_pixel_center,
    sclp64_contiguous,
    seed_word,
    triangular32,
)
from ugts_kc3.gsp4_camera_codeword import DenseYuv420Frame


ROOT = Path(__file__).parents[1]
LUT_PATH = ROOT / "native/host_tests/fixtures/uglut2_native_fixture.bin"
ROOT_SEED = 0x0123456789ABCDEF


def _program() -> FullSubstrateCameraProgram:
    lut = LUT_PATH.read_bytes()
    recipe = create_substrate_traversal_recipe(
        8,
        6,
        lut,
        root_seed=ROOT_SEED,
        recipe_seed=1,
    )
    return FullSubstrateCameraProgram(recipe, lut)


def test_seed_and_modular_kinematic_vectors() -> None:
    indexes = (0, 2, 3, 4, 8, 20, 21, 22, 32, 47)
    assert [seed_word(ROOT_SEED, index) for index in indexes] == [
        0x1F0251BC,
        0x8158659F,
        0xB3131412,
        0x3CFEF1C2,
        0x96446D67,
        0x58DAB4B1,
        0xFC6404C8,
        0xA5950CCF,
        0xA2C4A901,
        0xF31A5DF3,
    ]
    assert triangular32(0) == 0
    assert triangular32(1) == 0
    assert triangular32(2) == 1
    assert triangular32(0xFFFFFFFF) == 0x80000001
    state = frame_kinematics(ROOT_SEED, 3)
    assert (state.phi, state.omega, state.alpha) == (
        0x3EC5E976,
        0xED232B35,
        0xA5950CCF,
    )


def test_sclp64_and_corrected_morton_are_distinct_bijections() -> None:
    fields = (0xABCDE, 0x2AAAA, 0x1234, 0xFED)
    contiguous = sclp64_contiguous(*fields)
    morton = corrected_morton_key(*fields)
    assert contiguous == 0xABCDEAAAA9234FED
    assert morton == 0xD3D1F1D8FB43D1BA
    assert morton != contiguous


def test_klb37_keeps_elevation_separate_and_has_even_parity() -> None:
    code_a = make_klb37(0x54321, 0x2AAAA, 17, 5)
    code_b = make_klb37(0x54321, 0x2AAAA, 18, 5)
    assert code_a != code_b
    assert klb37_even_parity(code_a)
    assert klb37_even_parity(code_b)
    assert ((code_a >> 23) & 0x3FF) == 17
    assert ((code_b >> 23) & 0x3FF) == 18


def test_discrete_klein_seam_is_a_permutation_and_reflects_up() -> None:
    width, height = 8, 6
    mapped = [
        klein_address(x, y, width, height)[0]
        for y in range(height)
        for x in range(width)
    ]
    assert sorted(mapped) == list(range(width * height))
    assert klein_address(2, -1, width, height) == (45, True)
    assert klein_address(1, -1, width, height) == (46, True)
    assert klein_address(-1, 0, width, height) == (7, False)


def test_q15_center_and_med_use_frozen_integer_rounding() -> None:
    assert q15_pixel_center(0, 8) == -28671
    assert q15_pixel_center(7, 8) == 28671
    assert q15_pixel_center(0, 6, invert=True) == 27305
    assert median_predictor(10, 40, 30) == 20
    assert median_predictor(250, 240, 0) == 250


def test_known_packed_operator_receipt_and_guard_bits() -> None:
    program = _program()
    words = program.operator_state(0, 0).receipt_words()
    assert words == (
        0x00000000,
        0x00033333,
        0x00008000,
        0x00064745,
        0x00018000,
        0x00000A72,
        0x64745600,
        0x08981009,
        0x1CD00911,
        0xFFB00323,
        0x00000005,
        0x4306FDC7,
        0xAA4B2E48,
        0x5A6AF331,
        0xF0EBF0EA,
        0x020DEBFF,
        0x00000007,
        0x0000002F,
        0x00000028,
        0x4A5400AA,
    )
    assert (
        program.operator_block_digest(3, 0, 48).hex()
        == "09319ae4b21bf4e2df51b83e2e280971034954b91e82524437e4062ffaef86ef"
    )


def test_random_camera_frames_round_trip_exactly() -> None:
    program = _program()
    random_source = random.Random(42)

    def frame(timestamp: int) -> DenseYuv420Frame:
        return DenseYuv420Frame(
            8,
            6,
            timestamp,
            bytes(random_source.randrange(256) for _ in range(48)),
            bytes(random_source.randrange(256) for _ in range(12)),
            bytes(random_source.randrange(256) for _ in range(12)),
        )

    first = frame(1)
    second = frame(2)
    residual0 = program.residual_for(first, None, 0, checkpoint=True)
    replay0 = program.reconstruct(
        residual0,
        None,
        frame_ordinal=0,
        sensor_timestamp_ns=1,
        checkpoint=True,
    )
    residual1 = program.residual_for(second, replay0, 1, checkpoint=False)
    replay1 = program.reconstruct(
        residual1,
        replay0,
        frame_ordinal=1,
        sensor_timestamp_ns=2,
        checkpoint=False,
    )
    assert replay0 == first
    assert replay1 == second
    assert hashlib.sha256(residual0).hexdigest() == (
        "2c76f6c7e28d3a7324cfcd56b450caad662436961c14c04db8901b8383816f63"
    )
    assert hashlib.sha256(residual1).hexdigest() == (
        "a0940be900c9c2d4d774549ffa10989233c7ab062303840e0aba9967cd3c61dc"
    )


def test_profile1_traversal_and_coordinate_derivation_remain_unchanged() -> None:
    lut = LUT_PATH.read_bytes()
    recipe = create_substrate_traversal_recipe(
        8,
        6,
        lut,
        root_seed=ROOT_SEED,
        recipe_seed=1,
    )
    traversal = derive_substrate_traversal(recipe, lut)
    rho20, theta18 = derive_substrate_coordinate_codes(recipe, lut)
    assert recipe.traversal_sha256 == (
        "81d1da92df94cf4fdcf7bb87cb0265a232de25f1e99f7f3c086400e97ab70808"
    )
    assert len(traversal) == len(rho20) == len(theta18) == 48
    assert sorted(int(value) for value in traversal) == list(range(48))
