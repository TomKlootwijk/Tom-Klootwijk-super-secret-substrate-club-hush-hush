from __future__ import annotations

import hashlib
import math
from pathlib import Path

import pytest

from ugts_kc3.chrono_codec import (
    ChronoCodecError,
    encode_polar_frame,
    generate_polar_pixel_permutation,
)
from ugts_kc3.chrono_container import (
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
from ugts_kc3.packed_kinematics import LogPolarProfile, PolarLookupTable


def _fixture() -> tuple[Ugtc4dHeader, list[Ugtc4dSection]]:
    profile = LogPolarProfile(
        r0=1.0,
        rho_min=math.log(0.5),
        rho_max=math.log(math.hypot(4.5, 3.5)),
        core_radius=0.5,
    )
    lut = PolarLookupTable.generate(profile, 64).to_bytes()
    permutation = generate_polar_pixel_permutation(10, 8, lut)
    first = bytes((index * 13 + 7) & 255 for index in range(10 * 8 * 3))
    second = bytearray(first)
    second[40:61] = bytes((value ^ 5) for value in second[40:61])
    frame0 = encode_polar_frame(first, ordinal=0, source_pts=0, checkpoint=True)
    frame1 = encode_polar_frame(
        second,
        ordinal=1,
        source_pts=39_824,
        previous_polar_rgb_bytes=first,
        previous_ordinal=0,
    )
    stream_hash = hashlib.sha256()
    for ordinal, pts, rgb in ((0, 0, first), (1, 39_824, bytes(second))):
        import struct

        stream_hash.update(struct.pack("<IqQ", ordinal, pts, len(rgb)))
        stream_hash.update(rgb)
    flags = (
        UGTC4D_FLAG_LOSSLESS_RGB8
        | UGTC4D_FLAG_CUSTOM_PREDICTION
        | UGTC4D_FLAG_UGLUT2_POLAR
        | UGTC4D_FLAG_CHRONO_GEOMETRY
    )
    header = Ugtc4dHeader(
        flags=flags,
        width=10,
        height=8,
        frame_count=2,
        checkpoint_interval=2,
        first_source_pts=0,
        end_source_pts_exclusive=79_648,
        time_base_num=1,
        time_base_den=1_000_000,
        center_x=4.5,
        center_y=3.5,
        r0=profile.r0,
        core_radius=profile.core_radius,
        rho_min=profile.rho_min,
        rho_max=profile.rho_max,
        lut_resolution=64,
        source_sha256=hashlib.sha256(b"source fixture").hexdigest(),
        decoded_stream_sha256=stream_hash.hexdigest(),
    )
    manifest = {
        "schema": "ugtoms-chrono-geometry-codec-manifest-0.1",
        "authority": "LITERAL_OBSERVATION_WITH_GUARDED_GEOMETRY",
        "geometry": "UNBOUNDED_UNKNOWN",
    }
    operator = {
        "schema": "ugtoms-chrono-geometry-operator-registry-0.1",
        "operators": [],
    }
    unknown = {
        "schema": "fixture",
        "authority": "UNBOUNDED_UNKNOWN",
    }
    sections = [
        Ugtc4dSection.canonical_json("MANIFEST", manifest),
        Ugtc4dSection.canonical_json("OPERATOR", operator),
        Ugtc4dSection.raw("UGLUT2", lut),
        Ugtc4dSection.raw("POLARPIX", permutation.to_bytes()),
        Ugtc4dSection.raw("FRAME", frame0.to_bytes(), record_start=0),
        Ugtc4dSection.raw("FRAME", frame1.to_bytes(), record_start=1),
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
    assert decoded_json_section(inspected.sections_of_kind("MANIFEST")[0])[
        "geometry"
    ] == "UNBOUNDED_UNKNOWN"
    assert inspected.content_sha256 == data[216:248].hex()


def test_custom_container_is_deterministic_under_section_input_order() -> None:
    header, sections = _fixture()
    forward = build_ugtc4d_bytes(header, sections)
    reverse = build_ugtc4d_bytes(header, reversed(sections))
    assert reverse == forward


def test_custom_container_rejects_whole_file_and_section_corruption() -> None:
    header, sections = _fixture()
    data = bytearray(build_ugtc4d_bytes(header, sections))
    data[-1] ^= 1
    with pytest.raises(ChronoCodecError, match="whole-file SHA-256"):
        inspect_ugtc4d_bytes(data)

    # Rehashing the whole file cannot hide a section digest mismatch.
    original = bytearray(build_ugtc4d_bytes(header, sections))
    original[256] ^= 1
    original[216:248] = bytes(32)
    original[216:248] = hashlib.sha256(original).digest()
    with pytest.raises(ChronoCodecError, match="section SHA-256"):
        inspect_ugtc4d_bytes(original)


def test_custom_container_rejects_missing_geometry_authority_layer() -> None:
    header, sections = _fixture()
    without_geometry = [section for section in sections if section.kind != "GEOMETRY"]
    with pytest.raises(ChronoCodecError, match="missing required sections: GEOMETRY"):
        build_ugtc4d_bytes(header, without_geometry)


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
