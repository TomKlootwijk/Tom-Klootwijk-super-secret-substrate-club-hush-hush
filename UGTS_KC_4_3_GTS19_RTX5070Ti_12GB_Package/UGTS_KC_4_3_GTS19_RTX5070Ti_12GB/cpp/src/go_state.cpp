#include "ugts_go19/go_state.hpp"

#include "ugts_go19/sha256.hpp"

#include <algorithm>
#include <array>
#include <iomanip>
#include <limits>
#include <locale>
#include <queue>
#include <set>
#include <sstream>
#include <stdexcept>

namespace ugts_go19 {
namespace {

void ValidateBoard(const std::vector<std::uint8_t>& board,
                   std::size_t expected_points, const char* label) {
  if (board.size() != expected_points) {
    throw std::invalid_argument(std::string(label) +
                                " size does not match rules");
  }
  if (std::any_of(board.begin(), board.end(), [](std::uint8_t point) {
        return point != kEmpty && point != kBlack && point != kWhite;
      })) {
    throw std::invalid_argument(std::string(label) +
                                " contains an invalid point");
  }
}

void ValidateStateForRules(const State& state, const Rules& rules) {
  if (rules.size < 1 || rules.size > 19) {
    throw std::invalid_argument("board size must be in 1..19");
  }
  if (rules.passes_to_end < 1) {
    throw std::invalid_argument("passes_to_end must be positive");
  }
  if (state.size != rules.size) {
    throw std::invalid_argument("state size does not match rules");
  }
  if (state.to_play != kBlack && state.to_play != kWhite) {
    throw std::invalid_argument("state has an invalid player to move");
  }
  if (state.passes < 0) {
    throw std::invalid_argument("state pass count cannot be negative");
  }
  if (state.passes > rules.passes_to_end) {
    throw std::invalid_argument("state pass count exceeds terminal count");
  }

  const auto expected_points =
      static_cast<std::size_t>(rules.size * rules.size);
  ValidateBoard(state.board, expected_points, "state board");
  for (const auto& seen_board : state.seen_boards) {
    ValidateBoard(seen_board, expected_points, "seen board");
  }
  auto canonical_seen = state.seen_boards;
  std::sort(canonical_seen.begin(), canonical_seen.end());
  if (std::adjacent_find(canonical_seen.begin(), canonical_seen.end()) !=
      canonical_seen.end()) {
    throw std::invalid_argument(
        "positional-superko history contains a duplicate board");
  }
  if (std::none_of(state.seen_boards.begin(), state.seen_boards.end(),
                   [&](const auto& seen_board) {
                     return seen_board == state.board;
                   })) {
    throw std::invalid_argument(
        "positional-superko history does not contain current board");
  }
  if (state.previous_board.has_value()) {
    ValidateBoard(*state.previous_board, expected_points, "previous board");
    if (std::none_of(state.seen_boards.begin(), state.seen_boards.end(),
                     [&](const auto& seen_board) {
                       return seen_board == *state.previous_board;
                     })) {
      throw std::invalid_argument(
          "positional-superko history does not contain previous board");
    }
  }
}

bool BoardSeen(const State& state, const std::vector<std::uint8_t>& board) {
  return std::any_of(state.seen_boards.begin(), state.seen_boards.end(),
                     [&](const auto& item) { return item == board; });
}

std::string Hex(const std::vector<std::uint8_t>& bytes) {
  constexpr char digits[] = "0123456789abcdef";
  std::string output(bytes.size() * 2, '0');
  for (std::size_t index = 0; index < bytes.size(); ++index) {
    output[2 * index] = digits[bytes[index] >> 4U];
    output[2 * index + 1] = digits[bytes[index] & 0x0fU];
  }
  return output;
}

std::vector<std::vector<std::uint8_t>> CanonicalSeen(const State& state) {
  auto seen = state.seen_boards;
  std::sort(seen.begin(), seen.end());
  return seen;
}

void RequirePlyIncrementAvailable(const State& state) {
  if (state.ply == std::numeric_limits<std::uint64_t>::max()) {
    throw std::overflow_error(
        "ply exceeds the uint64 campaign-metadata representation");
  }
}

// A compact deterministic non-cryptographic board digest for diagnostics only.
// Canonical proof-state content addresses use Sha256Hex instead.
std::uint64_t Fnv1a64(const std::vector<std::uint8_t>& data,
                      std::uint64_t seed) {
  std::uint64_t hash = seed;
  for (std::uint8_t byte : data) {
    hash ^= byte;
    hash *= 1099511628211ULL;
  }
  return hash;
}

}  // namespace

State State::Initial(const Rules& rules) {
  if (rules.size < 1 || rules.size > 19) {
    throw std::invalid_argument("board size must be in 1..19");
  }
  if (rules.passes_to_end < 1) {
    throw std::invalid_argument("passes_to_end must be positive");
  }
  State state;
  state.size = rules.size;
  state.board.assign(static_cast<std::size_t>(rules.size * rules.size), kEmpty);
  state.to_play = kBlack;
  state.passes = 0;
  state.seen_boards.push_back(state.board);
  return state;
}

bool State::Terminal(const Rules& rules) const {
  return passes >= rules.passes_to_end;
}

std::uint8_t Other(std::uint8_t color) {
  if (color == kBlack) return kWhite;
  if (color == kWhite) return kBlack;
  throw std::invalid_argument("invalid color");
}

std::vector<int> Neighbors(int point, int size) {
  const int x = point % size;
  const int y = point / size;
  std::vector<int> result;
  result.reserve(4);
  if (x > 0) result.push_back(point - 1);
  if (x + 1 < size) result.push_back(point + 1);
  if (y > 0) result.push_back(point - size);
  if (y + 1 < size) result.push_back(point + size);
  return result;
}

std::pair<std::vector<int>, std::vector<int>> GroupAndLiberties(
    const std::vector<std::uint8_t>& board, int start, int size) {
  if (start < 0 || start >= static_cast<int>(board.size())) {
    throw std::out_of_range("group start outside board");
  }
  const auto color = board[static_cast<std::size_t>(start)];
  if (color == kEmpty) return {{}, {start}};

  std::vector<std::uint8_t> stone_seen(board.size(), 0);
  std::vector<std::uint8_t> liberty_seen(board.size(), 0);
  std::vector<int> stones;
  std::vector<int> liberties;
  std::vector<int> stack{start};
  stone_seen[static_cast<std::size_t>(start)] = 1;
  while (!stack.empty()) {
    const int point = stack.back();
    stack.pop_back();
    stones.push_back(point);
    for (int neighbor : Neighbors(point, size)) {
      const auto value = board[static_cast<std::size_t>(neighbor)];
      if (value == kEmpty) {
        if (!liberty_seen[static_cast<std::size_t>(neighbor)]) {
          liberty_seen[static_cast<std::size_t>(neighbor)] = 1;
          liberties.push_back(neighbor);
        }
      } else if (value == color &&
                 !stone_seen[static_cast<std::size_t>(neighbor)]) {
        stone_seen[static_cast<std::size_t>(neighbor)] = 1;
        stack.push_back(neighbor);
      }
    }
  }
  std::sort(stones.begin(), stones.end());
  std::sort(liberties.begin(), liberties.end());
  return {stones, liberties};
}

ApplyResult ApplyMove(const State& state, int move, const Rules& rules) {
  ValidateStateForRules(state, rules);
  if (state.Terminal(rules)) {
    throw IllegalMove("game is terminal");
  }
  const std::uint8_t next_player = Other(state.to_play);
  if (move == kPass) {
    RequirePlyIncrementAvailable(state);
    State next = state;
    next.to_play = next_player;
    next.passes += 1;
    next.previous_board = state.board;
    next.ply += 1;
    return {std::move(next), 0, 0};
  }
  if (move < 0 || move >= static_cast<int>(state.board.size())) {
    throw IllegalMove("move outside board");
  }
  if (state.board[static_cast<std::size_t>(move)] != kEmpty) {
    throw IllegalMove("occupied point");
  }

  State next = state;
  next.board[static_cast<std::size_t>(move)] = state.to_play;
  int captured = 0;
  std::vector<std::uint8_t> checked(next.board.size(), 0);
  for (int adjacent : Neighbors(move, rules.size)) {
    if (next.board[static_cast<std::size_t>(adjacent)] != next_player ||
        checked[static_cast<std::size_t>(adjacent)]) {
      continue;
    }
    auto [stones, liberties] =
        GroupAndLiberties(next.board, adjacent, rules.size);
    for (int stone : stones) checked[static_cast<std::size_t>(stone)] = 1;
    if (liberties.empty()) {
      captured += static_cast<int>(stones.size());
      for (int stone : stones) next.board[static_cast<std::size_t>(stone)] = kEmpty;
    }
  }

  auto [own_stones, own_liberties] =
      GroupAndLiberties(next.board, move, rules.size);
  int self_captured = 0;
  if (own_liberties.empty()) {
    if (!rules.allow_suicide) throw IllegalMove("suicide");
    self_captured = static_cast<int>(own_stones.size());
    for (int stone : own_stones) next.board[static_cast<std::size_t>(stone)] = kEmpty;
  }

  if (BoardSeen(state, next.board)) {
    throw IllegalMove("positional superko");
  }
  RequirePlyIncrementAvailable(state);
  next.seen_boards.push_back(next.board);
  next.previous_board = state.board;
  next.to_play = next_player;
  next.passes = 0;
  next.ply += 1;
  return {std::move(next), captured, self_captured};
}

bool IsLegal(const State& state, int move, const Rules& rules) {
  try {
    static_cast<void>(ApplyMove(state, move, rules));
    return true;
  } catch (const IllegalMove&) {
    return false;
  }
}

std::vector<int> LegalMoves(const State& state, const Rules& rules,
                            bool include_pass) {
  ValidateStateForRules(state, rules);
  std::vector<int> result;
  if (state.Terminal(rules)) return result;
  for (int point = 0; point < static_cast<int>(state.board.size()); ++point) {
    if (state.board[static_cast<std::size_t>(point)] == kEmpty &&
        IsLegal(state, point, rules)) {
      result.push_back(point);
    }
  }
  if (include_pass) {
    RequirePlyIncrementAvailable(state);
    result.push_back(kPass);
  }
  return result;
}

std::int64_t AreaScore2(const State& state, const Rules& rules) {
  ValidateStateForRules(state, rules);
  int black_area = 0;
  int white_area = 0;
  std::vector<std::uint8_t> visited(state.board.size(), 0);
  for (int point = 0; point < static_cast<int>(state.board.size()); ++point) {
    const auto value = state.board[static_cast<std::size_t>(point)];
    if (value == kBlack) {
      ++black_area;
      continue;
    }
    if (value == kWhite) {
      ++white_area;
      continue;
    }
    if (visited[static_cast<std::size_t>(point)]) continue;

    std::vector<int> region;
    std::vector<int> stack{point};
    visited[static_cast<std::size_t>(point)] = 1;
    bool borders_black = false;
    bool borders_white = false;
    while (!stack.empty()) {
      const int current = stack.back();
      stack.pop_back();
      region.push_back(current);
      for (int neighbor : Neighbors(current, rules.size)) {
        const auto adjacent = state.board[static_cast<std::size_t>(neighbor)];
        if (adjacent == kEmpty &&
            !visited[static_cast<std::size_t>(neighbor)]) {
          visited[static_cast<std::size_t>(neighbor)] = 1;
          stack.push_back(neighbor);
        } else if (adjacent == kBlack) {
          borders_black = true;
        } else if (adjacent == kWhite) {
          borders_white = true;
        }
      }
    }
    if (borders_black && !borders_white) {
      black_area += static_cast<int>(region.size());
    } else if (borders_white && !borders_black) {
      white_area += static_cast<int>(region.size());
    }
  }
  return 2LL * static_cast<std::int64_t>(black_area - white_area) -
         static_cast<std::int64_t>(rules.komi2);
}

std::vector<std::uint64_t> PackBlackBitplane(const State& state) {
  const std::size_t words = (state.board.size() + 63U) / 64U;
  std::vector<std::uint64_t> output(words, 0);
  for (std::size_t point = 0; point < state.board.size(); ++point) {
    if (state.board[point] == kBlack) {
      output[point / 64U] |= (1ULL << (point % 64U));
    }
  }
  return output;
}

std::vector<std::uint64_t> PackWhiteBitplane(const State& state) {
  const std::size_t words = (state.board.size() + 63U) / 64U;
  std::vector<std::uint64_t> output(words, 0);
  for (std::size_t point = 0; point < state.board.size(); ++point) {
    if (state.board[point] == kWhite) {
      output[point / 64U] |= (1ULL << (point % 64U));
    }
  }
  return output;
}

std::string CanonicalStateJson(const State& state, const Rules& rules) {
  ValidateStateForRules(state, rules);
  const auto seen = CanonicalSeen(state);
  std::ostringstream stream;
  stream.imbue(std::locale::classic());
  // Keys at every object level are lexicographically sorted, and there is no
  // insignificant whitespace. All string values are fixed ASCII or hex.
  stream << "{\"board_hex\":\"" << Hex(state.board)
         << "\",\"format\":\"UGTS-GO-STATE-v1\",\"passes\":"
         << state.passes << ",\"previous_board_hex\":";
  if (state.previous_board.has_value()) {
    stream << '\"' << Hex(*state.previous_board) << '\"';
  } else {
    stream << "null";
  }
  stream << ",\"rules\":{\"allow_suicide\":"
         << (rules.allow_suicide ? "true" : "false")
         << ",\"komi2\":" << rules.komi2
         << ",\"passes_to_end\":" << rules.passes_to_end
         << ",\"scoring\":\"area\",\"size\":" << rules.size
         << ",\"superko\":\"positional_superko\"},\"seen_hex\":[";
  for (std::size_t index = 0; index < seen.size(); ++index) {
    if (index != 0) stream << ',';
    stream << '\"' << Hex(seen[index]) << '\"';
  }
  stream << "],\"to_play\":" << static_cast<int>(state.to_play) << '}';
  return stream.str();
}

std::string CanonicalStateObjectId(const State& state, const Rules& rules) {
  return Sha256Hex(CanonicalStateJson(state, rules));
}

bool ExactStateEqual(const State& left, const Rules& left_rules,
                     const State& right, const Rules& right_rules) {
  ValidateStateForRules(left, left_rules);
  ValidateStateForRules(right, right_rules);
  if (left_rules.size != right_rules.size ||
      left_rules.komi2 != right_rules.komi2 ||
      left_rules.allow_suicide != right_rules.allow_suicide ||
      left_rules.passes_to_end != right_rules.passes_to_end) {
    return false;
  }
  return left.board == right.board && left.to_play == right.to_play &&
         left.passes == right.passes &&
         left.previous_board == right.previous_board &&
         CanonicalSeen(left) == CanonicalSeen(right);
}

std::string BoardDigestHex(const State& state) {
  const auto first = Fnv1a64(state.board, 1469598103934665603ULL);
  const auto second = Fnv1a64(state.board, 1099511628211ULL ^ state.to_play);
  std::ostringstream stream;
  stream << std::hex << std::setfill('0') << std::setw(16) << first
         << std::setw(16) << second;
  return stream.str();
}

}  // namespace ugts_go19
