"""Compact deterministic encodings for boards and move streams."""

from __future__ import annotations

from collections.abc import Iterable


def pack_board_2bit(board: bytes) -> bytes:
    """Pack four board points per byte (00 empty, 01 black, 10 white)."""
    if any(point not in (0, 1, 2) for point in board):
        raise ValueError("board contains invalid point value")
    out = bytearray((len(board) * 2 + 7) // 8)
    for index, point in enumerate(board):
        bit = index * 2
        out[bit // 8] |= point << (bit % 8)
    return bytes(out)


def unpack_board_2bit(data: bytes, points: int) -> bytes:
    if len(data) * 8 < points * 2:
        raise ValueError("packed board is too short")
    out = bytearray(points)
    for index in range(points):
        bit = index * 2
        value = (data[bit // 8] >> (bit % 8)) & 0b11
        if value == 0b11:
            raise ValueError("reserved 2-bit point value encountered")
        out[index] = value
    return bytes(out)


def encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("varint requires non-negative value")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


def decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ValueError("truncated varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
        if shift > 63:
            raise ValueError("varint is too large")


def pack_moves(moves: Iterable[int]) -> bytes:
    # Move -1 (pass) maps to zero; board points map to point+1.
    out = bytearray()
    for move in moves:
        if move < -1:
            raise ValueError("invalid move")
        out.extend(encode_varint(move + 1))
    return bytes(out)


def unpack_moves(data: bytes) -> list[int]:
    moves: list[int] = []
    offset = 0
    while offset < len(data):
        value, offset = decode_varint(data, offset)
        moves.append(value - 1)
    return moves
