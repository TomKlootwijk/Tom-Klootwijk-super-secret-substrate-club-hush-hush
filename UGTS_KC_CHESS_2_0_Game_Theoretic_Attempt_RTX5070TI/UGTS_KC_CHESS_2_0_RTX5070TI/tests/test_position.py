from __future__ import annotations

import unittest

from ugts_chess.constants import BLACK, WHITE, parse_square, square_name
from ugts_chess.hashing import compact_key64, repetition_key, state_sha256
from ugts_chess.position import Position, START_FEN


class PositionTests(unittest.TestCase):
    def test_01_start_roundtrip(self) -> None:
        self.assertEqual(Position.from_fen(START_FEN).to_fen(), START_FEN)

    def test_02_square_roundtrip(self) -> None:
        for name in ("a1", "e4", "h8", "b7"):
            self.assertEqual(square_name(parse_square(name)), name)

    def test_03_invalid_fen_field_count(self) -> None:
        with self.assertRaises(ValueError):
            Position.from_fen("8/8/8/8/8/8/8/K6k w - -")

    def test_04_invalid_rank_width(self) -> None:
        with self.assertRaises(ValueError):
            Position.from_fen("9/8/8/8/8/8/8/K6k w - - 0 1")

    def test_05_requires_two_kings(self) -> None:
        with self.assertRaises(ValueError):
            Position.from_fen("8/8/8/8/8/8/8/K7 w - - 0 1")

    def test_06_pawn_on_back_rank_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Position.from_fen("P6k/8/8/8/8/8/8/K7 w - - 0 1")

    def test_07_castling_right_conflict_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Position.from_fen("4k3/8/8/8/8/8/8/4K3 w K - 0 1")

    def test_08_en_passant_rank_conflict_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Position.from_fen("4k3/8/8/8/8/8/8/4K3 w - e3 0 1")

    def test_09_hash_is_stable(self) -> None:
        p = Position.initial()
        self.assertEqual(state_sha256(p), state_sha256(Position.from_fen(p.to_fen())))
        self.assertEqual(compact_key64(p), compact_key64(Position.from_fen(p.to_fen())))

    def test_10_hash_changes_with_turn(self) -> None:
        p = Position.initial()
        q = Position(p.board, BLACK, p.castling, p.ep_square, p.halfmove_clock, p.fullmove_number)
        self.assertNotEqual(state_sha256(p), state_sha256(q))
        self.assertNotEqual(repetition_key(p), repetition_key(q))

    def test_11_ascii_contains_coordinates(self) -> None:
        text = Position.initial().ascii()
        self.assertIn("8  r n b q k b n r", text)
        self.assertIn("a b c d e f g h", text)

    def test_12_state_record_counter_boundary(self) -> None:
        p = Position.initial()
        self.assertIn("halfmove_clock", p.state_record())
        self.assertNotIn("halfmove_clock", p.state_record(include_counters=False))


if __name__ == "__main__":
    unittest.main()
