"""Regenerate the tiny cross-language UGTC4D native decoder fixture.

This is an authoring helper only.  The C++ host test consumes the emitted
custom container without Python and independently regenerates the traversal,
entropy output, prediction state, and Cartesian RGB bytes.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np

from ugts_kc3.chrono_codec import DecodedStreamHasher, encode_substrate_frame
from ugts_kc3.chrono_container import (
    UGTC4D_FLAG_CHRONO_GEOMETRY,
    UGTC4D_FLAG_CUSTOM_PREDICTION,
    UGTC4D_FLAG_LOSSLESS_RGB8,
    UGTC4D_FLAG_UGLUT2_POLAR,
    Ugtc4dHeader,
    Ugtc4dSection,
    build_ugtc4d_bytes,
)
from ugts_kc3.chrono_prediction import (
    PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER,
    PREDICTOR_CARTESIAN_MEDIAN_Q709_CODEWORD_SUBSTRATE_ORDER,
    PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN,
    build_substrate_prediction_plan,
)
from ugts_kc3.chrono_substrate import (
    create_substrate_traversal_recipe,
    derive_substrate_traversal,
    gather_rgb_substrate_numpy,
)
from ugts_kc3.packed_kinematics import LogPolarProfile, PolarLookupTable


WIDTH = 8
HEIGHT = 6


def frame(ordinal: int) -> np.ndarray:
    y, x = np.mgrid[0:HEIGHT, 0:WIDTH]
    result = np.empty((HEIGHT, WIDTH, 3), dtype=np.uint8)
    result[:, :, 0] = (x * 29 + y * 11 + 7) & 255
    result[:, :, 1] = (x * 13 + y * 37 + 19) & 255
    result[:, :, 2] = ((x ^ y) * 41 + x * 3 + 23) & 255
    if ordinal:
        result[:, :, 0] = (
            result[:, :, 0].astype(np.uint16) + ordinal * ((x + y) % 3)
        ) & 255
        result[:, :, 1] = (
            result[:, :, 1].astype(np.uint16) + ordinal * ((2 * x + y) % 2)
        ) & 255
        result[:, :, 2] = (
            result[:, :, 2].astype(np.uint16) + ordinal * ((x + 2 * y) % 4)
        ) & 255
    return result


def main() -> None:
    output = Path(__file__).with_name("ugtc4d_native_fixture.ugtc4d")
    source_digest = hashlib.sha256(b"UGTC4D native C++17 fixture authority v1").digest()
    profile = LogPolarProfile(
        r0=1.0,
        rho_min=math.log(0.5),
        rho_max=math.log(16_000.0),
        core_radius=0.5,
    )
    lut_bytes = PolarLookupTable.generate(profile, 16).to_bytes()
    output.with_name("uglut2_native_fixture.bin").write_bytes(lut_bytes)
    recipe = create_substrate_traversal_recipe(
        WIDTH,
        HEIGHT,
        lut_bytes,
        root_seed=int.from_bytes(source_digest[:8], "little"),
        recipe_seed=1,
    )
    recipe_bytes = recipe.to_bytes()
    traversal = derive_substrate_traversal(recipe, lut_bytes)
    plan = build_substrate_prediction_plan(
        recipe,
        lut_bytes,
        traversal=traversal,
    )
    cartesian = [frame(0), frame(1), frame(2)]
    polar = [
        gather_rgb_substrate_numpy(item, recipe, lut_bytes, traversal=traversal)
        for item in cartesian
    ]
    records = [
        encode_substrate_frame(
            polar[0],
            plan,
            uglut2_bytes=lut_bytes,
            traversal_recipe_bytes=recipe_bytes,
            ordinal=0,
            source_pts=100,
            source_end_pts_exclusive=140,
            predictor=PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER,
            entropy_block_sizes=(256,),
        ),
        encode_substrate_frame(
            polar[1],
            plan,
            uglut2_bytes=lut_bytes,
            traversal_recipe_bytes=recipe_bytes,
            ordinal=1,
            source_pts=140,
            source_end_pts_exclusive=180,
            predictor=PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN,
            previous_polar_rgb=polar[0],
            previous_ordinal=0,
            entropy_block_sizes=(256,),
        ),
        encode_substrate_frame(
            polar[2],
            plan,
            uglut2_bytes=lut_bytes,
            traversal_recipe_bytes=recipe_bytes,
            ordinal=2,
            source_pts=180,
            source_end_pts_exclusive=220,
            predictor=PREDICTOR_CARTESIAN_MEDIAN_Q709_CODEWORD_SUBSTRATE_ORDER,
            entropy_block_sizes=(256,),
        ),
    ]
    stream = DecodedStreamHasher(
        width=WIDTH,
        height=HEIGHT,
        time_base_num=1,
        time_base_den=1_000,
    )
    for ordinal, item in enumerate(cartesian):
        stream.update(ordinal, 100 + ordinal * 40, 140 + ordinal * 40, item.tobytes())
    header = Ugtc4dHeader(
        flags=(
            UGTC4D_FLAG_LOSSLESS_RGB8
            | UGTC4D_FLAG_CUSTOM_PREDICTION
            | UGTC4D_FLAG_UGLUT2_POLAR
            | UGTC4D_FLAG_CHRONO_GEOMETRY
        ),
        width=WIDTH,
        height=HEIGHT,
        frame_count=3,
        checkpoint_interval=2,
        first_source_pts=100,
        end_source_pts_exclusive=220,
        time_base_num=1,
        time_base_den=1_000,
        center_x=(WIDTH - 1) * 0.5,
        center_y=(HEIGHT - 1) * 0.5,
        r0=profile.r0,
        core_radius=profile.core_radius,
        rho_min=profile.rho_min,
        rho_max=profile.rho_max,
        lut_resolution=16,
        source_sha256=source_digest.hex(),
        decoded_stream_sha256=stream.hexdigest(),
    )
    sections = [
        Ugtc4dSection.canonical_json(kind, {"schema": "native-cpp17-fixture-v1"})
        for kind in (
            "MANIFEST",
            "OPERATOR",
            "OBSERVE",
            "HYPOTHES",
            "GEOMETRY",
            "NOVELTY",
            "CHECKPNT",
            "SCENE3D",
        )
    ]
    sections.extend(
        (
            Ugtc4dSection.raw("UGLUT2", lut_bytes),
            Ugtc4dSection.raw("TRAVERS", recipe_bytes),
            Ugtc4dSection.raw("FRAME", records[0].to_bytes(), record_start=0),
            Ugtc4dSection.raw("FRAME", records[1].to_bytes(), record_start=1),
            Ugtc4dSection.raw("FRAME", records[2].to_bytes(), record_start=2),
        )
    )
    output.write_bytes(build_ugtc4d_bytes(header, sections))
    print(
        f"{output} bytes={output.stat().st_size} "
        f"sha256={hashlib.sha256(output.read_bytes()).hexdigest()} "
        f"traversal={recipe.traversal_sha256}"
    )


if __name__ == "__main__":
    main()
