#pragma once

#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace ugts_go19 {

constexpr std::uint8_t kEmpty = 0;
constexpr std::uint8_t kBlack = 1;
constexpr std::uint8_t kWhite = 2;
constexpr int kPass = -1;

class IllegalMove : public std::invalid_argument {
 public:
  using std::invalid_argument::invalid_argument;
};

struct Rules {
  int size = 19;
  int komi2 = 15;
  bool allow_suicide = false;
  int passes_to_end = 2;
};

struct State {
  int size = 19;
  std::vector<std::uint8_t> board;
  std::uint8_t to_play = kBlack;
  int passes = 0;
  std::vector<std::vector<std::uint8_t>> seen_boards;
  std::optional<std::vector<std::uint8_t>> previous_board;
  std::uint64_t ply = 0;

  static State Initial(const Rules& rules);
  [[nodiscard]] bool Terminal(const Rules& rules) const;
};

struct ApplyResult {
  State state;
  int captured = 0;
  int self_captured = 0;
};

[[nodiscard]] std::uint8_t Other(std::uint8_t color);
[[nodiscard]] std::vector<int> Neighbors(int point, int size);
[[nodiscard]] std::pair<std::vector<int>, std::vector<int>> GroupAndLiberties(
    const std::vector<std::uint8_t>& board, int start, int size);
[[nodiscard]] ApplyResult ApplyMove(const State& state, int move,
                                    const Rules& rules);
[[nodiscard]] bool IsLegal(const State& state, int move, const Rules& rules);
[[nodiscard]] std::vector<int> LegalMoves(const State& state,
                                          const Rules& rules,
                                          bool include_pass = true);
[[nodiscard]] std::int64_t AreaScore2(const State& state, const Rules& rules);
[[nodiscard]] std::vector<std::uint64_t> PackBlackBitplane(const State& state);
[[nodiscard]] std::vector<std::uint64_t> PackWhiteBitplane(const State& state);
// Canonical proof-state serialization. The representation contains every
// semantic state component from the formal specification, including the full
// positional-superko set and immediately previous board. `ply` is deliberately
// excluded because it is campaign metadata, not part of game-state equality.
[[nodiscard]] std::string CanonicalStateJson(const State& state,
                                             const Rules& rules);
// SHA-256 content address of the exact UTF-8 bytes returned by
// CanonicalStateJson. This is never a substitute for ExactStateEqual.
[[nodiscard]] std::string CanonicalStateObjectId(const State& state,
                                                 const Rules& rules);
// Exact collision-independent semantic equality. Hashes may select candidates,
// but this comparison is the authority before proof data can be shared.
[[nodiscard]] bool ExactStateEqual(const State& left, const Rules& left_rules,
                                   const State& right,
                                   const Rules& right_rules);
[[nodiscard]] std::string BoardDigestHex(const State& state);

}  // namespace ugts_go19
