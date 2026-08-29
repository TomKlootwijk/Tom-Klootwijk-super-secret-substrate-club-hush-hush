#include "ugts_chess/fen.hpp"

#include <algorithm>
#include <array>
#include <charconv>
#include <cctype>
#include <sstream>

namespace ugts::chess {
namespace {

std::uint8_t piece_from_char(char value) {
    switch (value) {
        case 'P': return WP; case 'N': return WN; case 'B': return WB;
        case 'R': return WR; case 'Q': return WQ; case 'K': return WK;
        case 'p': return BP; case 'n': return BN; case 'b': return BB;
        case 'r': return BR; case 'q': return BQ; case 'k': return BK;
        default: return Empty;
    }
}

char char_from_piece(std::uint8_t piece) {
    switch (piece) {
        case WP: return 'P'; case WN: return 'N'; case WB: return 'B';
        case WR: return 'R'; case WQ: return 'Q'; case WK: return 'K';
        case BP: return 'p'; case BN: return 'n'; case BB: return 'b';
        case BR: return 'r'; case BQ: return 'q'; case BK: return 'k';
        default: return '.';
    }
}

bool parse_int(std::string_view text, int minimum, int maximum, int& value) {
    value = 0;
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size() && value >= minimum && value <= maximum;
}

int parse_square(std::string_view text) {
    if (text.size() != 2 || text[0] < 'a' || text[0] > 'h' || text[1] < '1' || text[1] > '8') return -1;
    return (text[1] - '1') * 8 + (text[0] - 'a');
}

}  // namespace

bool parse_fen(std::string_view fen, PackedPosition& out, std::string& error) {
    out = PackedPosition{};
    std::array<std::string_view, 6> fields{};
    std::size_t start = 0;
    int field_count = 0;
    while (start < fen.size() && field_count < 6) {
        while (start < fen.size() && std::isspace(static_cast<unsigned char>(fen[start]))) ++start;
        if (start >= fen.size()) break;
        std::size_t end = start;
        while (end < fen.size() && !std::isspace(static_cast<unsigned char>(fen[end]))) ++end;
        fields[field_count++] = fen.substr(start, end - start);
        start = end;
    }
    while (start < fen.size() && std::isspace(static_cast<unsigned char>(fen[start]))) ++start;
    if (field_count != 6 || start != fen.size()) {
        error = "FEN must contain exactly six fields";
        return false;
    }

    int fen_rank = 7;
    int file = 0;
    int white_kings = 0;
    int black_kings = 0;
    for (char token : fields[0]) {
        if (token == '/') {
            if (file != 8 || fen_rank <= 0) { error = "invalid FEN rank width"; return false; }
            --fen_rank;
            file = 0;
            continue;
        }
        if (token >= '1' && token <= '8') {
            file += token - '0';
            if (file > 8) { error = "FEN rank overflow"; return false; }
            continue;
        }
        const std::uint8_t piece = piece_from_char(token);
        if (piece == Empty || file >= 8) { error = "invalid FEN piece token"; return false; }
        const int square = make_square(file, fen_rank);
        set_piece(out, square, piece);
        if (piece == WK) ++white_kings;
        if (piece == BK) ++black_kings;
        if (piece_type(piece) == 1 && (fen_rank == 0 || fen_rank == 7)) { error = "pawn on terminal rank"; return false; }
        ++file;
    }
    if (fen_rank != 0 || file != 8) { error = "FEN must contain eight complete ranks"; return false; }
    if (white_kings != 1 || black_kings != 1) { error = "FEN must contain exactly one king per side"; return false; }

    if (fields[1] == "w") out.turn = kWhite;
    else if (fields[1] == "b") out.turn = kBlack;
    else { error = "invalid FEN side"; return false; }

    out.castling = 0;
    if (fields[2] != "-") {
        for (char token : fields[2]) {
            std::uint8_t bit = 0;
            if (token == 'K') bit = kCastleWK;
            else if (token == 'Q') bit = kCastleWQ;
            else if (token == 'k') bit = kCastleBK;
            else if (token == 'q') bit = kCastleBQ;
            else { error = "invalid castling token"; return false; }
            if (out.castling & bit) { error = "duplicate castling token"; return false; }
            out.castling |= bit;
        }
    }
    if ((out.castling & kCastleWK) && (piece_at(out, 4) != WK || piece_at(out, 7) != WR)) { error = "white king-side right conflicts with board"; return false; }
    if ((out.castling & kCastleWQ) && (piece_at(out, 4) != WK || piece_at(out, 0) != WR)) { error = "white queen-side right conflicts with board"; return false; }
    if ((out.castling & kCastleBK) && (piece_at(out, 60) != BK || piece_at(out, 63) != BR)) { error = "black king-side right conflicts with board"; return false; }
    if ((out.castling & kCastleBQ) && (piece_at(out, 60) != BK || piece_at(out, 56) != BR)) { error = "black queen-side right conflicts with board"; return false; }

    out.ep_square = -1;
    if (fields[3] != "-") {
        const int square = parse_square(fields[3]);
        if (square < 0 || (rank_of(square) != 2 && rank_of(square) != 5)) { error = "invalid en-passant square"; return false; }
        if ((out.turn == kWhite && rank_of(square) != 5) || (out.turn == kBlack && rank_of(square) != 2)) {
            error = "en-passant rank conflicts with side";
            return false;
        }
        out.ep_square = static_cast<std::int8_t>(square);
    }

    int halfmove = 0;
    int fullmove = 0;
    if (!parse_int(fields[4], 0, 1000000, halfmove) || !parse_int(fields[5], 1, 65535, fullmove)) {
        error = "invalid FEN counters";
        return false;
    }
    out.halfmove = static_cast<std::uint8_t>(std::min(halfmove, 150));
    out.fullmove = static_cast<std::uint16_t>(fullmove);
    return true;
}

std::string to_fen(const PackedPosition& position) {
    std::ostringstream out;
    for (int rank = 7; rank >= 0; --rank) {
        int empty = 0;
        for (int file = 0; file < 8; ++file) {
            const std::uint8_t piece = piece_at(position, make_square(file, rank));
            if (piece == Empty) {
                ++empty;
            } else {
                if (empty) { out << empty; empty = 0; }
                out << char_from_piece(piece);
            }
        }
        if (empty) out << empty;
        if (rank) out << '/';
    }
    out << (position.turn == kWhite ? " w " : " b ");
    if (!position.castling) out << '-';
    else {
        if (position.castling & kCastleWK) out << 'K';
        if (position.castling & kCastleWQ) out << 'Q';
        if (position.castling & kCastleBK) out << 'k';
        if (position.castling & kCastleBQ) out << 'q';
    }
    out << ' ';
    if (position.ep_square < 0) out << '-';
    else out << static_cast<char>('a' + file_of(position.ep_square)) << static_cast<char>('1' + rank_of(position.ep_square));
    out << ' ' << static_cast<unsigned>(position.halfmove) << ' ' << position.fullmove;
    return out.str();
}

std::string move_to_uci(std::uint16_t move) {
    const int from = move_from(move);
    const int to = move_to(move);
    std::string result;
    result += static_cast<char>('a' + file_of(from));
    result += static_cast<char>('1' + rank_of(from));
    result += static_cast<char>('a' + file_of(to));
    result += static_cast<char>('1' + rank_of(to));
    switch (move_promotion(move)) {
        case 1: result += 'n'; break;
        case 2: result += 'b'; break;
        case 3: result += 'r'; break;
        case 4: result += 'q'; break;
        default: break;
    }
    return result;
}

bool parse_uci(std::string_view uci, std::uint16_t& move, std::string& error) {
    if (uci.size() != 4 && uci.size() != 5) { error = "UCI move must have 4 or 5 characters"; return false; }
    const int from = parse_square(uci.substr(0, 2));
    const int to = parse_square(uci.substr(2, 2));
    if (from < 0 || to < 0) { error = "invalid UCI square"; return false; }
    int promotion = 0;
    if (uci.size() == 5) {
        switch (uci[4]) {
            case 'n': promotion = 1; break;
            case 'b': promotion = 2; break;
            case 'r': promotion = 3; break;
            case 'q': promotion = 4; break;
            default: error = "invalid UCI promotion"; return false;
        }
    }
    move = encode_move(from, to, promotion);
    return true;
}

std::vector<std::string> legal_uci_moves(const PackedPosition& position) {
    MoveList moves{};
    generate_legal_moves(position, moves);
    std::vector<std::string> result;
    result.reserve(moves.count);
    for (std::uint16_t index = 0; index < moves.count; ++index) result.push_back(move_to_uci(moves.moves[index]));
    std::sort(result.begin(), result.end());
    return result;
}

}  // namespace ugts::chess
