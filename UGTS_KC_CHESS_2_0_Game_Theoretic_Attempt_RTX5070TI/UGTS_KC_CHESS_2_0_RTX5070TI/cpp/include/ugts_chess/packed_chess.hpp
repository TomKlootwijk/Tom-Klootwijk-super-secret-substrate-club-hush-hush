#pragma once

#include <cstddef>
#include <cstdint>

#if defined(__CUDACC__)
#define UGTS_HD __host__ __device__
#define UGTS_D __device__
#else
#define UGTS_HD
#define UGTS_D
#endif

namespace ugts::chess {

constexpr int kWhite = 0;
constexpr int kBlack = 1;
constexpr int kMaxMoves = 256;
constexpr std::uint8_t kCastleWK = 1;
constexpr std::uint8_t kCastleWQ = 2;
constexpr std::uint8_t kCastleBK = 4;
constexpr std::uint8_t kCastleBQ = 8;

enum Piece : std::uint8_t {
    Empty = 0,
    WP = 1, WN = 2, WB = 3, WR = 4, WQ = 5, WK = 6,
    BP = 9, BN = 10, BB = 11, BR = 12, BQ = 13, BK = 14,
};

struct alignas(64) PackedPosition {
    std::uint64_t cells[4]{};
    std::uint64_t key_lo{};
    std::uint64_t key_hi{};
    std::uint32_t parent{};
    std::uint16_t fullmove{1};
    std::uint8_t turn{kWhite};
    std::uint8_t castling{};
    std::int8_t ep_square{-1};
    std::uint8_t halfmove{};
    std::uint8_t flags{};
    std::uint8_t reserved[5]{};
};
static_assert(sizeof(PackedPosition) == 64, "PackedPosition protocol must stay 64 bytes");

struct MoveList {
    std::uint16_t moves[kMaxMoves]{};
    std::uint16_t count{};
};

UGTS_HD constexpr int file_of(int square) noexcept { return square & 7; }
UGTS_HD constexpr int rank_of(int square) noexcept { return square >> 3; }
UGTS_HD constexpr bool inside(int file, int rank) noexcept {
    return file >= 0 && file < 8 && rank >= 0 && rank < 8;
}
UGTS_HD constexpr int make_square(int file, int rank) noexcept { return rank * 8 + file; }
UGTS_HD constexpr int opposite(int color) noexcept { return color ^ 1; }
UGTS_HD constexpr int piece_color(std::uint8_t piece) noexcept {
    return piece == Empty ? -1 : ((piece & 8U) ? kBlack : kWhite);
}
UGTS_HD constexpr int piece_type(std::uint8_t piece) noexcept { return piece & 7U; }
UGTS_HD constexpr bool is_king(std::uint8_t piece) noexcept { return piece_type(piece) == 6; }

UGTS_HD inline std::uint8_t piece_at(const PackedPosition& position, int square) noexcept {
    const int word = square >> 4;
    const int shift = (square & 15) * 4;
    return static_cast<std::uint8_t>((position.cells[word] >> shift) & 0xFULL);
}

UGTS_HD inline void set_piece(PackedPosition& position, int square, std::uint8_t piece) noexcept {
    const int word = square >> 4;
    const int shift = (square & 15) * 4;
    const std::uint64_t mask = 0xFULL << shift;
    position.cells[word] = (position.cells[word] & ~mask) | (static_cast<std::uint64_t>(piece & 0xF) << shift);
}

UGTS_HD constexpr std::uint16_t encode_move(int from, int to, int promotion = 0) noexcept {
    return static_cast<std::uint16_t>((from & 63) | ((to & 63) << 6) | ((promotion & 7) << 12));
}
UGTS_HD constexpr int move_from(std::uint16_t move) noexcept { return move & 63; }
UGTS_HD constexpr int move_to(std::uint16_t move) noexcept { return (move >> 6) & 63; }
UGTS_HD constexpr int move_promotion(std::uint16_t move) noexcept { return (move >> 12) & 7; }

UGTS_HD inline void append_move(MoveList& list, int from, int to, int promotion = 0) noexcept {
    if (list.count < kMaxMoves) {
        list.moves[list.count++] = encode_move(from, to, promotion);
    }
}

UGTS_HD inline int find_king(const PackedPosition& position, int color) noexcept {
    const std::uint8_t expected = static_cast<std::uint8_t>((color == kWhite) ? WK : BK);
    for (int square = 0; square < 64; ++square) {
        if (piece_at(position, square) == expected) {
            return square;
        }
    }
    return -1;
}

UGTS_HD inline bool is_square_attacked(const PackedPosition& position, int target, int by_color) noexcept {
    const int tf = file_of(target);
    const int tr = rank_of(target);

    // Pawn attacks.
    const int pawn_source_rank = tr + ((by_color == kWhite) ? -1 : 1);
    const std::uint8_t pawn = static_cast<std::uint8_t>((by_color == kWhite) ? WP : BP);
    for (int side_index = 0; side_index < 2; ++side_index) {
        const int df = side_index == 0 ? -1 : 1;
        const int f = tf + df;
        if (inside(f, pawn_source_rank) && piece_at(position, make_square(f, pawn_source_rank)) == pawn) {
            return true;
        }
    }

    constexpr int knight_offsets[8][2] = {
        {1, 2}, {2, 1}, {2, -1}, {1, -2}, {-1, -2}, {-2, -1}, {-2, 1}, {-1, 2}
    };
    const std::uint8_t knight = static_cast<std::uint8_t>((by_color == kWhite) ? WN : BN);
    for (const auto& offset : knight_offsets) {
        const int f = tf + offset[0];
        const int r = tr + offset[1];
        if (inside(f, r) && piece_at(position, make_square(f, r)) == knight) {
            return true;
        }
    }

    const std::uint8_t king = static_cast<std::uint8_t>((by_color == kWhite) ? WK : BK);
    for (int df = -1; df <= 1; ++df) {
        for (int dr = -1; dr <= 1; ++dr) {
            if (df == 0 && dr == 0) continue;
            const int f = tf + df;
            const int r = tr + dr;
            if (inside(f, r) && piece_at(position, make_square(f, r)) == king) {
                return true;
            }
        }
    }

    constexpr int directions[8][2] = {
        {1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}
    };
    for (int direction = 0; direction < 8; ++direction) {
        int f = tf + directions[direction][0];
        int r = tr + directions[direction][1];
        while (inside(f, r)) {
            const std::uint8_t piece = piece_at(position, make_square(f, r));
            if (piece != Empty) {
                if (piece_color(piece) == by_color) {
                    const int type = piece_type(piece);
                    const bool orthogonal = direction < 4;
                    if (type == 5 || (orthogonal && type == 4) || (!orthogonal && type == 3)) {
                        return true;
                    }
                }
                break;
            }
            f += directions[direction][0];
            r += directions[direction][1];
        }
    }
    return false;
}

UGTS_HD inline bool apply_move(PackedPosition& position, std::uint16_t move) noexcept {
    const int from = move_from(move);
    const int to = move_to(move);
    const int promotion = move_promotion(move);
    const std::uint8_t moving = piece_at(position, from);
    if (moving == Empty || piece_color(moving) != position.turn) return false;
    const std::uint8_t target = piece_at(position, to);
    if (target != Empty && (piece_color(target) == position.turn || is_king(target))) return false;

    const int mover = position.turn;
    const int moving_type = piece_type(moving);
    bool capture = target != Empty;
    const bool en_passant = moving_type == 1 && to == position.ep_square && target == Empty && file_of(from) != file_of(to);

    set_piece(position, from, Empty);
    if (en_passant) {
        const int captured_square = to + ((mover == kWhite) ? -8 : 8);
        const std::uint8_t expected = static_cast<std::uint8_t>((mover == kWhite) ? BP : WP);
        if (piece_at(position, captured_square) != expected) return false;
        set_piece(position, captured_square, Empty);
        capture = true;
    }

    std::uint8_t placed = moving;
    if (promotion != 0) {
        if (moving_type != 1 || promotion < 1 || promotion > 4) return false;
        const int target_rank = rank_of(to);
        if ((mover == kWhite && target_rank != 7) || (mover == kBlack && target_rank != 0)) return false;
        int promoted_type = 0;
        switch (promotion) {
            case 1: promoted_type = 2; break; // knight
            case 2: promoted_type = 3; break; // bishop
            case 3: promoted_type = 4; break; // rook
            case 4: promoted_type = 5; break; // queen
            default: return false;
        }
        placed = static_cast<std::uint8_t>(promoted_type | ((mover == kBlack) ? 8 : 0));
    }
    set_piece(position, to, placed);

    // Castling rook patch.
    if (moving_type == 6 && (to - from == 2 || from - to == 2)) {
        int rook_from = -1;
        int rook_to = -1;
        if (from == 4 && to == 6) { rook_from = 7; rook_to = 5; }
        else if (from == 4 && to == 2) { rook_from = 0; rook_to = 3; }
        else if (from == 60 && to == 62) { rook_from = 63; rook_to = 61; }
        else if (from == 60 && to == 58) { rook_from = 56; rook_to = 59; }
        else return false;
        const std::uint8_t rook = static_cast<std::uint8_t>((mover == kWhite) ? WR : BR);
        if (piece_at(position, rook_from) != rook || piece_at(position, rook_to) != Empty) return false;
        set_piece(position, rook_from, Empty);
        set_piece(position, rook_to, rook);
    }

    // Castling-right updates are part of state identity and must precede hashing.
    if (moving_type == 6) {
        position.castling &= static_cast<std::uint8_t>((mover == kWhite) ? ~(kCastleWK | kCastleWQ) : ~(kCastleBK | kCastleBQ));
    }
    if (moving_type == 4) {
        if (from == 0) position.castling &= static_cast<std::uint8_t>(~kCastleWQ);
        if (from == 7) position.castling &= static_cast<std::uint8_t>(~kCastleWK);
        if (from == 56) position.castling &= static_cast<std::uint8_t>(~kCastleBQ);
        if (from == 63) position.castling &= static_cast<std::uint8_t>(~kCastleBK);
    }
    if (target == WR) {
        if (to == 0) position.castling &= static_cast<std::uint8_t>(~kCastleWQ);
        if (to == 7) position.castling &= static_cast<std::uint8_t>(~kCastleWK);
    } else if (target == BR) {
        if (to == 56) position.castling &= static_cast<std::uint8_t>(~kCastleBQ);
        if (to == 63) position.castling &= static_cast<std::uint8_t>(~kCastleBK);
    }

    position.ep_square = -1;
    if (moving_type == 1 && (to - from == 16 || from - to == 16)) {
        position.ep_square = static_cast<std::int8_t>((from + to) / 2);
    }
    position.halfmove = static_cast<std::uint8_t>((moving_type == 1 || capture) ? 0 : (position.halfmove < 150 ? position.halfmove + 1 : 150));
    if (mover == kBlack && position.fullmove < 0xFFFFU) ++position.fullmove;
    position.turn = static_cast<std::uint8_t>(opposite(mover));
    return true;
}

UGTS_HD inline void generate_pseudo_moves(const PackedPosition& position, MoveList& output) noexcept {
    output.count = 0;
    const int side = position.turn;
    constexpr int knight_offsets[8][2] = {
        {1, 2}, {2, 1}, {2, -1}, {1, -2}, {-1, -2}, {-2, -1}, {-2, 1}, {-1, 2}
    };
    constexpr int king_offsets[8][2] = {
        {1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}, {-1, -1}, {0, -1}, {1, -1}
    };
    constexpr int directions[8][2] = {
        {1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}
    };

    for (int from = 0; from < 64; ++from) {
        const std::uint8_t piece = piece_at(position, from);
        if (piece == Empty || piece_color(piece) != side) continue;
        const int type = piece_type(piece);
        const int ff = file_of(from);
        const int fr = rank_of(from);

        if (type == 1) {
            const int step = (side == kWhite) ? 1 : -1;
            const int start_rank = (side == kWhite) ? 1 : 6;
            const int promotion_rank = (side == kWhite) ? 7 : 0;
            const int one_rank = fr + step;
            if (inside(ff, one_rank)) {
                const int one = make_square(ff, one_rank);
                if (piece_at(position, one) == Empty) {
                    if (one_rank == promotion_rank) {
                        for (int promotion = 1; promotion <= 4; ++promotion) append_move(output, from, one, promotion);
                    } else {
                        append_move(output, from, one);
                        if (fr == start_rank) {
                            const int two = make_square(ff, fr + 2 * step);
                            if (piece_at(position, two) == Empty) append_move(output, from, two);
                        }
                    }
                }
            }
            for (int side_index = 0; side_index < 2; ++side_index) {
                const int df = side_index == 0 ? -1 : 1;
                const int tf = ff + df;
                const int tr = fr + step;
                if (!inside(tf, tr)) continue;
                const int to = make_square(tf, tr);
                const std::uint8_t target = piece_at(position, to);
                const bool normal_capture = target != Empty && piece_color(target) == opposite(side) && !is_king(target);
                bool ep_capture = false;
                if (to == position.ep_square && target == Empty) {
                    const int captured_square = to + ((side == kWhite) ? -8 : 8);
                    const std::uint8_t expected = static_cast<std::uint8_t>((side == kWhite) ? BP : WP);
                    ep_capture = piece_at(position, captured_square) == expected;
                }
                if (!normal_capture && !ep_capture) continue;
                if (tr == promotion_rank) {
                    for (int promotion = 1; promotion <= 4; ++promotion) append_move(output, from, to, promotion);
                } else {
                    append_move(output, from, to);
                }
            }
            continue;
        }

        if (type == 2) {
            for (const auto& offset : knight_offsets) {
                const int tf = ff + offset[0];
                const int tr = fr + offset[1];
                if (!inside(tf, tr)) continue;
                const int to = make_square(tf, tr);
                const std::uint8_t target = piece_at(position, to);
                if (target == Empty || (piece_color(target) == opposite(side) && !is_king(target))) append_move(output, from, to);
            }
            continue;
        }

        if (type == 6) {
            for (const auto& offset : king_offsets) {
                const int tf = ff + offset[0];
                const int tr = fr + offset[1];
                if (!inside(tf, tr)) continue;
                const int to = make_square(tf, tr);
                const std::uint8_t target = piece_at(position, to);
                if (target == Empty || (piece_color(target) == opposite(side) && !is_king(target))) append_move(output, from, to);
            }
            const int enemy = opposite(side);
            if (side == kWhite && from == 4 && piece == WK && !is_square_attacked(position, 4, enemy)) {
                if ((position.castling & kCastleWK) && piece_at(position, 7) == WR && piece_at(position, 5) == Empty && piece_at(position, 6) == Empty &&
                    !is_square_attacked(position, 5, enemy) && !is_square_attacked(position, 6, enemy)) append_move(output, 4, 6);
                if ((position.castling & kCastleWQ) && piece_at(position, 0) == WR && piece_at(position, 1) == Empty && piece_at(position, 2) == Empty && piece_at(position, 3) == Empty &&
                    !is_square_attacked(position, 3, enemy) && !is_square_attacked(position, 2, enemy)) append_move(output, 4, 2);
            } else if (side == kBlack && from == 60 && piece == BK && !is_square_attacked(position, 60, enemy)) {
                if ((position.castling & kCastleBK) && piece_at(position, 63) == BR && piece_at(position, 61) == Empty && piece_at(position, 62) == Empty &&
                    !is_square_attacked(position, 61, enemy) && !is_square_attacked(position, 62, enemy)) append_move(output, 60, 62);
                if ((position.castling & kCastleBQ) && piece_at(position, 56) == BR && piece_at(position, 57) == Empty && piece_at(position, 58) == Empty && piece_at(position, 59) == Empty &&
                    !is_square_attacked(position, 59, enemy) && !is_square_attacked(position, 58, enemy)) append_move(output, 60, 58);
            }
            continue;
        }

        int start_direction = 0;
        int end_direction = 8;
        if (type == 3) start_direction = 4;
        if (type == 3) end_direction = 8;
        if (type == 4) { start_direction = 0; end_direction = 4; }
        if (type != 3 && type != 4 && type != 5) continue;
        for (int direction = start_direction; direction < end_direction; ++direction) {
            int tf = ff + directions[direction][0];
            int tr = fr + directions[direction][1];
            while (inside(tf, tr)) {
                const int to = make_square(tf, tr);
                const std::uint8_t target = piece_at(position, to);
                if (target == Empty) {
                    append_move(output, from, to);
                } else {
                    if (piece_color(target) == opposite(side) && !is_king(target)) append_move(output, from, to);
                    break;
                }
                tf += directions[direction][0];
                tr += directions[direction][1];
            }
        }
    }
}

UGTS_HD inline void generate_legal_moves(const PackedPosition& position, MoveList& output) noexcept {
    MoveList pseudo{};
    generate_pseudo_moves(position, pseudo);
    output.count = 0;
    const int mover = position.turn;
    for (std::uint16_t index = 0; index < pseudo.count; ++index) {
        PackedPosition child = position;
        if (!apply_move(child, pseudo.moves[index])) continue;
        const int king_square = find_king(child, mover);
        if (king_square < 0) continue;
        if (!is_square_attacked(child, king_square, child.turn)) {
            if (output.count < kMaxMoves) output.moves[output.count++] = pseudo.moves[index];
        }
    }
}

UGTS_HD inline std::uint64_t perft(const PackedPosition& position, int depth) noexcept {
    if (depth <= 0) return 1;
    MoveList moves{};
    generate_legal_moves(position, moves);
    if (depth == 1) return moves.count;
    std::uint64_t total = 0;
    for (std::uint16_t index = 0; index < moves.count; ++index) {
        PackedPosition child = position;
        if (apply_move(child, moves.moves[index])) total += perft(child, depth - 1);
    }
    return total;
}

}  // namespace ugts::chess
