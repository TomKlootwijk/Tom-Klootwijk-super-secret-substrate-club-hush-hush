from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts.benchmark_rtx5070ti import (
    BenchmarkError,
    _create_unique_input_artifact,
    _file_identity,
    _publish_report_atomically,
    _run_expansion,
    main,
    require_stable_executable_identity,
    require_stable_input_identity,
    validate_rtx5070ti_device_info,
)
from ugts_chess.position import Position


def device_payload(
    *,
    name: str = "NVIDIA GeForce RTX 5070 Ti Laptop GPU",
    compute_capability: str = "12.0",
    device_index: int = 0,
) -> dict[str, object]:
    return {
        "cuda_compiled": True,
        "device_available": True,
        "device_index": device_index,
        "name": name,
        "compute_capability": compute_capability,
        "total_memory_bytes": 12_820_480_000,
        "free_memory_bytes": 10_000_000_000,
        "multiprocessors": 46,
        "warp_size": 32,
        "max_threads_per_block": 1024,
        "error": "",
    }


class RTX5070TiBenchmarkDeviceValidationTests(unittest.TestCase):
    def test_01_accepts_desktop_and_laptop_target_names(self) -> None:
        for name in (
            "NVIDIA GeForce RTX 5070 Ti",
            "NVIDIA GeForce RTX 5070 Ti GPU",
            "NVIDIA GeForce RTX 5070 Ti Laptop GPU",
        ):
            with self.subTest(name=name):
                result = validate_rtx5070ti_device_info(
                    device_payload(name=name),
                    expected_device_index=0,
                )
                self.assertTrue(result["valid"])
                self.assertEqual(result["failures"], [])
                self.assertTrue(result["checks"]["device_name_matches_rtx5070ti"])
                self.assertTrue(result["checks"]["compute_capability_matches"])
                self.assertFalse(result["independent_hardware_attestation"])

    def test_02_rejects_other_or_lookalike_gpu_names(self) -> None:
        for name in (
            "NVIDIA GeForce RTX 4090",
            "NVIDIA GeForce RTX 5070",
            "NVIDIA GeForce RTX 5070 Ti SUPER",
            "Fake NVIDIA GeForce RTX 5070 Ti Laptop GPU",
        ):
            with self.subTest(name=name):
                result = validate_rtx5070ti_device_info(
                    device_payload(name=name),
                    expected_device_index=0,
                )
                self.assertFalse(result["valid"])
                self.assertIn("device_name_not_rtx5070ti", result["failures"])

    def test_03_rejects_wrong_compute_capability_and_device_index(self) -> None:
        result = validate_rtx5070ti_device_info(
            device_payload(compute_capability="8.9", device_index=1),
            expected_device_index=0,
        )
        self.assertFalse(result["valid"])
        self.assertIn("compute_capability_not_12_0", result["failures"])
        self.assertIn("device_index_mismatch", result["failures"])
        self.assertEqual(result["expected_compute_capability"], "12.0")

    def test_04_rejects_unavailable_or_malformed_device_claim(self) -> None:
        unavailable = device_payload()
        unavailable["device_available"] = False
        unavailable["error"] = "requested CUDA device is unavailable"
        result = validate_rtx5070ti_device_info(unavailable, expected_device_index=0)
        self.assertFalse(result["valid"])
        self.assertIn("cuda_device_unavailable", result["failures"])
        self.assertIn("device_info_error_present", result["failures"])

        malformed = validate_rtx5070ti_device_info(None, expected_device_index=0)
        self.assertFalse(malformed["valid"])
        self.assertIn("device_info_not_object", malformed["failures"])

    def test_05_rejects_executable_identity_change(self) -> None:
        initial = {"path": "gpu.exe", "sha256": "1" * 64, "size_bytes": 100}
        require_stable_executable_identity(initial, dict(initial))

        changed = {**initial, "sha256": "2" * 64}
        with self.assertRaisesRegex(BenchmarkError, "executable identity changed"):
            require_stable_executable_identity(initial, changed)

    @patch("scripts.benchmark_rtx5070ti.benchmark")
    def test_06_cli_scopes_success_to_parity_without_attestation(self, mocked_benchmark) -> None:
        mocked_benchmark.return_value = {
            "parity": {"semantic_payload_identical": True},
            "input": {"sha256": "1" * 64},
            "executable": {"sha256": "2" * 64},
            "throughput_at_native_p50": {"cuda_positions_per_second": 1.0},
        }
        stream = io.StringIO()
        with redirect_stdout(stream):
            exit_code = main(["--output-dir", str(Path("unused-output")), "--positions", "1"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stream.getvalue())
        self.assertTrue(payload["parity_passed"])
        self.assertNotIn("qualified", payload)
        self.assertFalse(payload["gpu_execution_independently_attested"])

    def test_07_concurrent_runs_create_distinct_immutable_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            output_dir = Path(temp_name)
            workers = 4
            barrier = threading.Barrier(workers)

            def create_input() -> tuple[Path, dict[str, object]]:
                barrier.wait(timeout=5)
                return _create_unique_input_artifact(output_dir, [Position.initial()])

            with ThreadPoolExecutor(max_workers=workers) as executor:
                results = list(executor.map(lambda _: create_input(), range(workers)))

            paths = [path for path, _meta in results]
            self.assertEqual(len(set(paths)), workers)
            self.assertTrue(all(path.is_file() for path in paths))
            self.assertEqual(len({meta["sha256"] for _path, meta in results}), 1)
            self.assertTrue(all(meta["unique_per_invocation"] for _path, meta in results))
            self.assertTrue(all(not meta["reused_existing_exact_file"] for _path, meta in results))

    def test_08_mutation_during_native_run_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            output_dir = Path(temp_name)
            input_path, _meta = _create_unique_input_artifact(output_dir, [Position.initial()])
            identity = _file_identity(input_path)

            def mutate_input(_command: object) -> subprocess.CompletedProcess[str]:
                raw = bytearray(input_path.read_bytes())
                raw[-1] ^= 1
                input_path.write_bytes(raw)
                return subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=(
                        '{"backend":"cuda","positions":1,"moves":20,'
                        '"seconds":0.001,"cuda_fallback_reason":""}'
                    ),
                    stderr="",
                )

            with patch("scripts.benchmark_rtx5070ti._run_checked", side_effect=mutate_input):
                with self.assertRaisesRegex(BenchmarkError, "input identity changed"):
                    _run_expansion(
                        Path("gpu.exe"),
                        input_path,
                        output_dir / "moves.ugmv",
                        backend="cuda",
                        device=0,
                        expected_positions=1,
                        expected_input_identity=identity,
                    )

    def test_09_atomic_publication_rejects_concurrent_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            report_path = Path(temp_name) / "benchmark-1.json"
            barrier = threading.Barrier(2)

            def publish(marker: int) -> tuple[str, int]:
                barrier.wait(timeout=5)
                try:
                    _publish_report_atomically(report_path, {"marker": marker}, force=False)
                except BenchmarkError:
                    return "rejected", marker
                return "published", marker

            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(publish, (1, 2)))

            self.assertEqual([status for status, _marker in outcomes].count("published"), 1)
            self.assertEqual([status for status, _marker in outcomes].count("rejected"), 1)
            published_marker = next(marker for status, marker in outcomes if status == "published")
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), {"marker": published_marker})
            self.assertEqual(list(report_path.parent.glob("*.tmp")), [])

    def test_10_prepublication_input_mutation_prevents_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            output_dir = Path(temp_name)
            input_path, _meta = _create_unique_input_artifact(output_dir, [Position.initial()])
            identity = _file_identity(input_path)
            report_path = output_dir / "benchmark-1.json"

            def mutate_then_check() -> None:
                raw = bytearray(input_path.read_bytes())
                raw[-1] ^= 1
                input_path.write_bytes(raw)
                require_stable_input_identity(identity, input_path)

            with self.assertRaisesRegex(BenchmarkError, "input identity changed"):
                _publish_report_atomically(
                    report_path,
                    {"schema": "ugts-chess-rtx-batch-benchmark-v4"},
                    force=False,
                    pre_publish_check=mutate_then_check,
                )
            self.assertFalse(report_path.exists())
            self.assertEqual(list(output_dir.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
