from __future__ import annotations

import unittest

from ugts_chess.constants import BLACK, WHITE
from ugts_chess.hashing import repetition_key
from ugts_chess.position import Position
from ugts_chess.rules import (
    apply_move,
    legal_moves,
    move_to_san,
    parse_uci_move,
    perft,
    position_status,
)


class MoveGenerationTests(unittest.TestCase):
    def test_01_initial_legal_move_count(self) -> None:
        self.assertEqual(len(legal_moves(Position.initial())), 20)

    def test_02_initial_perft_1_to_4(self) -> None:
        p = Position.initial()
        self.assertEqual([perft(p, d) for d in range(1, 5)], [20, 400, 8902, 197281])

    def test_03_kiwipete_perft(self) -> None:
        p = Position.from_fen("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1")
        self.assertEqual([perft(p, d) for d in range(1, 4)], [48, 2039, 97862])

    def test_04_position_3_perft(self) -> None:
        p = Position.from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1")
        self.assertEqual([perft(p, d) for d in range(1, 4)], [14, 191, 2812])

    def test_05_position_4_perft(self) -> None:
        p = Position.from_fen("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1")
        self.assertEqual([perft(p, d) for d in range(1, 4)], [6, 264, 9467])

    def test_06_position_5_perft(self) -> None:
        p = Position.from_fen("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8")
        self.assertEqual([perft(p, d) for d in range(1, 4)], [44, 1486, 62379])

    def test_07_position_6_perft(self) -> None:
        p = Position.from_fen("r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10")
        self.assertEqual([perft(p, d) for d in range(1, 4)], [46, 2079, 89890])

    def test_08_castling_generated(self) -> None:
        p = Position.from_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        moves = {m.uci() for m in legal_moves(p)}
        self.assertIn("e1g1", moves)
        self.assertIn("e1c1", moves)

    def test_09_castling_through_attack_rejected(self) -> None:
        p = Position.from_fen("r3k2r/8/8/8/2b5/8/8/R3K2R w KQkq - 0 1")
        moves = {m.uci() for m in legal_moves(p)}
        self.assertNotIn("e1g1", moves)  # bishop c4 attacks f1
        self.assertIn("e1c1", moves)

    def test_10_en_passant_generated(self) -> None:
        p = Position.from_fen("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        move = parse_uci_move(p, "e5d6")
        self.assertTrue(move.is_en_passant)
        child = apply_move(p, move)
        self.assertEqual(child.board[35], ".")  # d5 captured

    def test_11_en_passant_pin_guard(self) -> None:
        p = Position.from_fen("k3r3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        self.assertNotIn("e5d6", {m.uci() for m in legal_moves(p)})

    def test_12_promotions_are_four_distinct_moves(self) -> None:
        p = Position.from_fen("7k/P7/8/8/8/8/8/7K w - - 0 1")
        promotions = sorted(m.uci() for m in legal_moves(p) if m.from_sq == 48)
        self.assertEqual(promotions, ["a7a8b", "a7a8n", "a7a8q", "a7a8r"])

    def test_13_king_capture_not_generated(self) -> None:
        p = Position.from_fen("8/8/8/8/8/8/1Q6/k1K5 w - - 0 1", strict=False)
        self.assertNotIn("b2a1", {m.uci() for m in legal_moves(p)})

    def test_14_checkmate_status(self) -> None:
        p = Position.from_fen("k7/1Q6/2K5/8/8/8/8/8 b - - 0 1")
        status = position_status(p)
        self.assertTrue(status.terminal)
        self.assertEqual(status.code, "checkmate")
        self.assertEqual(status.winner, WHITE)

    def test_15_stalemate_status(self) -> None:
        p = Position.from_fen("k7/2Q5/2K5/8/8/8/8/8 b - - 0 1")
        status = position_status(p)
        self.assertEqual(status.code, "stalemate")

    def test_16_dead_position_kings_only(self) -> None:
        p = Position.from_fen("8/8/8/8/8/8/2k5/2K5 w - - 0 1", strict=False)
        # Adjacent kings are structurally parseable only with strict=False but illegal;
        # use a legal separation for the actual status check.
        p = Position.from_fen("8/8/8/8/8/2k5/8/2K5 w - - 0 1")
        self.assertEqual(position_status(p).code, "dead_position")

    def test_17_dead_position_bishop(self) -> None:
        p = Position.from_fen("8/8/8/8/8/2k5/8/2KB4 w - - 0 1")
        self.assertEqual(position_status(p).code, "dead_position")

    def test_18_fifty_move_claim(self) -> None:
        p = Position.from_fen("8/8/8/8/8/2k5/8/2KR4 w - - 100 51")
        status = position_status(p)
        self.assertTrue(status.claimable)
        self.assertEqual(status.code, "fifty_move_claim")

    def test_19_seventy_five_move_automatic(self) -> None:
        p = Position.from_fen("8/8/8/8/8/2k5/8/2KR4 w - - 150 76")
        self.assertEqual(position_status(p).code, "seventy_five_move")

    def test_20_threefold_repetition_claim(self) -> None:
        p = Position.from_fen("8/8/8/8/8/2k5/8/2KR4 w - - 0 1")
        key = repetition_key(p)
        status = position_status(p, history_keys=[key, key, key])
        self.assertEqual(status.code, "threefold_repetition")

    def test_21_san_castle(self) -> None:
        p = Position.from_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        self.assertEqual(move_to_san(p, parse_uci_move(p, "e1g1")), "O-O")

    def test_22_san_checkmate(self) -> None:
        p = Position.from_fen("8/8/8/8/8/8/8/k1KQ4 w - - 0 1")
        self.assertEqual(move_to_san(p, parse_uci_move(p, "d1a4")), "Qa4#")


if __name__ == "__main__":
    unittest.main()
