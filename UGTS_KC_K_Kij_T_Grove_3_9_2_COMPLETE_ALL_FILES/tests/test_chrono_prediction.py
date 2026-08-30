from __future__ import annotations

import math

import numpy as np
import pytest

from ugts_kc3.chrono_prediction import (
    PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER,
    PREDICTOR_CARTESIAN_MEDIAN_Q709_CODEWORD_SUBSTRATE_ORDER,
    PREDICTOR_CARTESIAN_MEDIAN_GREEN_SUBSTRATE_ORDER,
    PREDICTOR_SUBSTRATE_MEDIAN_GREEN,
    PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN,
    build_substrate_prediction_plan,
    decode_q709_codewords_to_rgb_numpy,
    decode_substrate_prediction_numpy,
    encode_rgb_to_q709_codewords_numpy,
    encode_substrate_prediction_cuda,
    encode_substrate_prediction_numpy,
)
from ugts_kc3.chrono_substrate import (
    create_substrate_traversal_recipe,
    derive_substrate_traversal,
    gather_rgb_substrate_numpy,
)
from ugts_kc3.packed_kinematics import LogPolarProfile, PolarLookupTable


def _fixture() -> tuple[bytes, object, object]:
    profile = LogPolarProfile(1.0, math.log(0.5), math.log(32.0), 0.5)
    lut = PolarLookupTable.generate(profile, 64).to_bytes()
    recipe = create_substrate_traversal_recipe(
        23, 17, lut, root_seed=0x123456789ABCDEF0, recipe_seed=4
    )
    traversal = derive_substrate_traversal(recipe, lut)
    plan = build_substrate_prediction_plan(recipe, lut, traversal=traversal)
    return lut, recipe, plan


def _frames() -> tuple[np.ndarray, np.ndarray]:
    y, x = np.indices((17, 23), dtype=np.uint16)
    first = np.stack(
        ((x * 9 + y * 3), (x * 2 + y * 11), (x * 5 + y * 7)), axis=2
    ).astype(np.uint8)
    second = first.copy()
    second[4:11, 8:16] ^= np.array([3, 17, 29], dtype=np.uint8)
    return first, second


@pytest.mark.parametrize(
    "predictor",
    [
        PREDICTOR_SUBSTRATE_MEDIAN_GREEN,
        PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN,
        PREDICTOR_CARTESIAN_MEDIAN_GREEN_SUBSTRATE_ORDER,
        PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER,
        PREDICTOR_CARTESIAN_MEDIAN_Q709_CODEWORD_SUBSTRATE_ORDER,
    ],
)
def test_substrate_prediction_round_trip(predictor: int) -> None:
    lut, recipe, plan = _fixture()
    first, second = _frames()
    polar_first = gather_rgb_substrate_numpy(first, recipe, lut, traversal=plan.traversal)
    polar_second = gather_rgb_substrate_numpy(second, recipe, lut, traversal=plan.traversal)
    previous = (
        polar_first if predictor == PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN else None
    )
    target = polar_second if previous is not None else polar_first
    residual = encode_substrate_prediction_numpy(
        target, plan, predictor=predictor, previous_polar_rgb=previous
    )
    decoded = decode_substrate_prediction_numpy(
        residual, plan, predictor=predictor, previous_polar_rgb=previous
    )
    assert np.array_equal(decoded, target)


def test_plan_is_regenerated_and_every_dependency_precedes_its_pixel() -> None:
    _lut, _recipe, plan = _fixture()
    ordinal = np.arange(plan.pixel_count)
    assert plan.parent[0] == -1
    assert np.all((plan.parent < 0) | (plan.parent < ordinal))
    for dependency in (plan.a, plan.b, plan.c):
        assert np.all(~plan.use_median | ((dependency >= 0) & (dependency < ordinal)))
    assert plan.ram_bytes > plan.traversal.nbytes


