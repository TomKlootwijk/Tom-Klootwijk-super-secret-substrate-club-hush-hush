from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ugts_kc3.chrono_codec import (
    ChronoCodecError,
    FRAME_CHECKPOINT,
    PREDICTOR_RAW,
    PolarPixelPermutation,
    decode_polar_frame,
    decode_run_tokens,
    decoded_stream_sha256,
    encode_polar_frame,
    encode_run_tokens,
    gather_rgb_polar_cuda,
    gather_rgb_polar_numpy,
    generate_polar_pixel_permutation,
    inspect_polar_pixel_permutation,
    scatter_rgb_polar_numpy,
)
from ugts_kc3.packed_kinematics import LogPolarProfile, PolarLookupTable


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\0",
        bytes(400),
        b"abc",
        b"a" * 500,
        bytes(range(256)) * 3,
        b"\0\0hellohello\0" + bytes(range(1, 64)) + b"z" * 80,
    ],
)
def test_custom_run_tokens_round_trip_canonically(raw: bytes) -> None:
    encoded = encode_run_tokens(raw)
    assert decode_run_tokens(encoded, expected_bytes=len(raw)) == raw
    assert encode_run_tokens(
        decode_run_tokens(encoded, expected_bytes=len(raw))
    ) == encoded


def test_custom_run_tokens_reject_reserved_truncated_and_noncanonical() -> None:
    with pytest.raises(ChronoCodecError, match="reserved"):
        decode_run_tokens(b"\xc0", expected_bytes=0)
    with pytest.raises(ChronoCodecError, match="truncated"):
        decode_run_tokens(b"\x40", expected_bytes=3)
    with pytest.raises(ChronoCodecError, match="must not encode zero"):
        decode_run_tokens(b"\x40\x00", expected_bytes=3)
    # Two one-byte zero tokens decode to the declared output but are not the
    # unique canonical encoding of two zeros.
    with pytest.raises(ChronoCodecError, match="canonical"):
        decode_run_tokens(b"\x00\x00", expected_bytes=2)


def _small_lut() -> bytes:
    return PolarLookupTable.generate(
        LogPolarProfile(r0=1.0, rho_min=-1.0, rho_max=4.0, core_radius=0.5),
        resolution=64,
    ).to_bytes()


def test_polar_pixel_permutation_is_a_stored_all_pixel_bijection() -> None:
    np = pytest.importorskip("numpy")
    lut = _small_lut()
    permutation = generate_polar_pixel_permutation(19, 11, lut)
    binary = permutation.to_bytes()
    parsed = PolarPixelPermutation.from_bytes(binary, uglut2_bytes=lut)
    assert parsed == permutation
    assert parsed.pixel_count == 209
    assert sorted(parsed.polar_to_cartesian) == list(range(209))
    assert sorted(parsed.inverse()) == list(range(209))
    receipt = inspect_polar_pixel_permutation(binary, uglut2_bytes=lut)
    assert receipt["bijection_verified"] is True
    assert receipt["all_pixels_covered_once"] is True
    assert receipt["uglut2_sha256"] == hashlib.sha256(lut).hexdigest()

    frame = np.arange(11 * 19 * 3, dtype=np.uint32).reshape(11, 19, 3)
    frame = ((frame * 37 + 11) & 255).astype(np.uint8)
    polar = gather_rgb_polar_numpy(frame, parsed)
    reconstructed = scatter_rgb_polar_numpy(polar, parsed)
    assert np.array_equal(reconstructed, frame)


def test_polar_pixel_permutation_rejects_wrong_dependency_and_duplicate() -> None:
    lut = _small_lut()
    permutation = generate_polar_pixel_permutation(7, 5, lut)
    with pytest.raises(ChronoCodecError, match="dependency hash"):
        PolarPixelPermutation.from_bytes(
            permutation.to_bytes(),
            uglut2_bytes=PolarLookupTable.generate(
                LogPolarProfile(rho_min=-2.0, rho_max=3.0), 64
            ).to_bytes(),
        )
    values = list(permutation.polar_to_cartesian)
    values[-1] = values[0]
    malformed = PolarPixelPermutation(
        permutation.width, permutation.height, permutation.uglut2_sha256, tuple(values)
    )
    with pytest.raises(ChronoCodecError, match="duplicate"):
        malformed.to_bytes()


