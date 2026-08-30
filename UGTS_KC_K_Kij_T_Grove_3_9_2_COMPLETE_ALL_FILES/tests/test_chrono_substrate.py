from __future__ import annotations

import hashlib
import math

import numpy as np
import pytest

from ugts_kc3.chrono_substrate import (
    ChronoSubstrateError,
    SubstrateTraversalRecipe,
    TRAVERSAL_RECIPE_BYTES,
    create_substrate_traversal_recipe,
    derive_substrate_traversal,
    gather_rgb_substrate_numpy,
    scatter_rgb_substrate_numpy,
)
from ugts_kc3.packed_kinematics import LogPolarProfile, PolarLookupTable


def _lut_bytes(resolution: int = 64) -> bytes:
    profile = LogPolarProfile(
        r0=1.0,
        rho_min=math.log(0.5),
        rho_max=4.0,
        core_radius=0.5,
    )
    return PolarLookupTable.generate(profile, resolution).to_bytes()


def test_seeded_recipe_is_fixed_size_and_contains_no_permutation() -> None:
    lut = _lut_bytes()
    recipe = create_substrate_traversal_recipe(
        17,
        11,
        lut,
        root_seed=0x1867BAFA7C80C31F,
        recipe_seed=7,
    )
    encoded = recipe.to_bytes()
    assert len(encoded) == TRAVERSAL_RECIPE_BYTES
    assert len(encoded) < recipe.pixel_count * 4
    decoded = SubstrateTraversalRecipe.from_bytes(
        encoded,
        uglut2_bytes=lut,
        verify_derived_traversal=True,
    )
    assert decoded == recipe


def test_traversal_is_a_seeded_full_bijection_and_reproducible() -> None:
    lut = _lut_bytes()
    first = create_substrate_traversal_recipe(
        16, 12, lut, root_seed=1234, recipe_seed=5
    )
    second = create_substrate_traversal_recipe(
        16, 12, lut, root_seed=1234, recipe_seed=6
    )
    order_a = derive_substrate_traversal(first, lut)
    order_b = derive_substrate_traversal(first, lut)
    order_c = derive_substrate_traversal(second, lut)
    assert np.array_equal(order_a, order_b)
    assert sorted(order_a.tolist()) == list(range(16 * 12))
    assert not np.array_equal(order_a, order_c)
    assert hashlib.sha256(order_a.astype("<u4").tobytes()).hexdigest() == first.traversal_sha256


def test_rgb_round_trip_uses_regenerated_traversal() -> None:
    lut = _lut_bytes()
    recipe = create_substrate_traversal_recipe(
        13, 9, lut, root_seed=99, recipe_seed=101
    )
    source = np.arange(13 * 9 * 3, dtype=np.uint8).reshape(9, 13, 3)
    order = derive_substrate_traversal(recipe, lut)
    polar = gather_rgb_substrate_numpy(source, recipe, lut, traversal=order)
    restored = scatter_rgb_substrate_numpy(polar, recipe, lut, traversal=order)
    assert np.array_equal(restored, source)


def test_recipe_rejects_wrong_lut_and_tampered_digest() -> None:
    lut = _lut_bytes()
    recipe = create_substrate_traversal_recipe(
        8, 8, lut, root_seed=1, recipe_seed=2
    )
    other = _lut_bytes(128)
    with pytest.raises(ChronoSubstrateError, match="dependency"):
        SubstrateTraversalRecipe.from_bytes(recipe.to_bytes(), uglut2_bytes=other)
    tampered = bytearray(recipe.to_bytes())
    tampered[80] ^= 1
    with pytest.raises(ChronoSubstrateError):
        SubstrateTraversalRecipe.from_bytes(
            bytes(tampered),
            uglut2_bytes=lut,
            verify_derived_traversal=True,
        )


def test_radius_scale_other_than_one_fails_closed() -> None:
    profile = LogPolarProfile(r0=1.0, rho_min=-12.0, rho_max=12.0, core_radius=1e-6)
    lut = PolarLookupTable.generate(profile, 16).to_bytes()
    with pytest.raises(ChronoSubstrateError, match="unit UGLUT2 radius scale"):
        create_substrate_traversal_recipe(4, 4, lut, root_seed=1, recipe_seed=1)
