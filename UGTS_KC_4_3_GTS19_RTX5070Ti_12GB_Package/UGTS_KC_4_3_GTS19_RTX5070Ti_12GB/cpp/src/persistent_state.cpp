#include "ugts_go19/persistent_state.hpp"

#include "ugts_go19/sha256.hpp"

#include <algorithm>
#include <atomic>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>

namespace ugts_go19 {
namespace {

constexpr std::size_t kDigestBytes = 32;
constexpr std::size_t kLeafDepth = kDigestBytes;
constexpr std::size_t kPackedWords = 6;

std::atomic<std::uint64_t> g_next_arena_owner{1};

std::uint64_t AllocateArenaOwner() {
  std::uint64_t candidate = g_next_arena_owner.load(std::memory_order_relaxed);
  for (;;) {
    // Leave the counter permanently at max. This sacrifices one possible ID
    // so owner identity can never wrap to zero or reuse an earlier owner.
    if (candidate == 0U ||
        candidate == std::numeric_limits<std::uint64_t>::max()) {
      throw std::overflow_error("persistent arena owner space exhausted");
    }
    if (g_next_arena_owner.compare_exchange_weak(candidate, candidate + 1U,
                                                 std::memory_order_relaxed,
                                                 std::memory_order_relaxed)) {
      return candidate;
    }
  }
}

void IncrementDiagnostic(std::uint64_t& counter) noexcept {
  if (counter != std::numeric_limits<std::uint64_t>::max()) ++counter;
}

struct DigestHash {
  std::size_t operator()(const LocatorDigest256& digest) const noexcept {
    std::size_t value = 1469598103934665603ULL;
    for (std::uint8_t byte : digest) {
      value ^= static_cast<std::size_t>(byte);
      value *= static_cast<std::size_t>(1099511628211ULL);
    }
    return value;
  }
};

std::uint8_t HexNibble(char value) {
  if (value >= '0' && value <= '9') {
    return static_cast<std::uint8_t>(value - '0');
  }
  if (value >= 'a' && value <= 'f') {
    return static_cast<std::uint8_t>(value - 'a' + 10);
  }
  throw std::logic_error("SHA-256 returned non-lowercase-hex output");
}

LocatorDigest256 DefaultLocator(std::string_view material) {
  const std::string hex = Sha256Hex(material);
  if (hex.size() != 64U) {
    throw std::logic_error("SHA-256 returned the wrong digest length");
  }
  LocatorDigest256 result{};
  for (std::size_t index = 0; index < result.size(); ++index) {
    result[index] = static_cast<std::uint8_t>(
        (HexNibble(hex[index * 2U]) << 4U) | HexNibble(hex[index * 2U + 1U]));
  }
  return result;
}

void AppendByte(std::string& output, std::uint8_t value) {
  output.push_back(static_cast<char>(value));
}

void AppendU64(std::string& output, std::uint64_t value) {
  for (unsigned int shift = 0; shift < 64U; shift += 8U) {
    AppendByte(output, static_cast<std::uint8_t>((value >> shift) & 0xffU));
  }
}

std::string BoardLocatorMaterial(const PackedBoard& board) {
  std::string output = "UGTS-CPP-PACKED-BOARD-LOCATOR-v1";
  AppendByte(output, board.size);
  for (std::uint64_t word : board.black) AppendU64(output, word);
  for (std::uint64_t word : board.white) AppendU64(output, word);
  return output;
}

void ValidateBoardSize(int size) {
  if (size < 1 || size > 19) {
    throw std::invalid_argument("board size must be in 1..19");
  }
}

std::size_t PointCount(std::uint8_t size) {
  return static_cast<std::size_t>(size) * static_cast<std::size_t>(size);
}

std::size_t WordCount(std::uint8_t size) {
  return (PointCount(size) + 63U) / 64U;
}

void ValidatePackedBoard(const PackedBoard& board) {
  ValidateBoardSize(static_cast<int>(board.size));
  const std::size_t points = PointCount(board.size);
  const std::size_t words = WordCount(board.size);
  for (std::size_t word = 0; word < kPackedWords; ++word) {
    if ((board.black[word] & board.white[word]) != 0U) {
      throw std::invalid_argument("packed board bitplanes overlap");
    }
    if (word >= words && (board.black[word] != 0U || board.white[word] != 0U)) {
      throw std::invalid_argument("packed board has nonzero unused words");
    }
  }
  const std::size_t tail_bits = points % 64U;
  if (tail_bits != 0U) {
    const std::uint64_t valid_mask = (1ULL << tail_bits) - 1ULL;
    if (((board.black[words - 1U] | board.white[words - 1U]) & ~valid_mask) !=
        0U) {
      throw std::invalid_argument("packed board has nonzero unused tail bits");
    }
  }
}

bool PackedBoardLess(const PackedBoard& left, const PackedBoard& right) {
  if (left.size != right.size) return left.size < right.size;
  if (left.black != right.black) return left.black < right.black;
  return left.white < right.white;
}

void ValidateRules(const Rules& rules) {
  ValidateBoardSize(rules.size);
  if (rules.allow_suicide) {
    throw std::invalid_argument(
        "persistent state path requires suicide to be illegal");
  }
  if (rules.passes_to_end != 2) {
    throw std::invalid_argument(
        "persistent state path requires exactly two passes to terminate");
  }
}

bool RulesEqual(const Rules& left, const Rules& right) noexcept {
  return left.size == right.size && left.komi2 == right.komi2 &&
         left.allow_suicide == right.allow_suicide &&
         left.passes_to_end == right.passes_to_end;
}

void RequirePlyIncrementAvailable(std::uint64_t ply) {
  if (ply == std::numeric_limits<std::uint64_t>::max()) {
    throw std::overflow_error(
        "ply exceeds the uint64 campaign-metadata representation");
  }
}

}  // namespace

bool ExactPackedBoardEqual(const PackedBoard& left,
                           const PackedBoard& right) noexcept {
  return left.size == right.size && left.black == right.black &&
         left.white == right.white;
}

PackedBoard PackBoardExact(int size, const std::vector<std::uint8_t>& cells) {
  ValidateBoardSize(size);
  const std::size_t expected =
      static_cast<std::size_t>(size) * static_cast<std::size_t>(size);
  if (cells.size() != expected) {
    throw std::invalid_argument("board size does not match packed board cells");
  }
  PackedBoard result;
  result.size = static_cast<std::uint8_t>(size);
  for (std::size_t point = 0; point < cells.size(); ++point) {
    const std::uint8_t value = cells[point];
    if (value == kBlack) {
      result.black[point / 64U] |= 1ULL << (point % 64U);
    } else if (value == kWhite) {
      result.white[point / 64U] |= 1ULL << (point % 64U);
    } else if (value != kEmpty) {
      throw std::invalid_argument("board contains an invalid point");
    }
  }
  return result;
}

std::vector<std::uint8_t> UnpackBoardExact(const PackedBoard& board) {
  ValidatePackedBoard(board);
  std::vector<std::uint8_t> result(PointCount(board.size), kEmpty);
  for (std::size_t point = 0; point < result.size(); ++point) {
    const std::uint64_t bit = 1ULL << (point % 64U);
    if ((board.black[point / 64U] & bit) != 0U) {
      result[point] = kBlack;
    } else if ((board.white[point / 64U] & bit) != 0U) {
      result[point] = kWhite;
    }
  }
  return result;
}

std::uint64_t CheckedPersistentRank(std::uint64_t member_count,
                                    std::uint64_t passes) {
  const std::uint64_t maximum = std::numeric_limits<std::uint64_t>::max();
  if (member_count > (maximum - passes) / 2U) {
    throw std::overflow_error("persistent state rank exceeds uint64");
  }
  return member_count * 2U + passes;
}

struct PersistentStateArena::Impl {
  enum class NodeKind : std::uint8_t { kBranch = 0, kLeaf = 1 };

