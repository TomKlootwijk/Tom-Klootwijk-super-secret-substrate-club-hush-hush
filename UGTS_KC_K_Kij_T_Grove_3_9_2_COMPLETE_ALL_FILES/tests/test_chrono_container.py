from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
import pytest

from ugts_kc3.chrono_codec import (
    ChronoCodecError,
    DecodedStreamHasher,
    encode_substrate_frame,
)
from ugts_kc3.chrono_container import (
    SECTION_FLAG_OPTIONAL,
    UGTC4D_FLAG_CHRONO_GEOMETRY,
    UGTC4D_FLAG_CUSTOM_PREDICTION,
    UGTC4D_FLAG_LOSSLESS_RGB8,
    UGTC4D_FLAG_UGLUT2_POLAR,
    Ugtc4dHeader,
    Ugtc4dSection,
    build_ugtc4d_bytes,
    decoded_json_section,
    inspect_ugtc4d_bytes,
)
from ugts_kc3.chrono_prediction import build_substrate_prediction_plan
from ugts_kc3.chrono_substrate import (
    create_substrate_traversal_recipe,
    derive_substrate_traversal,
    gather_rgb_substrate_numpy,
)
from ugts_kc3.packed_kinematics import LogPolarProfile, PolarLookupTable


def _fixture() -> tuple[Ugtc4dHeader, list[Ugtc4dSection]]:
    width, height = 10, 8
    profile = LogPolarProfile(1.0, math.log(0.5), math.log(16.0), 0.5)
    lut = PolarLookupTable.generate(profile, 16).to_bytes()
    recipe = create_substrate_traversal_recipe(
        width,
        height,
        lut,
        root_seed=0x1867BAFA7C80C31F,
        recipe_seed=1,
    )
    traversal = derive_substrate_traversal(recipe, lut)
    plan = build_substrate_prediction_plan(recipe, lut, traversal=traversal)
    first = np.arange(width * height * 3, dtype=np.uint8).reshape(height, width, 3)
    second = first.copy()
    second[2:6, 3:8] ^= np.array([5, 7, 11], dtype=np.uint8)
    cartesian_frames = (first, second)
    intervals = ((0, 39_824), (39_824, 79_648))
    encoded_frames = []
    recipe_bytes = recipe.to_bytes()
    stream = DecodedStreamHasher(
        width=width,
        height=height,
        time_base_num=1,
        time_base_den=1_000_000,
    )
    for ordinal, (cartesian, (pts, end_pts)) in enumerate(
        zip(cartesian_frames, intervals)
    ):
        polar = gather_rgb_substrate_numpy(
            cartesian, recipe, lut, traversal=traversal
        )
        encoded_frames.append(
            encode_substrate_frame(
                polar,
                plan,
                uglut2_bytes=lut,
                traversal_recipe_bytes=recipe_bytes,
                ordinal=ordinal,
                source_pts=pts,
                source_end_pts_exclusive=end_pts,
                entropy_block_sizes=(256, 1024),
            )
        )
        stream.update(ordinal, pts, end_pts, cartesian.tobytes())
    flags = (
        UGTC4D_FLAG_LOSSLESS_RGB8
        | UGTC4D_FLAG_CUSTOM_PREDICTION
        | UGTC4D_FLAG_UGLUT2_POLAR
        | UGTC4D_FLAG_CHRONO_GEOMETRY
    )
    header = Ugtc4dHeader(
        flags=flags,
        width=width,
        height=height,
        frame_count=2,
        checkpoint_interval=1,
        first_source_pts=0,
        end_source_pts_exclusive=79_648,
        time_base_num=1,
        time_base_den=1_000_000,
        center_x=(width - 1) * 0.5,
        center_y=(height - 1) * 0.5,
        r0=profile.r0,
        core_radius=profile.core_radius,
        rho_min=profile.rho_min,
        rho_max=profile.rho_max,
        lut_resolution=16,
        source_sha256=hashlib.sha256(b"source fixture").hexdigest(),
        decoded_stream_sha256=stream.hexdigest(),
    )
    unknown = {"schema": "fixture-0.1", "authority": "UNBOUNDED_UNKNOWN"}
    sections = [
        Ugtc4dSection.canonical_json(
            "MANIFEST",
            {
                "schema": "ugtoms-chrono-geometry-codec-manifest-0.2",
                "authority": "EXACT_ACCEPTED_DECODED_RGB8_WITH_GUARDED_GEOMETRY",
                "geometry": "UNBOUNDED_UNKNOWN",
            },
        ),
        Ugtc4dSection.canonical_json(
            "OPERATOR",
            {"schema": "ugtoms-chrono-geometry-operator-registry-0.2"},
        ),
        Ugtc4dSection.raw("UGLUT2", lut),
        Ugtc4dSection.raw("TRAVERS", recipe_bytes),
        *[
            Ugtc4dSection.raw(
                "FRAME", frame.to_bytes(), record_start=ordinal
            )
            for ordinal, frame in enumerate(encoded_frames)
        ],
        Ugtc4dSection.canonical_json("OBSERVE", unknown),
        Ugtc4dSection.canonical_json("HYPOTHES", unknown),
        Ugtc4dSection.canonical_json("GEOMETRY", unknown),
        Ugtc4dSection.canonical_json("NOVELTY", unknown),
        Ugtc4dSection.canonical_json("CHECKPNT", unknown),
        Ugtc4dSection.canonical_json("SCENE3D", unknown),
    ]
    return header, sections


