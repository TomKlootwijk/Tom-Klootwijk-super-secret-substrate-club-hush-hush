from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ugts_chess import Position
from ugts_chess.gpu_protocol import (
    PACKED_POSITION,
    decode_move16,
    encode_move16,
    probe_cuda_device,
    recommended_rtx5070ti_config,
    run_batch,
)


class GPUProtocolTests(unittest.TestCase):
    def test_01_packed_record_is_64_bytes(self) -> None:
        self.assertEqual(PACKED_POSITION.size, 64)

    def test_02_move16_roundtrip(self) -> None:
        for move in ("e2e4", "a7a8q", "e1g1", "b7b8n"):
            self.assertEqual(decode_move16(encode_move16(move)), move)

    def test_03_profile_is_conservative(self) -> None:
        profile = recommended_rtx5070ti_config()
        self.assertEqual(profile["compile_architecture"], "120")
        self.assertLessEqual(profile["solver_budget_mib"], int(profile["nominal_vram_mib"] * 0.75))
        self.assertGreaterEqual(profile["reserved_headroom_mib"], 2048)
        self.assertIn("proposal", profile["correctness_boundary"].lower())

    @patch("ugts_chess.gpu_protocol.subprocess.run")
    def test_04_zero_exit_without_requested_output_cannot_reuse_stale_moves(self, mocked_run) -> None:
        mocked_run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            executable = root / "fake-gpu.exe"
            executable.write_bytes(b"fixed fake executable bytes")
            for stale_exists in (False, True):
                with self.subTest(stale_exists=stale_exists):
                    output = root / "batch" / "moves.ugmv"
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.unlink(missing_ok=True)
                    if stale_exists:
                        output.write_bytes(b"stale output that must not be read")
                    with self.assertRaisesRegex(RuntimeError, "without writing its requested output"):
                        run_batch(executable, [Position.initial()], output.parent)
                    self.assertFalse(output.exists())
                    command = mocked_run.call_args.args[0]
                    requested_output = Path(command[command.index("--output") + 1])
                    self.assertNotEqual(requested_output, output)
                    self.assertFalse(requested_output.exists())

    @patch("ugts_chess.gpu_protocol.subprocess.run")
    def test_05_device_probe_is_binary_bound_but_explicitly_self_reported(self, mocked_run) -> None:
        payload = (
            '{"cuda_compiled":true,"device_available":true,"device_index":0,'
            '"name":"Test CUDA Device","compute_capability":"12.0",'
            '"total_memory_bytes":1024,"free_memory_bytes":512,"multiprocessors":1,'
            '"warp_size":32,"max_threads_per_block":1024,"error":""}'
        )
        mocked_run.return_value = subprocess.CompletedProcess([], 0, stdout=payload, stderr="")
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "fake-gpu.exe"
            executable.write_bytes(b"fixed fake executable bytes")
            result = probe_cuda_device(executable)

        self.assertTrue(result["valid"])
        self.assertEqual(result["validation_failures"], [])
        self.assertEqual(result["payload"]["name"], "Test CUDA Device")
        self.assertRegex(str(result["executable"]["sha256"]), r"^[0-9a-f]{64}$")
        self.assertEqual(result["claim_source"], "same_executable_self_report")
        self.assertFalse(result["independent_hardware_attestation"])

    @unittest.skipUnless(os.environ.get("UGTS_GPU_HOST_EXE"), "host GPU-protocol executable not provided")
    def test_06_host_batch_matches_python_oracle(self) -> None:
        executable = Path(os.environ["UGTS_GPU_HOST_EXE"])
        positions = [
            Position.initial(),
            Position.from_fen("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"),
            Position.from_fen("8/8/8/8/8/k7/8/1QK5 w - - 0 1"),
            Position.from_fen("8/8/8/8/8/8/R3k3/K7 w - - 99 1"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            result = run_batch(executable, positions, temp)
        self.assertEqual(result["mismatches"], [])
        self.assertEqual(result["positions"], len(positions))
        self.assertGreater(result["verified_move_count"], 0)
        self.assertRegex(str(result["input_sha256"]), r"^[0-9a-f]{64}$")
        self.assertRegex(str(result["output_sha256"]), r"^[0-9a-f]{64}$")
        self.assertRegex(str(result["output_semantic_payload_sha256"]), r"^[0-9a-f]{64}$")
        self.assertRegex(str(result["executable_sha256"]), r"^[0-9a-f]{64}$")
        self.assertIn(result["output_backend_flag"], (0, 1))
        self.assertEqual(result["output"]["sha256"], result["output_sha256"])
        self.assertEqual(
            result["output"]["semantic_payload_sha256"],
            result["output_semantic_payload_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
