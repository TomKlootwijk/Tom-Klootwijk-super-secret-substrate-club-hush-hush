#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace ugts::chess2 {

enum class Color : std::uint8_t { White = 0, Black = 1 };
constexpr Color opposite(Color c) noexcept { return c == Color::White ? Color::Black : Color::White; }

constexpr std::uint8_t CASTLE_WK = 1u;
constexpr std::uint8_t CASTLE_WQ = 2u;
constexpr std::uint8_t CASTLE_BK = 4u;
constexpr std::uint8_t CASTLE_BQ = 8u;

constexpr std::uint8_t MOVE_CAPTURE = 1u << 0;
constexpr std::uint8_t MOVE_EN_PASSANT = 1u << 1;
constexpr std::uint8_t MOVE_CASTLE = 1u << 2;
constexpr std::uint8_t MOVE_PROMOTION = 1u << 3;
constexpr std::uint8_t MOVE_DOUBLE_PAWN = 1u << 4;

struct Move {
    std::uint8_t from = 0;
    std::uint8_t to = 0;
    char promotion = '\0';
    std::uint8_t flags = 0;

    [[nodiscard]] bool is_capture() const noexcept { return (flags & MOVE_CAPTURE) != 0; }
    [[nodiscard]] bool is_en_passant() const noexcept { return (flags & MOVE_EN_PASSANT) != 0; }
    [[nodiscard]] bool is_castle() const noexcept { return (flags & MOVE_CASTLE) != 0; }
    [[nodiscard]] bool is_promotion() const noexcept { return (flags & MOVE_PROMOTION) != 0; }
    [[nodiscard]] bool is_double_pawn() const noexcept { return (flags & MOVE_DOUBLE_PAWN) != 0; }
    [[nodiscard]] std::string uci() const;

    friend bool operator==(const Move&, const Move&) = default;
    friend bool operator<(const Move& a, const Move& b) noexcept {
        if (a.from != b.from) return a.from < b.from;
        if (a.to != b.to) return a.to < b.to;
        if (a.promotion != b.promotion) return a.promotion < b.promotion;
        return a.flags < b.flags;
    }
};

struct Position {
    std::array<char, 64> board{};
    Color turn = Color::White;
    std::uint8_t castling = CASTLE_WK | CASTLE_WQ | CASTLE_BK | CASTLE_BQ;
    std::int8_t ep_square = -1;
    std::uint16_t halfmove_clock = 0;
    std::uint16_t fullmove_number = 1;

    static Position from_fen(std::string_view fen, bool strict = true);
    static Position initial();
    [[nodiscard]] std::string to_fen() const;
    [[nodiscard]] int king_square(Color c) const;
    void validate_structure() const;
};

struct PositionStatus {
    bool terminal = false;
    std::string code = "ongoing";
    std::optional<Color> winner;
    bool claimable = false;
    std::string detail;
};

[[nodiscard]] int file_of(int sq) noexcept;
[[nodiscard]] int rank_of(int sq) noexcept;
[[nodiscard]] std::string square_name(int sq);
[[nodiscard]] int parse_square(std::string_view name);
[[nodiscard]] std::optional<Color> piece_color(char piece) noexcept;
[[nodiscard]] char piece_type(char piece) noexcept;

[[nodiscard]] bool is_square_attacked(const Position& position, int sq, Color by_color);
[[nodiscard]] bool in_check(const Position& position, std::optional<Color> color = std::nullopt);
[[nodiscard]] std::vector<Move> pseudo_legal_moves(const Position& position);
[[nodiscard]] Position apply_move(const Position& position, const Move& move, bool validate_turn_piece = true);
[[nodiscard]] std::vector<Move> legal_moves(const Position& position);
[[nodiscard]] Move parse_uci_move(const Position& position, std::string_view text);
[[nodiscard]] PositionStatus position_status(const Position& position,
                                             const std::vector<std::string>* history_keys = nullptr,
                                             bool claim_draws = true);
[[nodiscard]] bool insufficient_material(const Position& position);
[[nodiscard]] std::uint64_t perft(const Position& position, int depth);
[[nodiscard]] std::vector<std::pair<std::string, std::uint64_t>> perft_divide(const Position& position, int depth);

[[nodiscard]] std::string canonical_state_text(const Position& position, bool include_counters = true);
[[nodiscard]] std::string state_sha256(const Position& position, bool include_counters = true);
[[nodiscard]] std::string repetition_record_text(const Position& position);
[[nodiscard]] std::string repetition_key(const Position& position);
[[nodiscard]] std::uint64_t cache_key64(const Position& position);

}  // namespace ugts::chess2
