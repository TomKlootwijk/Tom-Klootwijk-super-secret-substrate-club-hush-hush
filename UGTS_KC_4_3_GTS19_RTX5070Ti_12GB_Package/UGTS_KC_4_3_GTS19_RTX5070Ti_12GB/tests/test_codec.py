from __future__ import annotations

import unittest

from ugts_go19.codec import (
    decode_varint,
    encode_varint,
    pack_board_2bit,
    pack_moves,
    unpack_board_2bit,
    unpack_moves,
)


class CodecTests(unittest.TestCase):
    def test_19x19_board_is_91_bytes(self) -> None:
        board = bytes([0, 1, 2] * 120 + [0])
        self.assertEqual(len(board), 361)
        packed = pack_board_2bit(board)
        self.assertEqual(len(packed), 91)
        self.assertEqual(unpack_board_2bit(packed, 361), board)

    def test_varints_round_trip(self) -> None:
        for value in (0, 1, 127, 128, 16_384, 2**32):
            encoded = encode_varint(value)
            decoded, offset = decode_varint(encoded)
            self.assertEqual(decoded, value)
            self.assertEqual(offset, len(encoded))

    def test_move_stream_round_trip(self) -> None:
        moves = [-1, 0, 18, 180, 360, -1]
        self.assertEqual(unpack_moves(pack_moves(moves)), moves)


if __name__ == "__main__":
    unittest.main()