def test_q709_codeword_is_bijective_over_the_complete_rgb24_domain() -> None:
    green, blue = np.meshgrid(
        np.arange(256, dtype=np.uint8),
        np.arange(256, dtype=np.uint8),
        indexing="ij",
    )
    tested = 0
    for red in range(256):
        rgb = np.empty((256, 256, 3), dtype=np.uint8)
        rgb[..., 0] = red
        rgb[..., 1] = green
        rgb[..., 2] = blue
        codewords = encode_rgb_to_q709_codewords_numpy(rgb)
        assert np.array_equal(decode_q709_codewords_to_rgb_numpy(codewords), rgb)
        tested += rgb.shape[0] * rgb.shape[1]
    assert tested == 1 << 24


def test_cuda_encoder_matches_cpu_oracle_when_available() -> None:
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("CUDA is unavailable")
    lut, recipe, plan = _fixture()
    first, second = _frames()
    polar = np.stack(
        [
            gather_rgb_substrate_numpy(frame, recipe, lut, traversal=plan.traversal)
            for frame in (first, second)
        ]
    )
    expected = np.stack(
        [
            np.frombuffer(
                encode_substrate_prediction_numpy(
                    frame,
                    plan,
                    predictor=PREDICTOR_SUBSTRATE_MEDIAN_GREEN,
                ),
                dtype=np.uint8,
            ).reshape(3, plan.pixel_count)
            for frame in polar
        ]
    )
    actual, receipt = encode_substrate_prediction_cuda(
        polar,
        plan,
        predictor=PREDICTOR_SUBSTRATE_MEDIAN_GREEN,
        max_vram_mib=256,
    )
    assert np.array_equal(actual, expected)
    assert receipt["integer_byte_exact"] is True


def test_temporal_cuda_encoder_matches_cpu_oracle_when_available() -> None:
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("CUDA is unavailable")
    lut, recipe, plan = _fixture()
    first, second = _frames()
    polar_first = gather_rgb_substrate_numpy(first, recipe, lut, traversal=plan.traversal)
    polar_second = gather_rgb_substrate_numpy(second, recipe, lut, traversal=plan.traversal)
    expected = np.frombuffer(
        encode_substrate_prediction_numpy(
            polar_second,
            plan,
            predictor=PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN,
            previous_polar_rgb=polar_first,
        ),
        dtype=np.uint8,
    ).reshape(1, 3, plan.pixel_count)
    actual, _receipt = encode_substrate_prediction_cuda(
        polar_second[None, ...],
        plan,
        predictor=PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN,
        previous_polar_frames=polar_first[None, ...],
        max_vram_mib=256,
    )
    assert np.array_equal(actual, expected)


@pytest.mark.parametrize(
    "predictor",
    [
        PREDICTOR_CARTESIAN_MEDIAN_GREEN_SUBSTRATE_ORDER,
        PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER,
        PREDICTOR_CARTESIAN_MEDIAN_Q709_CODEWORD_SUBSTRATE_ORDER,
    ],
)
def test_cartesian_median_substrate_order_cuda_matches_cpu(predictor: int) -> None:
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("CUDA is unavailable")
    lut, recipe, plan = _fixture()
    first, second = _frames()
    polar = np.stack(
        [
            gather_rgb_substrate_numpy(frame, recipe, lut, traversal=plan.traversal)
            for frame in (first, second)
        ]
    )
    expected = np.stack(
        [
            np.frombuffer(
                encode_substrate_prediction_numpy(
                    frame,
                    plan,
                    predictor=predictor,
                ),
                dtype=np.uint8,
            ).reshape(3, plan.pixel_count)
            for frame in polar
        ]
    )
    actual, receipt = encode_substrate_prediction_cuda(
        polar,
        plan,
        predictor=predictor,
        max_vram_mib=256,
    )
    assert np.array_equal(actual, expected)
    assert receipt["integer_byte_exact"] is True
