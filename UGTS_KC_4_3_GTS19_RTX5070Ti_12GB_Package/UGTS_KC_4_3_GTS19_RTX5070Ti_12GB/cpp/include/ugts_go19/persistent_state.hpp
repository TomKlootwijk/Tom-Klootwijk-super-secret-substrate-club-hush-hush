#pragma once

#include "ugts_go19/go_state.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string_view>
#include <vector>

namespace ugts_go19 {

// A fixed-width locator. Locators select collision buckets only; none of the
// APIs below accept locator equality as proof of board, history, or state
// equality.
using LocatorDigest256 = std::array<std::uint8_t, 32>;
// Injected locators must be deterministic functions of canonical_material.
// Returning the same digest for every input is valid and explicitly tested.
using LocatorFunction =
    std::function<LocatorDigest256(std::string_view canonical_material)>;

struct PersistentArenaConfig {
  LocatorFunction board_locator;
  LocatorFunction history_locator;
  LocatorFunction state_locator;
};

// Exact packed occupancy for every supported board size. Unused words and
// unused high bits are required to be zero.
struct PackedBoard {
  std::uint8_t size = 0;
  std::array<std::uint64_t, 6> black{};
  std::array<std::uint64_t, 6> white{};
};

[[nodiscard]] bool ExactPackedBoardEqual(const PackedBoard& left,
                                         const PackedBoard& right) noexcept;
[[nodiscard]] PackedBoard PackBoardExact(
    int size, const std::vector<std::uint8_t>& cells);
[[nodiscard]] std::vector<std::uint8_t> UnpackBoardExact(
    const PackedBoard& board);

class PersistentStateArena;

// Handles deliberately expose no numeric value. A default-constructed handle,
// a handle from another arena, or a handle whose record is missing is rejected
// with an exception by every consuming API.
class BoardHandle {
 public:
  BoardHandle() = default;

 private:
  BoardHandle(std::uint64_t owner, std::uint64_t index)
      : owner_(owner), index_(index) {}
  std::uint64_t owner_ = 0;
  std::uint64_t index_ = 0;
  friend class PersistentStateArena;
};

class HistoryHandle {
 public:
  HistoryHandle() = default;

 private:
  HistoryHandle(std::uint64_t owner, std::uint64_t index)
      : owner_(owner), index_(index) {}
  std::uint64_t owner_ = 0;
  std::uint64_t index_ = 0;
  friend class PersistentStateArena;
};

class PersistentStateHandle {
 public:
  PersistentStateHandle() = default;

 private:
  PersistentStateHandle(std::uint64_t owner, std::uint64_t index)
      : owner_(owner), index_(index) {}
  std::uint64_t owner_ = 0;
  std::uint64_t index_ = 0;
  friend class PersistentStateArena;
};

struct PersistentStateView {
  BoardHandle board;
  std::uint8_t to_play = kBlack;
  std::uint64_t passes = 0;
  HistoryHandle history;
  std::optional<BoardHandle> previous_board;
  // Campaign metadata. It is stored and overflow-checked, but deliberately
  // excluded from exact semantic state equality.
  std::uint64_t ply = 0;
};

struct PersistentHistoryInsertResult {
  HistoryHandle history;
  bool inserted = false;
};

struct PersistentApplyResult {
  PersistentStateHandle state;
  int captured = 0;
  int self_captured = 0;
};

struct PersistentArenaMetrics {
  // Diagnostics only, never proof-authoritative. Event counters saturate at
  // uint64 max rather than wrapping.
  std::uint64_t board_records = 0;
  std::uint64_t history_nodes = 0;
  std::uint64_t state_records = 0;
  std::uint64_t successful_history_insertions = 0;
  std::uint64_t duplicate_history_insertions = 0;
  std::uint64_t path_node_copy_attempts = 0;
  std::uint64_t history_nodes_reused_by_interning = 0;
  std::uint64_t maximum_collision_leaf_members = 0;
  std::uint64_t maximum_board_locator_bucket = 0;
  std::uint64_t maximum_history_locator_bucket = 0;
  std::uint64_t maximum_state_locator_bucket = 0;
};

// Single-writer, in-memory validation foundation for complete
// positional-superko states. Its vectors/maps have no configured memory bound.
// Rule-bearing operations require suicide-illegal play and exactly two passes
// to terminate, which is the rank-safe profile supported by this sibling path.
// This class intentionally has no disk, paging, checkpoint, or proof status
// behavior. Allocation failure is not transactional: after std::bad_alloc or
// std::length_error escapes a mutating call, discard the whole arena and every
// handle from it rather than attempting to continue proof-authoritative work.
class PersistentStateArena {
 public:
  explicit PersistentStateArena(PersistentArenaConfig config = {});
  ~PersistentStateArena();
  PersistentStateArena(const PersistentStateArena&) = delete;
  PersistentStateArena& operator=(const PersistentStateArena&) = delete;
  PersistentStateArena(PersistentStateArena&&) = delete;
  PersistentStateArena& operator=(PersistentStateArena&&) = delete;