def test_custom_container_round_trip_and_required_authority_sections() -> None:
    header, sections = _fixture()
    data = build_ugtc4d_bytes(header, sections)
    inspected = inspect_ugtc4d_bytes(data)
    assert inspected.header == header
    assert inspected.byte_length == len(data)
    assert len(inspected.sections_of_kind("FRAME")) == 2
    assert len(inspected.sections_of_kind("TRAVERS")[0].stored) == 128
    assert decoded_json_section(inspected.sections_of_kind("MANIFEST")[0])[
        "geometry"
    ] == "UNBOUNDED_UNKNOWN"


def test_custom_container_is_deterministic_under_section_input_order() -> None:
    header, sections = _fixture()
    assert build_ugtc4d_bytes(header, reversed(sections)) == build_ugtc4d_bytes(
        header, sections
    )


def test_custom_container_rejects_whole_file_and_section_corruption() -> None:
    header, sections = _fixture()
    data = bytearray(build_ugtc4d_bytes(header, sections))
    data[-1] ^= 1
    with pytest.raises(ChronoCodecError, match="whole-file SHA-256"):
        inspect_ugtc4d_bytes(data)

    original = bytearray(build_ugtc4d_bytes(header, sections))
    original[256] ^= 1
    original[216:248] = bytes(32)
    original[216:248] = hashlib.sha256(original).digest()
    with pytest.raises(ChronoCodecError, match="section SHA-256"):
        inspect_ugtc4d_bytes(original)


def test_custom_container_rejects_pixel_map_and_unknown_mandatory_section() -> None:
    header, sections = _fixture()
    sections.append(Ugtc4dSection.raw("POLARPIX", b"forbidden stored map"))
    with pytest.raises(ChronoCodecError, match="unknown mandatory"):
        build_ugtc4d_bytes(header, sections)
    sections[-1] = Ugtc4dSection.raw(
        "FUTURE", b"optional", flags=SECTION_FLAG_OPTIONAL
    )
    inspect_ugtc4d_bytes(build_ugtc4d_bytes(header, sections))


def test_custom_container_rejects_missing_or_duplicate_singleton() -> None:
    header, sections = _fixture()
    without_geometry = [section for section in sections if section.kind != "GEOMETRY"]
    with pytest.raises(ChronoCodecError, match="missing required sections: GEOMETRY"):
        build_ugtc4d_bytes(header, without_geometry)
    duplicate = list(sections) + [
        Ugtc4dSection.canonical_json(
            "GEOMETRY", {"schema": "duplicate"}, record_start=1
        )
    ]
    with pytest.raises(ChronoCodecError, match="singleton"):
        build_ugtc4d_bytes(header, duplicate)


def test_semantic_address_ignores_metadata_storage_tokenization() -> None:
    logical = b'{"a":1}'
    raw = Ugtc4dSection.raw("MANIFEST", logical)
    coded = Ugtc4dSection.run_coded("MANIFEST", logical)
    assert raw.semantic_address == coded.semantic_address


def test_json_sections_are_canonical_and_custom_run_coded() -> None:
    section = Ugtc4dSection.canonical_json("MANIFEST", {"z": 1, "a": [2, 3]})
    assert section.logical() == b'{"a":[2,3],"z":1}'
    assert decoded_json_section(section) == {"a": [2, 3], "z": 1}


def test_container_module_does_not_wrap_an_existing_container_or_codec() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "ugts_kc3" / "chrono_container.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "import zipfile",
        "import zlib",
        "import av",
        "import cv2",
        "ffmpeg",
        "libx264",
    ):
        assert forbidden not in source