  struct BoardRecord {
    PackedBoard value;
    LocatorDigest256 locator{};
  };

  struct HistoryNode {
    NodeKind kind = NodeKind::kBranch;
    std::uint8_t board_size = 0;
    std::uint8_t depth = 0;
    std::uint64_t count = 0;
    std::vector<std::pair<std::uint8_t, std::uint64_t>> children;
    std::vector<std::uint64_t> boards;
    LocatorDigest256 locator{};
  };

  struct StateRecord {
    std::uint64_t board = 0;
    std::uint8_t to_play = kBlack;
    std::uint64_t passes = 0;
    std::uint64_t history = 0;
    std::optional<std::uint64_t> previous_board;
    std::uint64_t ply = 0;
    LocatorDigest256 locator{};
  };

  explicit Impl(PersistentArenaConfig input)
      : owner(AllocateArenaOwner()),
        board_locator(input.board_locator ? std::move(input.board_locator)
                                          : LocatorFunction(DefaultLocator)),
        history_locator(input.history_locator
                            ? std::move(input.history_locator)
                            : LocatorFunction(DefaultLocator)),
        state_locator(input.state_locator ? std::move(input.state_locator)
                                          : LocatorFunction(DefaultLocator)) {
    boards.emplace_back();
    nodes.emplace_back();
    states.emplace_back();
  }

  std::uint64_t owner;
  LocatorFunction board_locator;
  LocatorFunction history_locator;
  LocatorFunction state_locator;
  std::vector<BoardRecord> boards;
  std::vector<HistoryNode> nodes;
  std::vector<StateRecord> states;
  std::unordered_map<LocatorDigest256, std::vector<std::uint64_t>, DigestHash>
      board_buckets;
  std::unordered_map<LocatorDigest256, std::vector<std::uint64_t>, DigestHash>
      node_buckets;
  std::unordered_map<LocatorDigest256, std::vector<std::uint64_t>, DigestHash>
      state_buckets;
  std::array<std::uint64_t, 20> empty_roots{};
  PersistentArenaMetrics metrics;

  const BoardRecord& RequireBoard(BoardHandle handle) const {
    if (handle.owner_ != owner || handle.index_ == 0U ||
        handle.index_ >= boards.size()) {
      throw std::invalid_argument(
          "board handle is invalid or belongs to another arena");
    }
    return boards[static_cast<std::size_t>(handle.index_)];
  }

  const HistoryNode& RequireHistory(HistoryHandle handle) const {
    if (handle.owner_ != owner || handle.index_ == 0U ||
        handle.index_ >= nodes.size()) {
      throw std::invalid_argument(
          "history handle is invalid or belongs to another arena");
    }
    const HistoryNode& root = nodes[static_cast<std::size_t>(handle.index_)];
    if (root.kind != NodeKind::kBranch || root.depth != 0U) {
      throw std::invalid_argument(
          "history handle does not identify a radix root");
    }
    return root;
  }

  const StateRecord& RequireState(PersistentStateHandle handle) const {
    if (handle.owner_ != owner || handle.index_ == 0U ||
        handle.index_ >= states.size()) {
      throw std::invalid_argument(
          "persistent state handle is invalid or belongs to another arena");
    }
    return states[static_cast<std::size_t>(handle.index_)];
  }

