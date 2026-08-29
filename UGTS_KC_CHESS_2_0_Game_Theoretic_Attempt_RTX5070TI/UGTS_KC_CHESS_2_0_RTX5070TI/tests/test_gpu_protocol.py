from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from ugts_chess.gpu_protocol import (
    INPUT_HEADER,
    MAX_MOVES,
    OUTPUT_HEADER,
    decode_move16,
    encode_move16,
    pack_position,
    read_move_batch,
    recommended_rtx5070ti_config,
)
from ugts_chess.position import Position


class GPUProtocolTests(unittest.TestCase):
    def test_01_move16_roundtrip(self) -> None:
        for move in ("e2e4", "a7a8q", "h2h1n"):
            self.assertEqual(decode_move16(encode_move16(move)), move)

    def test_02_position_record_is_exactly_64_bytes(self) -> None:
        self.assertEqual(len(pack_position(Position.initial())), 64)
        self.assertEqual(INPUT_HEADER.size, 64)
        self.assertEqual(OUTPUT_HEADER.size, 64)

    def test_03_output_batch_decoder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "moves.ugmv"
            moves = [encode_move16("e2e4"), encode_move16("d2d4")]
            header = OUTPUT_HEADER.pack(b"UGTSMV20", 1, 2, MAX_MOVES, 1, 0)
            payload = struct.pack("<H", 2) + struct.pack(f"<{MAX_MOVES}H", *(moves + [0] * (MAX_MOVES - 2)))
            path.write_bytes(header + payload)
            self.assertEqual(read_move_batch(path), [["e2e4", "d2d4"]])

    def test_04_rtx_budget_leaves_headroom(self) -> None:
        config = recommended_rtx5070ti_config()
        self.assertEqual(config["nominal_vram_mib"], 12288)
        self.assertEqual(config["solver_budget_mib"] + config["reserved_headroom_mib"], 12288)
        self.assertEqual(config["compile_architecture"], "120")


if __name__ == "__main__":
    unittest.main()
