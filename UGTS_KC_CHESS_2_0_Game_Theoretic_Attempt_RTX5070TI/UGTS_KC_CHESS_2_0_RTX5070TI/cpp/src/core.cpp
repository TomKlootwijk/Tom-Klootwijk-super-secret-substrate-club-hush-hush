#include "ugts_chess2/core.hpp"
#include "ugts_chess2/sha256.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <charconv>
#include <limits>
#include <sstream>
#include <stdexcept>

namespace ugts::chess2 {
namespace {
constexpr char EMPTY = '.';
constexpr std::string_view PIECES = "PNBRQKpnbrqk";
constexpr std::array<char, 4> PROMOTIONS = {'Q', 'R', 'B', 'N'};
constexpr std::array<std::pair<int, int>, 8> KNIGHT_DELTAS = {{{1, 2}, {2, 1}, {2, -1}, {1, -2}, {-1, -2}, {-2, -1}, {-2, 1}, {-1, 2}}};
constexpr std::array<std::pair<int, int>, 8> KING_DELTAS = {{{1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}, {-1, -1}, {0, -1}, {1, -1}}};
constexpr std::array<std::pair<int, int>, 4> BISHOP_DIRS = {{{1, 1}, {1, -1}, {-1, 1}, {-1, -1}}};
constexpr std::array<std::pair<int, int>, 4> ROOK_DIRS = {{{1, 0}, {-1, 0}, {0, 1}, {0, -1}}};
constexpr std::array<std::pair<int, int>, 8> QUEEN_DIRS = {{{1, 1}, {1, -1}, {-1, 1}, {-1, -1}, {1, 0}, {-1, 0}, {0, 1}, {0, -1}}};

bool inside(int file, int rank) noexcept { return file >= 0 && file < 8 && rank >= 0 && rank < 8; }
bool valid_piece(char p) noexcept { return p == EMPTY || PIECES.find(p) != std::string_view::npos; }

std::vector<std::string_view> split_ws(std::string_view text) {
    std::vector<std::string_view> out;
    std::size_t i = 0;
    while (i < text.size()) {
        while (i < text.size() && std::isspace(static_cast<unsigned char>(text[i]))) ++i;
        if (i >= text.size()) break;
        std::size_t j = i;
        while (j < text.size() && !std::isspace(static_cast<unsigned char>(text[j]))) ++j;
        out.push_back(text.substr(i, j - i));
        i = j;
    }
    return out;
}

int parse_nonnegative(std::string_view token, const char* label) {
    int value = 0;
    const auto [ptr, ec] = std::from_chars(token.data(), token.data() + token.size(), value);
    if (ec != std::errc{} || ptr != token.data() + token.size() || value < 0) {
        throw std::invalid_argument(std::string(label) + " must be a non-negative integer");
    }
    return value;
}

void add_pawn_moves(const Position& position, int sq, char piece, std::vector<Move>& out) {
    const auto color_opt = piece_color(piece);
    if (!color_opt) return;
    const Color color = *color_opt;
    const int file = file_of(sq);
    const int rank = rank_of(sq);
    const int direction = color == Color::White ? 1 : -1;
    const int step = direction * 8;
    const int start_rank = color == Color::White ? 1 : 6;
    const int promotion_from_rank = color == Color::White ? 6 : 1;

    const int one = sq + step;
    if (one >= 0 && one < 64 && position.board[one] == EMPTY) {
        if (rank == promotion_from_rank) {
            for (char promotion : PROMOTIONS) out.push_back(Move{static_cast<std::uint8_t>(sq), static_cast<std::uint8_t>(one), promotion, MOVE_PROMOTION});
        } else {
            out.push_back(Move{static_cast<std::uint8_t>(sq), static_cast<std::uint8_t>(one), '\0', 0});
            const int two = sq + 2 * step;
            if (rank == start_rank && position.board[two] == EMPTY) {
                out.push_back(Move{static_cast<std::uint8_t>(sq), static_cast<std::uint8_t>(two), '\0', MOVE_DOUBLE_PAWN});
            }
        }
    }

    const int target_rank = rank + direction;
    if (target_rank < 0 || target_rank >= 8) return;
    for (int df : {-1, 1}) {
        const int target_file = file + df;
        if (target_file < 0 || target_file >= 8) continue;
        const int target = target_rank * 8 + target_file;
        const char occupant = position.board[target];
        if (occupant != EMPTY && piece_color(occupant) == std::optional<Color>(opposite(color)) && piece_type(occupant) != 'K') {
            std::uint8_t flags = MOVE_CAPTURE;
            if (rank == promotion_from_rank) {
                flags |= MOVE_PROMOTION;
                for (char promotion : PROMOTIONS) out.push_back(Move{static_cast<std::uint8_t>(sq), static_cast<std::uint8_t>(target), promotion, flags});
            } else {
                out.push_back(Move{static_cast<std::uint8_t>(sq), static_cast<std::uint8_t>(target), '\0', flags});
            }
        } else if (target == position.ep_square) {
            const int captured_sq = target - step;
            const char expected = color == Color::White ? 'p' : 'P';
            if (captured_sq >= 0 && captured_sq < 64 && position.board[captured_sq] == expected) {
                out.push_back(Move{static_cast<std::uint8_t>(sq), static_cast<std::uint8_t>(target), '\0', static_cast<std::uint8_t>(MOVE_CAPTURE | MOVE_EN_PASSANT)});
            }
        }
    }
}

template <std::size_t N>
void add_leaper_moves(const Position& position, int sq, char piece, const std::array<std::pair<int, int>, N>& deltas, std::vector<Move>& out) {
    const auto color_opt = piece_color(piece);
    if (!color_opt) return;
    const Color color = *color_opt;
    const int file = file_of(sq);
    const int rank = rank_of(sq);
    for (const auto [df, dr] : deltas) {
        const int f = file + df;
        const int r = rank + dr;
        if (!inside(f, r)) continue;
        const int target = r * 8 + f;
        const char occupant = position.board[target];
        if (occupant == EMPTY) out.push_back(Move{static_cast<std::uint8_t>(sq), static_cast<std::uint8_t>(target), '\0', 0});
        else if (piece_color(occupant) == std::optional<Color>(opposite(color)) && piece_type(occupant) != 'K') {
            out.push_back(Move{static_cast<std::uint8_t>(sq), static_cast<std::uint8_t>(target), '\0', MOVE_CAPTURE});
        }
    }
}

template <std::size_t N>
void add_slider_moves(const Position& position, int sq, char piece, const std::array<std::pair<int, int>, N>& dirs, std::vector<Move>& out) {
    const auto color_opt = piece_color(piece);
    if (!color_opt) return;
    const Color color = *color_opt;
    const int file = file_of(sq);
    const int rank = rank_of(sq);
    for (const auto [df, dr] : dirs) {
        int f = file + df;
        int r = rank + dr;
        while (inside(f, r)) {
            const int target = r * 8 + f;
            const char occupant = position.board[target];
            if (occupant == EMPTY) out.push_back(Move{static_cast<std::uint8_t>(sq), static_cast<std::uint8_t>(target), '\0', 0});
            else {
                if (piece_color(occupant) == std::optional<Color>(opposite(color)) && piece_type(occupant) != 'K') {
                    out.push_back(Move{static_cast<std::uint8_t>(sq), static_cast<std::uint8_t>(target), '\0', MOVE_CAPTURE});
                }
                break;
            }
            f += df;
            r += dr;
        }
    }
}

void add_castling(const Position& position, int sq, char piece, std::vector<Move>& out) {
    const auto color_opt = piece_color(piece);
    if (!color_opt) return;
    const Color color = *color_opt;
    const Color enemy = opposite(color);
    const auto& b = position.board;
    if (color == Color::White && sq == 4 && piece == 'K') {
        if ((position.castling & CASTLE_WK) && b[5] == EMPTY && b[6] == EMPTY && b[7] == 'R' &&
            !is_square_attacked(position, 4, enemy) && !is_square_attacked(position, 5, enemy) && !is_square_attacked(position, 6, enemy)) {
            out.push_back(Move{4, 6, '\0', MOVE_CASTLE});
        }
        if ((position.castling & CASTLE_WQ) && b[1] == EMPTY && b[2] == EMPTY && b[3] == EMPTY && b[0] == 'R' &&
            !is_square_attacked(position, 4, enemy) && !is_square_attacked(position, 3, enemy) && !is_square_attacked(position, 2, enemy)) {
            out.push_back(Move{4, 2, '\0', MOVE_CASTLE});
        }
    } else if (color == Color::Black && sq == 60 && piece == 'k') {
        if ((position.castling & CASTLE_BK) && b[61] == EMPTY && b[62] == EMPTY && b[63] == 'r' &&
            !is_square_attacked(position, 60, enemy) && !is_square_attacked(position, 61, enemy) && !is_square_attacked(position, 62, enemy)) {
            out.push_back(Move{60, 62, '\0', MOVE_CASTLE});
        }
        if ((position.castling & CASTLE_BQ) && b[57] == EMPTY && b[58] == EMPTY && b[59] == EMPTY && b[56] == 'r' &&
            !is_square_attacked(position, 60, enemy) && !is_square_attacked(position, 59, enemy) && !is_square_attacked(position, 58, enemy)) {
            out.push_back(Move{60, 58, '\0', MOVE_CASTLE});
        }
    }
}

std::vector<int> ep_capture_sources(const Position& position) {
    std::vector<int> sources;
    if (position.ep_square < 0) return sources;
    const int ep = position.ep_square;
    const int file = file_of(ep);
    const int rank = rank_of(ep);
    const int source_rank = position.turn == Color::White ? rank - 1 : rank + 1;
    const char pawn = position.turn == Color::White ? 'P' : 'p';
    for (int sf : {file - 1, file + 1}) {
        if (inside(sf, source_rank)) {
            const int sq = source_rank * 8 + sf;
            if (position.board[sq] == pawn) sources.push_back(sq);
        }
    }
    return sources;
}
}  // namespace

int file_of(int sq) noexcept { return sq & 7; }
int rank_of(int sq) noexcept { return sq >> 3; }

std::string square_name(int sq) {
    if (sq < 0 || sq >= 64) throw std::out_of_range("square out of range");
    std::string out(2, ' ');
    out[0] = static_cast<char>('a' + file_of(sq));
    out[1] = static_cast<char>('1' + rank_of(sq));
    return out;
}

int parse_square(std::string_view name) {
    if (name.size() != 2 || name[0] < 'a' || name[0] > 'h' || name[1] < '1' || name[1] > '8') throw std::invalid_argument("invalid square name");
    return (name[1] - '1') * 8 + (name[0] - 'a');
}

std::optional<Color> piece_color(char piece) noexcept {
    if (piece >= 'A' && piece <= 'Z' && PIECES.find(piece) != std::string_view::npos) return Color::White;
    if (piece >= 'a' && piece <= 'z' && PIECES.find(piece) != std::string_view::npos) return Color::Black;
    return std::nullopt;
}

char piece_type(char piece) noexcept { return static_cast<char>(std::toupper(static_cast<unsigned char>(piece))); }

std::string Move::uci() const {
    std::string out = square_name(from) + square_name(to);
    if (promotion != '\0') out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(promotion))));
    return out;
}