  bool ExactNodeRecordEqual(const HistoryNode& left,
                            const HistoryNode& right) const {
    if (left.kind != right.kind || left.board_size != right.board_size ||
        left.depth != right.depth || left.count != right.count ||
        left.children.size() != right.children.size() ||
        left.boards.size() != right.boards.size()) {
      return false;
    }
    if (left.kind == NodeKind::kLeaf) {
      for (std::size_t index = 0; index < left.boards.size(); ++index) {
        const BoardRecord& left_board =
            boards[static_cast<std::size_t>(left.boards[index])];
        const BoardRecord& right_board =
            boards[static_cast<std::size_t>(right.boards[index])];
        if (!ExactPackedBoardEqual(left_board.value, right_board.value)) {
          return false;
        }
      }
      return true;
    }
    for (std::size_t index = 0; index < left.children.size(); ++index) {
      if (left.children[index].first != right.children[index].first) {
        return false;
      }
      const HistoryNode& left_child =
          nodes[static_cast<std::size_t>(left.children[index].second)];
      const HistoryNode& right_child =
          nodes[static_cast<std::size_t>(right.children[index].second)];
      if (!ExactNodeRecordEqual(left_child, right_child)) return false;
    }
    return true;
  }

  std::string NodeLocatorMaterial(const HistoryNode& node) const {
    std::string output = "UGTS-CPP-PSK-RADIX-NODE-LOCATOR-v1";
    AppendByte(output, static_cast<std::uint8_t>(node.kind));
    AppendByte(output, node.board_size);
    AppendByte(output, node.depth);
    AppendU64(output, node.count);
    AppendU64(output, static_cast<std::uint64_t>(node.children.size()));
    for (const auto& child : node.children) {
      AppendByte(output, child.first);
      AppendU64(output, child.second);
    }
    AppendU64(output, static_cast<std::uint64_t>(node.boards.size()));
    for (std::uint64_t board : node.boards) AppendU64(output, board);
    return output;
  }

  void ValidateNodeRecord(const HistoryNode& node) const {
    ValidateBoardSize(static_cast<int>(node.board_size));
    if (node.kind == NodeKind::kLeaf) {
      if (node.depth != kLeafDepth || !node.children.empty() ||
          node.boards.empty() || node.count != node.boards.size()) {
        throw std::logic_error("invalid persistent collision leaf");
      }
      const LocatorDigest256* leaf_locator = nullptr;
      const PackedBoard* previous = nullptr;
      for (std::uint64_t board_id : node.boards) {
        if (board_id == 0U || board_id >= boards.size()) {
          throw std::logic_error("persistent collision leaf has invalid board");
        }
        const BoardRecord& board = boards[static_cast<std::size_t>(board_id)];
        if (board.value.size != node.board_size) {
          throw std::logic_error("persistent collision leaf mixes board sizes");
        }
        if (leaf_locator != nullptr && *leaf_locator != board.locator) {
          throw std::logic_error("persistent collision leaf mixes locators");
        }
        if (previous != nullptr && !PackedBoardLess(*previous, board.value)) {
          throw std::logic_error(
              "persistent collision leaf is not exact-canonical");
        }
        leaf_locator = &board.locator;
        previous = &board.value;
      }
      return;
    }

    if (node.depth >= kLeafDepth || !node.boards.empty()) {
      throw std::logic_error("invalid persistent radix branch");
    }
    if (node.children.empty()) {
      if (node.depth != 0U || node.count != 0U) {
        throw std::logic_error("only an empty radix root may have no children");
      }
      return;
    }
    std::uint64_t count = 0;
    int previous_slot = -1;
    for (const auto& child : node.children) {
      if (static_cast<int>(child.first) <= previous_slot ||
          child.second == 0U || child.second >= nodes.size()) {
        throw std::logic_error("invalid persistent radix child");
      }
      const HistoryNode& child_node =
          nodes[static_cast<std::size_t>(child.second)];
      if (child_node.board_size != node.board_size ||
          child_node.depth != static_cast<std::uint8_t>(node.depth + 1U)) {
        throw std::logic_error("persistent radix child envelope mismatch");
      }
      if (count >
          std::numeric_limits<std::uint64_t>::max() - child_node.count) {
        throw std::overflow_error(
            "persistent history member count exceeds uint64");
      }
      count += child_node.count;
      previous_slot = static_cast<int>(child.first);
    }
    if (count != node.count) {
      throw std::logic_error("persistent radix branch count mismatch");
    }
  }

  std::uint64_t InternNode(HistoryNode node) {
    ValidateNodeRecord(node);
    const std::string material = NodeLocatorMaterial(node);
    node.locator = history_locator(material);
    auto found = node_buckets.find(node.locator);
    if (found != node_buckets.end()) {
      for (std::uint64_t candidate_id : found->second) {
        const HistoryNode& candidate =
            nodes[static_cast<std::size_t>(candidate_id)];
        if (ExactNodeRecordEqual(candidate, node)) {
          IncrementDiagnostic(metrics.history_nodes_reused_by_interning);
          return candidate_id;
        }
      }
    }
    if (nodes.size() == std::numeric_limits<std::uint64_t>::max()) {
      throw std::overflow_error("persistent history node space exhausted");
    }
    const std::uint64_t id = static_cast<std::uint64_t>(nodes.size());
    nodes.push_back(std::move(node));
    auto& bucket = node_buckets[nodes.back().locator];
    bucket.push_back(id);
    metrics.history_nodes = static_cast<std::uint64_t>(nodes.size() - 1U);
    metrics.maximum_history_locator_bucket =
        std::max(metrics.maximum_history_locator_bucket,
                 static_cast<std::uint64_t>(bucket.size()));
    return id;
  }