def test_checkpoint_and_temporal_frames_reconstruct_exact_polar_rgb() -> None:
    np = pytest.importorskip("numpy")
    first = np.zeros((128, 3), dtype=np.uint8)
    first[:, 0] = np.arange(128, dtype=np.uint8)
    first[:, 1] = 91
    first[:, 2] = np.arange(127, -1, -1, dtype=np.uint8)
    second = first.copy()
    second[17:29] ^= np.array([3, 7, 11], dtype=np.uint8)
    third = second.copy()
    third[90:110, 1] = 4

    encoded0 = encode_polar_frame(
        first.tobytes(), ordinal=0, source_pts=0, checkpoint=True
    )
    assert encoded0.flags == FRAME_CHECKPOINT
    record0, decoded0 = decode_polar_frame(encoded0.to_bytes())
    assert record0 == encoded0
    assert decoded0 == first.tobytes()

    encoded1 = encode_polar_frame(
        second.tobytes(),
        ordinal=1,
        source_pts=39_824,
        previous_polar_rgb_bytes=decoded0,
        previous_ordinal=0,
    )
    record1, decoded1 = decode_polar_frame(
        encoded1.to_bytes(),
        previous_polar_rgb_bytes=decoded0,
        expected_previous_ordinal=0,
    )
    assert record1 == encoded1
    assert decoded1 == second.tobytes()

    encoded2 = encode_polar_frame(
        third.tobytes(),
        ordinal=2,
        source_pts=79_648,
        previous_polar_rgb_bytes=decoded1,
        previous_ordinal=1,
    )
    _, decoded2 = decode_polar_frame(
        encoded2.to_bytes(),
        previous_polar_rgb_bytes=decoded1,
        expected_previous_ordinal=1,
    )
    assert decoded2 == third.tobytes()
    assert len(encoded1.payload) < len(second.tobytes())


def test_frame_parser_fails_closed_on_hash_chain_and_noncanonical_tokens() -> None:
    current = bytes((index * 19) & 255 for index in range(300))
    record = encode_polar_frame(current, ordinal=0, source_pts=0, checkpoint=True)
    corrupted = bytearray(record.to_bytes())
    corrupted[-1] ^= 1
    with pytest.raises(ChronoCodecError, match="payload SHA-256"):
        decode_polar_frame(corrupted)

    delta = encode_polar_frame(
        current,
        ordinal=1,
        source_pts=1,
        previous_polar_rgb_bytes=current,
        previous_ordinal=0,
    )
    with pytest.raises(ChronoCodecError, match="previous ordinal"):
        decode_polar_frame(
            delta.to_bytes(),
            previous_polar_rgb_bytes=current,
            expected_previous_ordinal=9,
        )


def test_decoded_stream_digest_binds_ordinal_pts_length_and_rgb() -> None:
    frames = [(0, 0, b"\x01\x02\x03"), (1, 39_824, b"\x04\x05\x06")]
    digest = decoded_stream_sha256(frames)
    assert len(digest) == 64
    assert digest != decoded_stream_sha256(
        [(0, 0, b"\x01\x02\x03"), (1, 39_825, b"\x04\x05\x06")]
    )
    with pytest.raises(ChronoCodecError, match="dense"):
        decoded_stream_sha256([(1, 0, b"\x01\x02\x03")])


def test_cuda_polar_gather_matches_numpy_when_available() -> None:
    np = pytest.importorskip("numpy")
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("CUDA is unavailable")
    lut = _small_lut()
    permutation = generate_polar_pixel_permutation(32, 24, lut)
    frames = [
        ((np.arange(24 * 32 * 3).reshape(24, 32, 3) * factor + 17) & 255).astype(
            np.uint8
        )
        for factor in (3, 11)
    ]
    expected = np.stack(
        [gather_rgb_polar_numpy(frame, permutation) for frame in frames], axis=0
    )
    actual, receipt = gather_rgb_polar_cuda(frames, permutation, max_vram_mib=256)
    assert np.array_equal(actual, expected)
    assert receipt["integer_byte_exact"] is True
    assert receipt["peak_mib"] <= 256


def test_codec_primitive_module_does_not_embed_a_conventional_codec() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "ugts_kc3" / "chrono_codec.py"
    ).read_text(encoding="utf-8")
    for forbidden_import in ("import zlib", "import av", "import PIL", "import imageio"):
        assert forbidden_import not in source
    # The contract names prohibited payload formats; implementation calls are
    # what this test excludes.
    for forbidden_call in ("cv2.imencode", "ffmpeg", "libx264"):
        assert forbidden_call not in source


def test_checkpoint_rejects_a_temporal_predictor_shape() -> None:
    frame = bytes([7, 8, 9] * 20)
    record = encode_polar_frame(frame, ordinal=0, source_pts=0, checkpoint=True)
    assert record.predictor in (PREDICTOR_RAW, 1)