Position Position::initial() { return from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"); }

Position Position::from_fen(std::string_view fen, bool strict) {
    const auto fields = split_ws(fen);
    if (fields.size() != 6) throw std::invalid_argument("FEN must contain exactly six fields");
    Position p;
    p.board.fill(EMPTY);
    std::array<std::string_view, 8> rows{};
    std::size_t row_count = 0;
    std::size_t start = 0;
    for (std::size_t i = 0; i <= fields[0].size(); ++i) {
        if (i == fields[0].size() || fields[0][i] == '/') {
            if (row_count >= 8) throw std::invalid_argument("FEN placement must contain eight ranks");
            rows[row_count++] = fields[0].substr(start, i - start);
            start = i + 1;
        }
    }
    if (row_count != 8) throw std::invalid_argument("FEN placement must contain eight ranks");
    for (std::size_t fen_rank = 0; fen_rank < 8; ++fen_rank) {
        const int rank = 7 - static_cast<int>(fen_rank);
        int file = 0;
        for (char ch : rows[fen_rank]) {
            if (ch >= '1' && ch <= '8') file += ch - '0';
            else if (PIECES.find(ch) != std::string_view::npos) {
                if (file >= 8) throw std::invalid_argument("FEN rank overflows eight files");
                p.board[rank * 8 + file] = ch;
                ++file;
            } else throw std::invalid_argument("invalid FEN placement token");
        }
        if (file != 8) throw std::invalid_argument("FEN rank does not expand to eight files");
    }
    if (fields[1] == "w") p.turn = Color::White;
    else if (fields[1] == "b") p.turn = Color::Black;
    else throw std::invalid_argument("FEN side to move must be w or b");
    p.castling = 0;
    if (fields[2] != "-") {
        std::array<bool, 256> seen{};
        for (char ch : fields[2]) {
            const auto idx = static_cast<unsigned char>(ch);
            if (seen[idx]) throw std::invalid_argument("duplicate castling right");
            seen[idx] = true;
            switch (ch) {
                case 'K': p.castling |= CASTLE_WK; break;
                case 'Q': p.castling |= CASTLE_WQ; break;
                case 'k': p.castling |= CASTLE_BK; break;
                case 'q': p.castling |= CASTLE_BQ; break;
                default: throw std::invalid_argument("invalid castling rights");
            }
        }
    }
    p.ep_square = fields[3] == "-" ? -1 : static_cast<std::int8_t>(parse_square(fields[3]));
    const int half = parse_nonnegative(fields[4], "halfmove clock");
    const int full = parse_nonnegative(fields[5], "fullmove number");
    if (half > std::numeric_limits<std::uint16_t>::max()) throw std::invalid_argument("halfmove clock too large");
    if (full < 1 || full > std::numeric_limits<std::uint16_t>::max()) throw std::invalid_argument("fullmove number out of range");
    p.halfmove_clock = static_cast<std::uint16_t>(half);
    p.fullmove_number = static_cast<std::uint16_t>(full);
    if (strict) p.validate_structure();
    return p;
}

void Position::validate_structure() const {
    int wk = 0, bk = 0;
    for (int sq = 0; sq < 64; ++sq) {
        const char piece = board[sq];
        if (!valid_piece(piece)) throw std::invalid_argument("invalid board piece");
        if (piece == 'K') ++wk;
        if (piece == 'k') ++bk;
        if (piece_type(piece) == 'P' && (rank_of(sq) == 0 || rank_of(sq) == 7)) throw std::invalid_argument("pawn on first or eighth rank");
    }
    if (wk != 1 || bk != 1) throw std::invalid_argument("position must contain exactly one king per side");
    if ((castling & CASTLE_WK) && (board[4] != 'K' || board[7] != 'R')) throw std::invalid_argument("white king-side castling right conflicts with board");
    if ((castling & CASTLE_WQ) && (board[4] != 'K' || board[0] != 'R')) throw std::invalid_argument("white queen-side castling right conflicts with board");
    if ((castling & CASTLE_BK) && (board[60] != 'k' || board[63] != 'r')) throw std::invalid_argument("black king-side castling right conflicts with board");
    if ((castling & CASTLE_BQ) && (board[60] != 'k' || board[56] != 'r')) throw std::invalid_argument("black queen-side castling right conflicts with board");
    if (ep_square >= 0) {
        const int expected_rank = turn == Color::White ? 5 : 2;
        if (rank_of(ep_square) != expected_rank) throw std::invalid_argument("en-passant target rank conflicts with side to move");
    }
}

int Position::king_square(Color c) const {
    const char king = c == Color::White ? 'K' : 'k';
    for (int i = 0; i < 64; ++i) if (board[i] == king) return i;
    throw std::invalid_argument("missing king");
}

std::string Position::to_fen() const {
    std::ostringstream out;
    for (int rank = 7; rank >= 0; --rank) {
        int run = 0;
        for (int file = 0; file < 8; ++file) {
            const char piece = board[rank * 8 + file];
            if (piece == EMPTY) ++run;
            else {
                if (run) { out << run; run = 0; }
                out << piece;
            }
        }
        if (run) out << run;
        if (rank) out << '/';
    }
    out << ' ' << (turn == Color::White ? 'w' : 'b') << ' ';
    bool any = false;
    if (castling & CASTLE_WK) { out << 'K'; any = true; }
    if (castling & CASTLE_WQ) { out << 'Q'; any = true; }
    if (castling & CASTLE_BK) { out << 'k'; any = true; }
    if (castling & CASTLE_BQ) { out << 'q'; any = true; }
    if (!any) out << '-';
    out << ' ' << (ep_square < 0 ? "-" : square_name(ep_square));
    out << ' ' << halfmove_clock << ' ' << fullmove_number;
    return out.str();
}

bool is_square_attacked(const Position& position, int sq, Color by_color) {
    const int file = file_of(sq);
    const int rank = rank_of(sq);
    const char pawn = by_color == Color::White ? 'P' : 'p';
    const int source_rank = by_color == Color::White ? rank - 1 : rank + 1;
    for (int source_file : {file - 1, file + 1}) {
        if (inside(source_file, source_rank) && position.board[source_rank * 8 + source_file] == pawn) return true;
    }
    const char knight = by_color == Color::White ? 'N' : 'n';
    for (const auto [df, dr] : KNIGHT_DELTAS) {
        const int f = file + df, r = rank + dr;
        if (inside(f, r) && position.board[r * 8 + f] == knight) return true;
    }
    const char king = by_color == Color::White ? 'K' : 'k';
    for (const auto [df, dr] : KING_DELTAS) {
        const int f = file + df, r = rank + dr;
        if (inside(f, r) && position.board[r * 8 + f] == king) return true;
    }
    const char bishop = by_color == Color::White ? 'B' : 'b';
    const char rook = by_color == Color::White ? 'R' : 'r';
    const char queen = by_color == Color::White ? 'Q' : 'q';
    for (const auto [df, dr] : BISHOP_DIRS) {
        int f = file + df, r = rank + dr;
        while (inside(f, r)) {
            const char p = position.board[r * 8 + f];
            if (p != EMPTY) { if (p == bishop || p == queen) return true; break; }
            f += df; r += dr;
        }
    }
    for (const auto [df, dr] : ROOK_DIRS) {
        int f = file + df, r = rank + dr;
        while (inside(f, r)) {
            const char p = position.board[r * 8 + f];
            if (p != EMPTY) { if (p == rook || p == queen) return true; break; }
            f += df; r += dr;
        }
    }
    return false;
}

bool in_check(const Position& position, std::optional<Color> color) {
    const Color c = color.value_or(position.turn);
    return is_square_attacked(position, position.king_square(c), opposite(c));
}

std::vector<Move> pseudo_legal_moves(const Position& position) {
    std::vector<Move> out;
    out.reserve(96);
    for (int sq = 0; sq < 64; ++sq) {
        const char piece = position.board[sq];
        if (piece == EMPTY || piece_color(piece) != std::optional<Color>(position.turn)) continue;
        switch (piece_type(piece)) {
            case 'P': add_pawn_moves(position, sq, piece, out); break;
            case 'N': add_leaper_moves(position, sq, piece, KNIGHT_DELTAS, out); break;
            case 'B': add_slider_moves(position, sq, piece, BISHOP_DIRS, out); break;
            case 'R': add_slider_moves(position, sq, piece, ROOK_DIRS, out); break;
            case 'Q': add_slider_moves(position, sq, piece, QUEEN_DIRS, out); break;
            case 'K': add_leaper_moves(position, sq, piece, KING_DELTAS, out); add_castling(position, sq, piece, out); break;
            default: break;
        }
    }
    return out;
}

Position apply_move(const Position& position, const Move& move, bool validate_turn_piece) {
    if (move.from >= 64 || move.to >= 64) throw std::invalid_argument("move square out of range");
    Position child = position;
    const char moving = child.board[move.from];
    if (moving == EMPTY) throw std::invalid_argument("move source is empty");
    const auto mover_opt = piece_color(moving);
    if (!mover_opt) throw std::invalid_argument("invalid move source piece");
    const Color mover = *mover_opt;
    if (validate_turn_piece && mover != position.turn) throw std::invalid_argument("move source does not belong to side to move");
    char captured = child.board[move.to];
    if (captured != EMPTY && piece_type(captured) == 'K') throw std::invalid_argument("king capture is not a legal transition");

    child.board[move.from] = EMPTY;
    if (move.is_en_passant()) {
        const int capture_sq = mover == Color::White ? static_cast<int>(move.to) - 8 : static_cast<int>(move.to) + 8;
        if (capture_sq < 0 || capture_sq >= 64) throw std::invalid_argument("invalid en-passant capture square");
        captured = child.board[capture_sq];
        child.board[capture_sq] = EMPTY;
    }
    child.board[move.to] = moving;

    if (move.is_castle()) {
        switch (move.to) {
            case 6: child.board[7] = EMPTY; child.board[5] = 'R'; break;
            case 2: child.board[0] = EMPTY; child.board[3] = 'R'; break;
            case 62: child.board[63] = EMPTY; child.board[61] = 'r'; break;
            case 58: child.board[56] = EMPTY; child.board[59] = 'r'; break;
            default: throw std::invalid_argument("invalid castling destination");
        }
    }
    if (move.promotion != '\0') {
        if (piece_type(moving) != 'P') throw std::invalid_argument("only a pawn may promote");
        const char up = static_cast<char>(std::toupper(static_cast<unsigned char>(move.promotion)));
        if (up != 'Q' && up != 'R' && up != 'B' && up != 'N') throw std::invalid_argument("unsupported promotion piece");
        child.board[move.to] = mover == Color::White ? up : static_cast<char>(std::tolower(static_cast<unsigned char>(up)));
    }

    std::uint8_t castling = position.castling;
    if (moving == 'K') castling &= static_cast<std::uint8_t>(~(CASTLE_WK | CASTLE_WQ));
    else if (moving == 'k') castling &= static_cast<std::uint8_t>(~(CASTLE_BK | CASTLE_BQ));
    else if (moving == 'R') {
        if (move.from == 0) castling &= static_cast<std::uint8_t>(~CASTLE_WQ);
        else if (move.from == 7) castling &= static_cast<std::uint8_t>(~CASTLE_WK);
    } else if (moving == 'r') {
        if (move.from == 56) castling &= static_cast<std::uint8_t>(~CASTLE_BQ);
        else if (move.from == 63) castling &= static_cast<std::uint8_t>(~CASTLE_BK);
    }
    if (captured == 'R') {
        if (move.to == 0) castling &= static_cast<std::uint8_t>(~CASTLE_WQ);
        else if (move.to == 7) castling &= static_cast<std::uint8_t>(~CASTLE_WK);
    } else if (captured == 'r') {
        if (move.to == 56) castling &= static_cast<std::uint8_t>(~CASTLE_BQ);
        else if (move.to == 63) castling &= static_cast<std::uint8_t>(~CASTLE_BK);
    }
    child.castling = castling;
    child.ep_square = move.is_double_pawn() ? static_cast<std::int8_t>((static_cast<int>(move.from) + static_cast<int>(move.to)) / 2) : -1;
    child.halfmove_clock = (piece_type(moving) == 'P' || captured != EMPTY) ? 0 : static_cast<std::uint16_t>(std::min<unsigned>(65535u, position.halfmove_clock + 1u));
    child.fullmove_number = position.turn == Color::Black ? static_cast<std::uint16_t>(std::min<unsigned>(65535u, position.fullmove_number + 1u)) : position.fullmove_number;
    child.turn = opposite(position.turn);
    return child;
}

std::vector<Move> legal_moves(const Position& position) {
    std::vector<Move> out;
    const Color mover = position.turn;
    for (const Move& move : pseudo_legal_moves(position)) {
        const Position child = apply_move(position, move);
        if (!in_check(child, mover)) out.push_back(move);
    }
    std::sort(out.begin(), out.end(), [](const Move& a, const Move& b) { return a.uci() < b.uci(); });
    return out;
}

Move parse_uci_move(const Position& position, std::string_view text) {
    std::string token(text);
    std::transform(token.begin(), token.end(), token.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    std::optional<Move> found;
    for (const auto& move : legal_moves(position)) {
        if (move.uci() == token) {
            if (found) throw std::invalid_argument("UCI move is not unique");
            found = move;
        }
    }
    if (!found) throw std::invalid_argument("UCI move is not legal in the position");
    return *found;
}

bool insufficient_material(const Position& position) {
    std::vector<std::pair<int, char>> non_kings;
    for (int sq = 0; sq < 64; ++sq) {
        const char piece = position.board[sq];
        if (piece != EMPTY && piece_type(piece) != 'K') non_kings.emplace_back(sq, piece);
    }
    if (non_kings.empty()) return true;
    for (const auto [sq, piece] : non_kings) {
        (void)sq;
        const char t = piece_type(piece);
        if (t == 'P' || t == 'R' || t == 'Q') return false;
    }
    if (non_kings.size() == 1 && (piece_type(non_kings[0].second) == 'B' || piece_type(non_kings[0].second) == 'N')) return true;
    bool bishops_only = true;
    int square_color = -1;
    for (const auto [sq, piece] : non_kings) {
        if (piece_type(piece) != 'B') { bishops_only = false; break; }
        const int c = (file_of(sq) + rank_of(sq)) & 1;
        if (square_color < 0) square_color = c;
        else if (c != square_color) return false;
    }
    return bishops_only;
}

PositionStatus position_status(const Position& position, const std::vector<std::string>* history_keys, bool claim_draws) {
    const auto moves = legal_moves(position);
    if (moves.empty()) {
        if (in_check(position)) return PositionStatus{true, "checkmate", opposite(position.turn), false, "side to move is in check with no legal move"};
        return PositionStatus{true, "stalemate", std::nullopt, false, "side to move has no legal move and is not in check"};
    }
    if (insufficient_material(position)) return PositionStatus{true, "dead_position", std::nullopt, false, "implemented exact dead-position subset"};
    if (position.halfmove_clock >= 150) return PositionStatus{true, "seventy_five_move", std::nullopt, false, "automatic 75-move draw"};
    if (history_keys) {
        const auto key = repetition_key(position);
        const auto count = static_cast<int>(std::count(history_keys->begin(), history_keys->end(), key));
        if (count >= 5) return PositionStatus{true, "fivefold_repetition", std::nullopt, false, "automatic fivefold repetition"};
        if (claim_draws && count >= 3) return PositionStatus{true, "threefold_repetition_claim", std::nullopt, true, "verified draw claim is available"};
    }
    if (claim_draws && position.halfmove_clock >= 100) return PositionStatus{true, "fifty_move_claim", std::nullopt, true, "verified 50-move draw claim is available"};
    return PositionStatus{};
}

std::uint64_t perft(const Position& position, int depth) {
    if (depth < 0) throw std::invalid_argument("perft depth must be non-negative");
    if (depth == 0) return 1;
    std::uint64_t total = 0;
    for (const auto& move : legal_moves(position)) total += perft(apply_move(position, move), depth - 1);
    return total;
}

std::vector<std::pair<std::string, std::uint64_t>> perft_divide(const Position& position, int depth) {
    if (depth < 1) throw std::invalid_argument("perft divide depth must be positive");
    std::vector<std::pair<std::string, std::uint64_t>> out;
    for (const auto& move : legal_moves(position)) out.emplace_back(move.uci(), perft(apply_move(position, move), depth - 1));
    std::sort(out.begin(), out.end());
    return out;
}

std::string canonical_state_text(const Position& position, bool include_counters) {
    std::ostringstream out;
    out << "board=";
    for (char c : position.board) out << c;
    out << "\nturn=" << (position.turn == Color::White ? 'w' : 'b');
    out << "\ncastling=" << static_cast<unsigned>(position.castling);
    out << "\nep=" << static_cast<int>(position.ep_square);
    if (include_counters) {
        out << "\nhalfmove=" << position.halfmove_clock;
        out << "\nfullmove=" << position.fullmove_number;
    }
    out << '\n';
    return out.str();
}

std::string state_sha256(const Position& position, bool include_counters) { return sha256_hex(canonical_state_text(position, include_counters)); }

std::string repetition_record_text(const Position& position) {
    const int ep = ep_capture_sources(position).empty() ? -1 : position.ep_square;
    std::ostringstream out;
    out << "board=";
    for (char c : position.board) out << c;
    out << "\nturn=" << (position.turn == Color::White ? 'w' : 'b');
    out << "\ncastling=" << static_cast<unsigned>(position.castling);
    out << "\nep=" << ep << '\n';
    return out.str();
}

std::string repetition_key(const Position& position) { return sha256_hex(repetition_record_text(position)); }

std::uint64_t cache_key64(const Position& position) {
    const std::string hex = state_sha256(position, false);
    std::uint64_t value = 0;
    for (int i = 0; i < 16; ++i) {
        value <<= 4;
        const char c = hex[static_cast<std::size_t>(i)];
        value |= static_cast<std::uint64_t>(c >= '0' && c <= '9' ? c - '0' : 10 + c - 'a');
    }
    return value;
}

}  // namespace ugts::chess2