  std::uint64_t MakeEmptyRoot(int board_size) {
    ValidateBoardSize(board_size);
    std::uint64_t& cached = empty_roots[static_cast<std::size_t>(board_size)];
    if (cached != 0U) return cached;
    HistoryNode root;
    root.kind = NodeKind::kBranch;
    root.board_size = static_cast<std::uint8_t>(board_size);
    root.depth = 0;
    cached = InternNode(std::move(root));
    return cached;
  }

  bool ContainsNode(std::uint64_t node_id, std::size_t depth,
                    const BoardRecord& board) const {
    if (node_id == 0U || node_id >= nodes.size()) {
      throw std::logic_error("persistent radix contains an invalid node");
    }
    const HistoryNode& node = nodes[static_cast<std::size_t>(node_id)];
    if (node.board_size != board.value.size || node.depth != depth) {
      throw std::logic_error("persistent radix lookup envelope mismatch");
    }
    if (depth == kLeafDepth) {
      if (node.kind != NodeKind::kLeaf) {
        throw std::logic_error("persistent radix path did not end in a leaf");
      }
      for (std::uint64_t existing_id : node.boards) {
        const BoardRecord& existing =
            boards[static_cast<std::size_t>(existing_id)];
        if (ExactPackedBoardEqual(existing.value, board.value)) return true;
      }
      return false;
    }
    if (node.kind != NodeKind::kBranch) {
      throw std::logic_error("persistent radix path ended before full depth");
    }
    const std::uint8_t slot = board.locator[depth];
    const auto child =
        std::lower_bound(node.children.begin(), node.children.end(), slot,
                         [](const auto& entry, std::uint8_t value) {
                           return entry.first < value;
                         });
    if (child == node.children.end() || child->first != slot) return false;
    return ContainsNode(child->second, depth + 1U, board);
  }

  std::uint64_t InsertNode(std::uint64_t node_id, std::size_t depth,
                           std::uint64_t board_id, bool& inserted) {
    const BoardRecord& board = boards[static_cast<std::size_t>(board_id)];
    if (depth == kLeafDepth) {
      HistoryNode leaf;
      if (node_id != 0U) {
        if (node_id >= nodes.size()) {
          throw std::logic_error(
              "persistent radix insertion found invalid leaf");
        }
        leaf = nodes[static_cast<std::size_t>(node_id)];
        if (leaf.kind != NodeKind::kLeaf || leaf.depth != kLeafDepth ||
            leaf.board_size != board.value.size) {
          throw std::logic_error("persistent radix insertion leaf mismatch");
        }
        for (std::uint64_t existing_id : leaf.boards) {
          if (ExactPackedBoardEqual(
                  boards[static_cast<std::size_t>(existing_id)].value,
                  board.value)) {
            inserted = false;
            return node_id;
          }
        }
      } else {
        leaf.kind = NodeKind::kLeaf;
        leaf.board_size = board.value.size;
        leaf.depth = static_cast<std::uint8_t>(kLeafDepth);
      }
      leaf.boards.push_back(board_id);
      std::sort(leaf.boards.begin(), leaf.boards.end(),
                [&](std::uint64_t left, std::uint64_t right) {
                  return PackedBoardLess(
                      boards[static_cast<std::size_t>(left)].value,
                      boards[static_cast<std::size_t>(right)].value);
                });
      leaf.count = static_cast<std::uint64_t>(leaf.boards.size());
      IncrementDiagnostic(metrics.path_node_copy_attempts);
      metrics.maximum_collision_leaf_members =
          std::max(metrics.maximum_collision_leaf_members, leaf.count);
      inserted = true;
      return InternNode(std::move(leaf));
    }

    HistoryNode branch;
    if (node_id != 0U) {
      if (node_id >= nodes.size()) {
        throw std::logic_error(
            "persistent radix insertion found invalid branch");
      }
      branch = nodes[static_cast<std::size_t>(node_id)];
      if (branch.kind != NodeKind::kBranch || branch.depth != depth ||
          branch.board_size != board.value.size) {
        throw std::logic_error("persistent radix insertion branch mismatch");
      }
    } else {
      branch.kind = NodeKind::kBranch;
      branch.board_size = board.value.size;
      branch.depth = static_cast<std::uint8_t>(depth);
    }
    const std::uint8_t slot = board.locator[depth];
    auto child =
        std::lower_bound(branch.children.begin(), branch.children.end(), slot,
                         [](const auto& entry, std::uint8_t value) {
                           return entry.first < value;
                         });
    const std::size_t child_offset =
        static_cast<std::size_t>(child - branch.children.begin());
    const std::uint64_t old_child =
        child != branch.children.end() && child->first == slot ? child->second
                                                               : 0U;
    bool child_inserted = false;
    const std::uint64_t new_child =
        InsertNode(old_child, depth + 1U, board_id, child_inserted);
    if (!child_inserted) {
      inserted = false;
      return node_id;
    }
    if (old_child == 0U) {
      branch.children.insert(
          branch.children.begin() + static_cast<std::ptrdiff_t>(child_offset),
          {slot, new_child});
    } else {
      branch.children[child_offset].second = new_child;
    }
    if (node_id == 0U) {
      branch.count = nodes[static_cast<std::size_t>(new_child)].count;
    } else {
      if (branch.count == std::numeric_limits<std::uint64_t>::max()) {
        throw std::overflow_error(
            "persistent history member count exceeds uint64");
      }
      ++branch.count;
    }
    IncrementDiagnostic(metrics.path_node_copy_attempts);
    inserted = true;
    return InternNode(std::move(branch));
  }

  void CollectBoardIds(std::uint64_t node_id,
                       std::vector<std::uint64_t>& output) const {
    if (node_id == 0U || node_id >= nodes.size()) {
      throw std::logic_error("persistent radix traversal found invalid node");
    }
    const HistoryNode& node = nodes[static_cast<std::size_t>(node_id)];
    if (node.kind == NodeKind::kLeaf) {
      output.insert(output.end(), node.boards.begin(), node.boards.end());
      return;
    }
    for (const auto& child : node.children) {
      CollectBoardIds(child.second, output);
    }
  }

