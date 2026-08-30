import contextlib
import io
import json
from pathlib import Path
from unittest import mock

import pytest

from ugts_kc3.cli import _parser, main


def test_compile_ugtc4d_parser_defaults_match_authoring_profile() -> None:
    parsed = _parser().parse_args(
        ["compile-ugtc4d", "input.mp4", "output.ugtc4d"]
    )

    assert parsed.input == Path("input.mp4")
    assert parsed.output == Path("output.ugtc4d")
    assert parsed.receipt is None
    assert parsed.batch_frames == 16
    assert parsed.max_vram_mib == 4096


@pytest.mark.parametrize("option", ["--batch-frames", "--max-vram-mib"])
@pytest.mark.parametrize("value", ["0", "-1", "1.5"])
def test_compile_ugtc4d_parser_rejects_invalid_positive_counts(
    option: str,
    value: str,
) -> None:
    with contextlib.redirect_stderr(io.StringIO()):
        with pytest.raises(SystemExit):
            _parser().parse_args(
                ["compile-ugtc4d", "input.mp4", "output.ugtc4d", option, value]
            )


def test_compile_ugtc4d_dispatches_without_encoding_fixture() -> None:
    expected = {
        "schema": "ugtoms-chrono-lossless-authoring-receipt-0.2",
        "output": {"path": "output.ugtc4d", "bytes": 123, "sha256": "ab"},
    }
    with mock.patch(
        "ugts_kc3.chrono_compile.compile_video_to_ugtc4d",
        return_value=expected,
    ) as compile_codec:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(
                [
                    "compile-ugtc4d",
                    "input.mp4",
                    "output.ugtc4d",
                    "--receipt",
                    "receipt.json",
                    "--batch-frames",
                    "7",
                    "--max-vram-mib",
                    "3072",
                ]
            )

    assert result == 0
    compile_codec.assert_called_once_with(
        Path("input.mp4"),
        Path("output.ugtc4d"),
        receipt_path=Path("receipt.json"),
        batch_frames=7,
        max_vram_mib=3072,
    )
    assert json.loads(output.getvalue()) == expected


def test_verify_ugtc4d_defaults_to_strict_container_replay() -> None:
    expected = {"status": "PASS", "frames_verified": 2}
    with (
        mock.patch(
            "ugts_kc3.chrono_compile.verify_ugtc4d_file",
            return_value=expected,
        ) as verify_file,
        mock.patch(
            "ugts_kc3.chrono_compile.verify_ugtc4d_against_source"
        ) as verify_source,
    ):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["verify-ugtc4d", "sample.ugtc4d"])

    assert result == 0
    verify_file.assert_called_once_with(Path("sample.ugtc4d"))
    verify_source.assert_not_called()
    assert json.loads(output.getvalue()) == expected


def test_verify_ugtc4d_source_option_uses_independent_source_verifier() -> None:
    expected = {
        "status": "PASS",
        "source_verification": {"rgb24_and_pts_exact": True},
    }
    with (
        mock.patch("ugts_kc3.chrono_compile.verify_ugtc4d_file") as verify_file,
        mock.patch(
            "ugts_kc3.chrono_compile.verify_ugtc4d_against_source",
            return_value=expected,
        ) as verify_source,
    ):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(
                [
                    "verify-ugtc4d",
                    "sample.ugtc4d",
                    "--source-video",
                    "source.mp4",
                ]
            )

    assert result == 0
    verify_source.assert_called_once_with(
        Path("sample.ugtc4d"),
        Path("source.mp4"),
    )
    verify_file.assert_not_called()
    assert json.loads(output.getvalue()) == expected
