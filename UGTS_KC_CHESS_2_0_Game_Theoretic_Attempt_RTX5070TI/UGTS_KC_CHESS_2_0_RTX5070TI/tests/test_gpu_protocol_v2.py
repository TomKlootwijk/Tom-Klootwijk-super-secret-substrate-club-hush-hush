from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from ugts_chess import Position
from ugts_chess.gpu_protocol import (
    PACKED_POSITION,
    decode_move16,
    encode_move16,
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

    @unittest.skipUnless(os.environ.get("UGTS_GPU_HOST_EXE"), "host GPU-protocol executable not provided")
    def test_04_host_batch_matches_python_oracle(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