  void CollectNodeIds(std::uint64_t node_id,
                      std::set<std::uint64_t>& output) const {
    if (!output.insert(node_id).second) return;
    const HistoryNode& node = nodes[static_cast<std::size_t>(node_id)];
    for (const auto& child : node.children)
      CollectNodeIds(child.second, output);
  }

  bool ExactStateRecordEqual(const StateRecord& left,
                             const StateRecord& right) const {
    if (left.to_play != right.to_play || left.passes != right.passes ||
        left.ply != right.ply ||
        left.previous_board.has_value() != right.previous_board.has_value() ||
        !ExactPackedBoardEqual(
            boards[static_cast<std::size_t>(left.board)].value,
            boards[static_cast<std::size_t>(right.board)].value) ||
        !ExactNodeRecordEqual(nodes[static_cast<std::size_t>(left.history)],
                              nodes[static_cast<std::size_t>(right.history)])) {
      return false;
    }
    if (!left.previous_board.has_value()) return true;
    return ExactPackedBoardEqual(
        boards[static_cast<std::size_t>(*left.previous_board)].value,
        boards[static_cast<std::size_t>(*right.previous_board)].value);
  }

  std::string StateLocatorMaterial(const StateRecord& state) const {
    std::string output = "UGTS-CPP-PERSISTENT-STATE-LOCATOR-v1";
    AppendU64(output, state.board);
    AppendByte(output, state.to_play);
    AppendU64(output, state.passes);
    AppendU64(output, state.history);
    AppendByte(output, state.previous_board.has_value() ? 1U : 0U);
    if (state.previous_board.has_value())
      AppendU64(output, *state.previous_board);
    AppendU64(output, state.ply);
    return output;
  }

  void ValidateStateRecord(const StateRecord& state, const Rules& rules) const {
    ValidateRules(rules);
    if (state.board == 0U || state.board >= boards.size() ||
        state.history == 0U || state.history >= nodes.size()) {
      throw std::invalid_argument("persistent state contains a missing handle");
    }
    const BoardRecord& board = boards[static_cast<std::size_t>(state.board)];
    const HistoryNode& history = nodes[static_cast<std::size_t>(state.history)];
    if (board.value.size != rules.size || history.kind != NodeKind::kBranch ||
        history.depth != 0U || history.board_size != rules.size) {
      throw std::invalid_argument("persistent state size does not match rules");
    }
    if (state.to_play != kBlack && state.to_play != kWhite) {
      throw std::invalid_argument(
          "persistent state has an invalid player to move");
    }
    if (state.passes > static_cast<std::uint64_t>(rules.passes_to_end)) {
      throw std::invalid_argument(
          "persistent state pass count exceeds terminal count");
    }
    if (!ContainsNode(state.history, 0U, board)) {
      throw std::invalid_argument(
          "positional-superko history does not contain current board");
    }
    if (state.previous_board.has_value()) {
      if (*state.previous_board == 0U ||
          *state.previous_board >= boards.size()) {
        throw std::invalid_argument(
            "persistent previous-board handle is missing");
      }
      const BoardRecord& previous =
          boards[static_cast<std::size_t>(*state.previous_board)];
      if (previous.value.size != rules.size) {
        throw std::invalid_argument(
            "persistent previous board size does not match rules");
      }
      if (!ContainsNode(state.history, 0U, previous)) {
        throw std::invalid_argument(
            "positional-superko history does not contain previous board");
      }
    }
    static_cast<void>(CheckedPersistentRank(history.count, state.passes));
  }