  [[nodiscard]] BoardHandle InternBoard(const PackedBoard& board);
  [[nodiscard]] BoardHandle InternBoard(int size,
                                        const std::vector<std::uint8_t>& cells);
  [[nodiscard]] PackedBoard BoardValue(BoardHandle board) const;

  [[nodiscard]] HistoryHandle EmptyHistory(int board_size);
  [[nodiscard]] PersistentHistoryInsertResult InsertHistory(
      HistoryHandle history, BoardHandle board);
  [[nodiscard]] bool HistoryContains(HistoryHandle history,
                                     BoardHandle board) const;
  [[nodiscard]] std::uint64_t HistoryMemberCount(HistoryHandle history) const;
  [[nodiscard]] bool ExactHistoryEqual(HistoryHandle left,
                                       const PersistentStateArena& right_arena,
                                       HistoryHandle right) const;

  // Diagnostic structural-sharing count. This counts immutable trie node
  // identities shared by two roots in this arena; it is not semantic equality
  // and is the only API that intentionally observes handle identity.
  [[nodiscard]] std::uint64_t SharedHistoryNodeCount(HistoryHandle left,
                                                     HistoryHandle right) const;

  [[nodiscard]] PersistentStateHandle InternState(
      const PersistentStateView& state, const Rules& rules);
  [[nodiscard]] PersistentStateView StateValue(
      PersistentStateHandle state) const;
  [[nodiscard]] bool ExactStateEqual(PersistentStateHandle left,
                                     const Rules& left_rules,
                                     const PersistentStateArena& right_arena,
                                     PersistentStateHandle right,
                                     const Rules& right_rules) const;

  [[nodiscard]] PersistentStateHandle Initial(const Rules& rules);
  [[nodiscard]] PersistentApplyResult ApplyMove(PersistentStateHandle state,
                                                int move, const Rules& rules);
  [[nodiscard]] bool IsLegal(PersistentStateHandle state, int move,
                             const Rules& rules);
  [[nodiscard]] std::vector<int> LegalMoves(PersistentStateHandle state,
                                            const Rules& rules,
                                            bool include_pass = true);
  [[nodiscard]] bool Terminal(PersistentStateHandle state,
                              const Rules& rules) const;
  [[nodiscard]] std::int64_t AreaScore2(PersistentStateHandle state,
                                        const Rules& rules) const;

  // Differential-oracle adapters. Export is the only transition-adjacent API
  // that materializes a flat complete history.
  [[nodiscard]] PersistentStateHandle ImportLegacy(const State& state,
                                                   const Rules& rules);
  [[nodiscard]] State ExportLegacy(PersistentStateHandle state,
                                   const Rules& rules) const;

  [[nodiscard]] PersistentArenaMetrics Metrics() const;

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

// rank = 2 * member_count + passes, with no unsigned wraparound.
[[nodiscard]] std::uint64_t CheckedPersistentRank(std::uint64_t member_count,
                                                  std::uint64_t passes);

}  // namespace ugts_go19