  PersistentStateHandle InternStateRecord(StateRecord state,
                                          const Rules& rules) {
    ValidateStateRecord(state, rules);
    const std::string material = StateLocatorMaterial(state);
    state.locator = state_locator(material);
    auto found = state_buckets.find(state.locator);
    if (found != state_buckets.end()) {
      for (std::uint64_t candidate_id : found->second) {
        if (ExactStateRecordEqual(
                states[static_cast<std::size_t>(candidate_id)], state)) {
          return PersistentStateHandle(owner, candidate_id);
        }
      }
    }
    if (states.size() == std::numeric_limits<std::uint64_t>::max()) {
      throw std::overflow_error("persistent state handle space exhausted");
    }
    const std::uint64_t id = static_cast<std::uint64_t>(states.size());
    states.push_back(std::move(state));
    auto& bucket = state_buckets[states.back().locator];
    bucket.push_back(id);
    metrics.state_records = static_cast<std::uint64_t>(states.size() - 1U);
    metrics.maximum_state_locator_bucket =
        std::max(metrics.maximum_state_locator_bucket,
                 static_cast<std::uint64_t>(bucket.size()));
    return PersistentStateHandle(owner, id);
  }
};

PersistentStateArena::PersistentStateArena(PersistentArenaConfig config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}

PersistentStateArena::~PersistentStateArena() = default;

BoardHandle PersistentStateArena::InternBoard(const PackedBoard& board) {
  ValidatePackedBoard(board);
  const std::string material = BoardLocatorMaterial(board);
  const LocatorDigest256 locator = impl_->board_locator(material);
  auto found = impl_->board_buckets.find(locator);
  if (found != impl_->board_buckets.end()) {
    for (std::uint64_t candidate_id : found->second) {
      const Impl::BoardRecord& candidate =
          impl_->boards[static_cast<std::size_t>(candidate_id)];
      if (ExactPackedBoardEqual(candidate.value, board)) {
        return BoardHandle(impl_->owner, candidate_id);
      }
    }
  }
  if (impl_->boards.size() == std::numeric_limits<std::uint64_t>::max()) {
    throw std::overflow_error("persistent board handle space exhausted");
  }
  const std::uint64_t id = static_cast<std::uint64_t>(impl_->boards.size());
  impl_->boards.push_back({board, locator});
  auto& bucket = impl_->board_buckets[locator];
  bucket.push_back(id);
  impl_->metrics.board_records =
      static_cast<std::uint64_t>(impl_->boards.size() - 1U);
  impl_->metrics.maximum_board_locator_bucket =
      std::max(impl_->metrics.maximum_board_locator_bucket,
               static_cast<std::uint64_t>(bucket.size()));
  return BoardHandle(impl_->owner, id);
}

BoardHandle PersistentStateArena::InternBoard(
    int size, const std::vector<std::uint8_t>& cells) {
  return InternBoard(PackBoardExact(size, cells));
}

PackedBoard PersistentStateArena::BoardValue(BoardHandle board) const {
  return impl_->RequireBoard(board).value;
}

HistoryHandle PersistentStateArena::EmptyHistory(int board_size) {
  return HistoryHandle(impl_->owner, impl_->MakeEmptyRoot(board_size));
}

PersistentHistoryInsertResult PersistentStateArena::InsertHistory(
    HistoryHandle history, BoardHandle board) {
  const Impl::HistoryNode& root = impl_->RequireHistory(history);
  const Impl::BoardRecord& board_record = impl_->RequireBoard(board);
  if (root.board_size != board_record.value.size) {
    throw std::invalid_argument("history and board sizes do not match");
  }
  if (root.count == std::numeric_limits<std::uint64_t>::max()) {
    throw std::overflow_error("persistent history member count exceeds uint64");
  }
  bool inserted = false;
  const std::uint64_t next =
      impl_->InsertNode(history.index_, 0U, board.index_, inserted);
  if (inserted) {
    IncrementDiagnostic(impl_->metrics.successful_history_insertions);
  } else {
    IncrementDiagnostic(impl_->metrics.duplicate_history_insertions);
  }
  return {HistoryHandle(impl_->owner, next), inserted};
}

bool PersistentStateArena::HistoryContains(HistoryHandle history,
                                           BoardHandle board) const {
  const Impl::HistoryNode& root = impl_->RequireHistory(history);
  const Impl::BoardRecord& board_record = impl_->RequireBoard(board);
  if (root.board_size != board_record.value.size) {
    throw std::invalid_argument("history and board sizes do not match");
  }
  return impl_->ContainsNode(history.index_, 0U, board_record);
}

std::uint64_t PersistentStateArena::HistoryMemberCount(
    HistoryHandle history) const {
  return impl_->RequireHistory(history).count;
}

bool PersistentStateArena::ExactHistoryEqual(
    HistoryHandle left, const PersistentStateArena& right_arena,
    HistoryHandle right) const {
  const Impl::HistoryNode& left_root = impl_->RequireHistory(left);
  const Impl::HistoryNode& right_root =
      right_arena.impl_->RequireHistory(right);
  if (left_root.board_size != right_root.board_size ||
      left_root.count != right_root.count) {
    return false;
  }
  std::vector<std::uint64_t> left_ids;
  std::vector<std::uint64_t> right_ids;
  left_ids.reserve(static_cast<std::size_t>(left_root.count));
  right_ids.reserve(static_cast<std::size_t>(right_root.count));
  impl_->CollectBoardIds(left.index_, left_ids);
  right_arena.impl_->CollectBoardIds(right.index_, right_ids);
  auto left_less = [&](std::uint64_t first, std::uint64_t second) {
    return PackedBoardLess(
        impl_->boards[static_cast<std::size_t>(first)].value,
        impl_->boards[static_cast<std::size_t>(second)].value);
  };
  auto right_less = [&](std::uint64_t first, std::uint64_t second) {
    return PackedBoardLess(
        right_arena.impl_->boards[static_cast<std::size_t>(first)].value,
        right_arena.impl_->boards[static_cast<std::size_t>(second)].value);
  };
  std::sort(left_ids.begin(), left_ids.end(), left_less);
  std::sort(right_ids.begin(), right_ids.end(), right_less);
  for (std::size_t index = 0; index < left_ids.size(); ++index) {
    if (!ExactPackedBoardEqual(
            impl_->boards[static_cast<std::size_t>(left_ids[index])].value,
            right_arena.impl_
                ->boards[static_cast<std::size_t>(right_ids[index])]
                .value)) {
      return false;
    }
  }
  return true;
}

std::uint64_t PersistentStateArena::SharedHistoryNodeCount(
    HistoryHandle left, HistoryHandle right) const {
  static_cast<void>(impl_->RequireHistory(left));
  static_cast<void>(impl_->RequireHistory(right));
  std::set<std::uint64_t> left_nodes;
  std::set<std::uint64_t> right_nodes;
  impl_->CollectNodeIds(left.index_, left_nodes);
  impl_->CollectNodeIds(right.index_, right_nodes);
  std::uint64_t shared = 0;
  for (std::uint64_t node : left_nodes) {
    if (right_nodes.count(node) != 0U) ++shared;
  }
  return shared;
}

PersistentStateHandle PersistentStateArena::InternState(
    const PersistentStateView& state, const Rules& rules) {
  const Impl::BoardRecord& board = impl_->RequireBoard(state.board);
  const Impl::HistoryNode& history = impl_->RequireHistory(state.history);
  std::optional<std::uint64_t> previous;
  if (state.previous_board.has_value()) {
    static_cast<void>(impl_->RequireBoard(*state.previous_board));
    previous = state.previous_board->index_;
  }
  Impl::StateRecord record;
  record.board = state.board.index_;
  record.to_play = state.to_play;
  record.passes = state.passes;
  record.history = state.history.index_;
  record.previous_board = previous;
  record.ply = state.ply;
  if (board.value.size != history.board_size) {
    throw std::invalid_argument("persistent state board/history size mismatch");
  }
  return impl_->InternStateRecord(std::move(record), rules);
}

PersistentStateView PersistentStateArena::StateValue(
    PersistentStateHandle state) const {
  const Impl::StateRecord& record = impl_->RequireState(state);
  PersistentStateView result;
  result.board = BoardHandle(impl_->owner, record.board);
  result.to_play = record.to_play;
  result.passes = record.passes;
  result.history = HistoryHandle(impl_->owner, record.history);
  if (record.previous_board.has_value()) {
    result.previous_board = BoardHandle(impl_->owner, *record.previous_board);
  }
  result.ply = record.ply;
  return result;
}

bool PersistentStateArena::ExactStateEqual(
    PersistentStateHandle left, const Rules& left_rules,
    const PersistentStateArena& right_arena, PersistentStateHandle right,
    const Rules& right_rules) const {
  const Impl::StateRecord& left_state = impl_->RequireState(left);
  const Impl::StateRecord& right_state = right_arena.impl_->RequireState(right);
  impl_->ValidateStateRecord(left_state, left_rules);
  right_arena.impl_->ValidateStateRecord(right_state, right_rules);
  if (!RulesEqual(left_rules, right_rules) ||
      left_state.to_play != right_state.to_play ||
      left_state.passes != right_state.passes ||
      left_state.previous_board.has_value() !=
          right_state.previous_board.has_value()) {
    return false;
  }
  if (!ExactPackedBoardEqual(
          impl_->boards[static_cast<std::size_t>(left_state.board)].value,
          right_arena.impl_->boards[static_cast<std::size_t>(right_state.board)]
              .value)) {
    return false;
  }
  if (left_state.previous_board.has_value() &&
      !ExactPackedBoardEqual(
          impl_->boards[static_cast<std::size_t>(*left_state.previous_board)]
              .value,
          right_arena.impl_
              ->boards[static_cast<std::size_t>(*right_state.previous_board)]
              .value)) {
    return false;
  }
  return ExactHistoryEqual(
      HistoryHandle(impl_->owner, left_state.history), right_arena,
      HistoryHandle(right_arena.impl_->owner, right_state.history));
}

PersistentStateHandle PersistentStateArena::Initial(const Rules& rules) {
  ValidateRules(rules);
  const std::vector<std::uint8_t> empty(
      static_cast<std::size_t>(rules.size * rules.size), kEmpty);
  const BoardHandle board = InternBoard(rules.size, empty);
  const HistoryHandle empty_history = EmptyHistory(rules.size);
  const auto inserted = InsertHistory(empty_history, board);
  if (!inserted.inserted) {
    throw std::logic_error("initial board was already in an empty history");
  }
  return InternState({board, kBlack, 0U, inserted.history, std::nullopt, 0U},
                     rules);
}

PersistentApplyResult PersistentStateArena::ApplyMove(
    PersistentStateHandle state_handle, int move, const Rules& rules) {
  const Impl::StateRecord& stored = impl_->RequireState(state_handle);
  impl_->ValidateStateRecord(stored, rules);
  if (stored.passes >= static_cast<std::uint64_t>(rules.passes_to_end)) {
    throw IllegalMove("game is terminal");
  }
  const std::uint8_t next_player = Other(stored.to_play);
  if (move == kPass) {
    RequirePlyIncrementAvailable(stored.ply);
    Impl::StateRecord next = stored;
    next.to_play = next_player;
    ++next.passes;
    next.previous_board = stored.board;
    ++next.ply;
    next.locator = {};
    return {impl_->InternStateRecord(std::move(next), rules), 0, 0};
  }

  const Impl::BoardRecord& current =
      impl_->boards[static_cast<std::size_t>(stored.board)];
  std::vector<std::uint8_t> board = UnpackBoardExact(current.value);
  if (move < 0 || move >= static_cast<int>(board.size())) {
    throw IllegalMove("move outside board");
  }
  if (board[static_cast<std::size_t>(move)] != kEmpty) {
    throw IllegalMove("occupied point");
  }

  board[static_cast<std::size_t>(move)] = stored.to_play;
  int captured = 0;
  std::vector<std::uint8_t> checked(board.size(), 0U);
  for (int adjacent : Neighbors(move, rules.size)) {
    if (board[static_cast<std::size_t>(adjacent)] != next_player ||
        checked[static_cast<std::size_t>(adjacent)] != 0U) {
      continue;
    }
    auto group = GroupAndLiberties(board, adjacent, rules.size);
    for (int stone : group.first) checked[static_cast<std::size_t>(stone)] = 1U;
    if (group.second.empty()) {
      captured += static_cast<int>(group.first.size());
      for (int stone : group.first)
        board[static_cast<std::size_t>(stone)] = kEmpty;
    }
  }

  auto own_group = GroupAndLiberties(board, move, rules.size);
  int self_captured = 0;
  if (own_group.second.empty()) {
    if (!rules.allow_suicide) throw IllegalMove("suicide");
    self_captured = static_cast<int>(own_group.first.size());
    for (int stone : own_group.first)
      board[static_cast<std::size_t>(stone)] = kEmpty;
  }

  const BoardHandle next_board = InternBoard(rules.size, board);
  const HistoryHandle history(impl_->owner, stored.history);
  if (HistoryContains(history, next_board)) {
    throw IllegalMove("positional superko");
  }
  RequirePlyIncrementAvailable(stored.ply);
  const auto inserted = InsertHistory(history, next_board);
  if (!inserted.inserted) {
    throw std::logic_error(
        "legal board failed exact persistent-history insertion");
  }
  PersistentStateView next;
  next.board = next_board;
  next.to_play = next_player;
  next.passes = 0;
  next.history = inserted.history;
  next.previous_board = BoardHandle(impl_->owner, stored.board);
  next.ply = stored.ply + 1U;
  return {InternState(next, rules), captured, self_captured};
}

bool PersistentStateArena::IsLegal(PersistentStateHandle state, int move,
                                   const Rules& rules) {
  try {
    static_cast<void>(ApplyMove(state, move, rules));
    return true;
  } catch (const IllegalMove&) {
    return false;
  }
}

std::vector<int> PersistentStateArena::LegalMoves(
    PersistentStateHandle state_handle, const Rules& rules, bool include_pass) {
  // IsLegal interns exact candidate states and may reallocate the state arena,
  // so keep an immutable value copy rather than a reference into that vector.
  const Impl::StateRecord state = impl_->RequireState(state_handle);
  impl_->ValidateStateRecord(state, rules);
  std::vector<int> result;
  if (state.passes >= static_cast<std::uint64_t>(rules.passes_to_end)) {
    return result;
  }
  const std::vector<std::uint8_t> board = UnpackBoardExact(
      impl_->boards[static_cast<std::size_t>(state.board)].value);
  for (int point = 0; point < static_cast<int>(board.size()); ++point) {
    if (board[static_cast<std::size_t>(point)] == kEmpty &&
        IsLegal(state_handle, point, rules)) {
      result.push_back(point);
    }
  }
  if (include_pass) {
    RequirePlyIncrementAvailable(state.ply);
    result.push_back(kPass);
  }
  return result;
}

bool PersistentStateArena::Terminal(PersistentStateHandle state_handle,
                                    const Rules& rules) const {
  const Impl::StateRecord& state = impl_->RequireState(state_handle);
  impl_->ValidateStateRecord(state, rules);
  return state.passes >= static_cast<std::uint64_t>(rules.passes_to_end);
}

std::int64_t PersistentStateArena::AreaScore2(
    PersistentStateHandle state_handle, const Rules& rules) const {
  const Impl::StateRecord& state = impl_->RequireState(state_handle);
  impl_->ValidateStateRecord(state, rules);
  State flat;
  flat.size = rules.size;
  flat.board = UnpackBoardExact(
      impl_->boards[static_cast<std::size_t>(state.board)].value);
  flat.to_play = state.to_play;
  flat.passes = static_cast<int>(state.passes);
  // Scoring depends only on occupancy and rules. A one-member validating
  // history avoids reconstructing the complete PSK set here.
  flat.seen_boards = {flat.board};
  flat.ply = state.ply;
  return ugts_go19::AreaScore2(flat, rules);
}

PersistentStateHandle PersistentStateArena::ImportLegacy(const State& state,
                                                         const Rules& rules) {
  // Reject unsupported profiles before interning any adapter input.
  ValidateRules(rules);
  // Canonical serialization is the legacy implementation's complete public
  // validator. Its return value is deliberately unused.
  static_cast<void>(CanonicalStateJson(state, rules));
  HistoryHandle history = EmptyHistory(rules.size);
  for (const auto& seen : state.seen_boards) {
    const BoardHandle board = InternBoard(rules.size, seen);
    const auto inserted = InsertHistory(history, board);
    if (!inserted.inserted) {
      throw std::invalid_argument("legacy history contains an exact duplicate");
    }
    history = inserted.history;
  }
  PersistentStateView imported;
  imported.board = InternBoard(rules.size, state.board);
  imported.to_play = state.to_play;
  imported.passes = static_cast<std::uint64_t>(state.passes);
  imported.history = history;
  if (state.previous_board.has_value()) {
    imported.previous_board = InternBoard(rules.size, *state.previous_board);
  }
  imported.ply = state.ply;
  return InternState(imported, rules);
}

State PersistentStateArena::ExportLegacy(PersistentStateHandle state_handle,
                                         const Rules& rules) const {
  const Impl::StateRecord& state = impl_->RequireState(state_handle);
  impl_->ValidateStateRecord(state, rules);
  std::vector<std::uint64_t> board_ids;
  board_ids.reserve(static_cast<std::size_t>(
      impl_->nodes[static_cast<std::size_t>(state.history)].count));
  impl_->CollectBoardIds(state.history, board_ids);
  std::sort(board_ids.begin(), board_ids.end(),
            [&](std::uint64_t left, std::uint64_t right) {
              return PackedBoardLess(
                  impl_->boards[static_cast<std::size_t>(left)].value,
                  impl_->boards[static_cast<std::size_t>(right)].value);
            });
  State result;
  result.size = rules.size;
  result.board = UnpackBoardExact(
      impl_->boards[static_cast<std::size_t>(state.board)].value);
  result.to_play = state.to_play;
  result.passes = static_cast<int>(state.passes);
  result.seen_boards.reserve(board_ids.size());
  for (std::uint64_t board : board_ids) {
    result.seen_boards.push_back(
        UnpackBoardExact(impl_->boards[static_cast<std::size_t>(board)].value));
  }
  if (state.previous_board.has_value()) {
    result.previous_board = UnpackBoardExact(
        impl_->boards[static_cast<std::size_t>(*state.previous_board)].value);
  }
  result.ply = state.ply;
  static_cast<void>(CanonicalStateJson(result, rules));
  return result;
}

PersistentArenaMetrics PersistentStateArena::Metrics() const {
  return impl_->metrics;
}

}  // namespace ugts_go19
