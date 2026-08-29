#include "ugts_go19/persistent_state.hpp"

#include <algorithm>
#include <cstdint>
#include <functional>
#include <iostream>
#include <iterator>
#include <limits>
#include <random>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

using ugts_go19::ApplyMove;
using ugts_go19::BoardHandle;
using ugts_go19::CanonicalStateJson;
using ugts_go19::CheckedPersistentRank;
using ugts_go19::ExactPackedBoardEqual;
using ugts_go19::HistoryHandle;
using ugts_go19::IllegalMove;
using ugts_go19::kBlack;
using ugts_go19::kEmpty;
using ugts_go19::kPass;
using ugts_go19::kWhite;
using ugts_go19::LocatorDigest256;
using ugts_go19::PackBoardExact;
using ugts_go19::PackedBoard;
using ugts_go19::PersistentArenaConfig;
using ugts_go19::PersistentStateArena;
using ugts_go19::PersistentStateHandle;
using ugts_go19::PersistentStateView;
using ugts_go19::Rules;
using ugts_go19::State;
using ugts_go19::UnpackBoardExact;

void Require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

template <typename Exception, typename Callback>
void RequireThrows(Callback&& callback, std::string_view message_fragment,
                   const std::string& failure) {
  try {
    callback();
  } catch (const Exception& error) {
    if (std::string(error.what()).find(message_fragment) == std::string::npos) {
      throw std::runtime_error(failure +
                               ": unexpected message: " + error.what());
    }
    return;
  }
  throw std::runtime_error(failure + ": no exception");
}

Rules TestRules(int size) {
  Rules rules;
  rules.size = size;
  rules.komi2 = size == 19 ? 15 : 1;
  rules.allow_suicide = false;
  rules.passes_to_end = 2;
  return rules;
}

std::vector<std::uint8_t> WithStone(int size, int point,
                                    std::uint8_t color = kBlack) {
  std::vector<std::uint8_t> board(static_cast<std::size_t>(size * size),
                                  kEmpty);
  board[static_cast<std::size_t>(point)] = color;
  return board;
}

void RequireParity(PersistentStateArena& arena,
                   PersistentStateHandle persistent, const State& flat,
                   const Rules& rules, const std::string& label) {
  const State exported = arena.ExportLegacy(persistent, rules);
  Require(exported.ply == flat.ply, label + ": ply metadata mismatch");
  Require(
      CanonicalStateJson(exported, rules) == CanonicalStateJson(flat, rules),
      label + ": exact legacy state mismatch");
  Require(ugts_go19::ExactStateEqual(exported, rules, flat, rules),
          label + ": semantic legacy equality mismatch");
  Require(
      arena.AreaScore2(persistent, rules) == ugts_go19::AreaScore2(flat, rules),
      label + ": area score mismatch");
  Require(arena.Terminal(persistent, rules) == flat.Terminal(rules),
          label + ": terminal mismatch");
}

void ApplyParity(PersistentStateArena& arena, PersistentStateHandle& persistent,
                 State& flat, int move, const Rules& rules,
                 const std::string& label) {
  const PersistentStateView before = arena.StateValue(persistent);
  const std::uint64_t before_members = arena.HistoryMemberCount(before.history);
  const std::uint64_t before_rank =
      CheckedPersistentRank(before_members, before.passes);
  const auto persistent_result = arena.ApplyMove(persistent, move, rules);
  const auto flat_result = ApplyMove(flat, move, rules);
  Require(persistent_result.captured == flat_result.captured,
          label + ": capture count mismatch");
  Require(persistent_result.self_captured == flat_result.self_captured,
          label + ": self-capture count mismatch");
  persistent = persistent_result.state;
  flat = flat_result.state;
  const PersistentStateView after = arena.StateValue(persistent);
  const std::uint64_t after_members = arena.HistoryMemberCount(after.history);
  const std::uint64_t after_rank =
      CheckedPersistentRank(after_members, after.passes);
  Require(after_rank > before_rank, label + ": rank did not increase");
  if (move == kPass) {
    Require(after_members == before_members && after_rank == before_rank + 1U,
            label + ": pass rank/history delta mismatch");
  } else {
    Require(after_members == before_members + 1U && after.passes == 0U,
            label + ": point-move history/pass delta mismatch");
    Require(after_rank == before_rank + 2U - before.passes,
            label + ": point-move rank delta mismatch");
  }
  RequireParity(arena, persistent, flat, rules, label);
}

void TestPackedBoardsAllSizesAndMalformedInputs() {
  PersistentStateArena arena;
  for (int size = 1; size <= 19; ++size) {
    std::vector<std::uint8_t> cells(static_cast<std::size_t>(size * size),
                                    kEmpty);
    for (std::size_t point = 0; point < cells.size(); ++point) {
      cells[point] = static_cast<std::uint8_t>((point * 2U + 1U) % 3U);
    }
    const std::vector<std::size_t> word_boundaries = {
        63U, 64U, 127U, 128U, 191U, 192U, 255U, 256U, 319U, 320U};
    for (std::size_t index = 0; index < word_boundaries.size(); ++index) {
      const std::size_t point = word_boundaries[index];
      if (point < cells.size()) {
        cells[point] = index % 2U == 0U ? kBlack : kWhite;
      }
    }
    const PackedBoard packed = PackBoardExact(size, cells);
    Require(UnpackBoardExact(packed) == cells,
            "packed board round-trip failed at size " + std::to_string(size));
    const BoardHandle first = arena.InternBoard(packed);
    const BoardHandle duplicate = arena.InternBoard(size, cells);
    Require(ExactPackedBoardEqual(arena.BoardValue(first),
                                  arena.BoardValue(duplicate)),
            "board interning changed exact content");

    std::vector<std::uint8_t> short_cells = cells;
    short_cells.pop_back();
    RequireThrows<std::invalid_argument>(
        [&] { static_cast<void>(PackBoardExact(size, short_cells)); },
        "does not match",
        "short packed board accepted at size " + std::to_string(size));
    std::vector<std::uint8_t> invalid_cells = cells;
    invalid_cells[invalid_cells.size() / 2U] = 3U;
    RequireThrows<std::invalid_argument>(
        [&] { static_cast<void>(PackBoardExact(size, invalid_cells)); },
        "invalid point",
        "invalid packed point accepted at size " + std::to_string(size));

    PackedBoard overlap = packed;
    overlap.black[0] |= 1U;
    overlap.white[0] |= 1U;
    RequireThrows<std::invalid_argument>(
        [&] { static_cast<void>(arena.InternBoard(overlap)); }, "overlap",
        "overlapping bitplanes accepted at size " + std::to_string(size));

    const std::size_t points = cells.size();
    const std::size_t words = (points + 63U) / 64U;
    const std::size_t tail_bits = points % 64U;
    if (tail_bits != 0U) {
      PackedBoard dirty_tail = packed;
      dirty_tail.black[words - 1U] |= 1ULL << tail_bits;
      RequireThrows<std::invalid_argument>(
          [&] { static_cast<void>(arena.InternBoard(dirty_tail)); },
          "tail bits",
          "dirty packed tail accepted at size " + std::to_string(size));
    }
    if (words < packed.black.size()) {
      PackedBoard dirty_word = packed;
      dirty_word.white[words] = 1U;
      RequireThrows<std::invalid_argument>(
          [&] { static_cast<void>(arena.InternBoard(dirty_word)); },
          "unused words",
          "dirty unused word accepted at size " + std::to_string(size));
    }
  }
  Require(arena.Metrics().board_records == 19U,
          "exact duplicate boards were not interned");

  RequireThrows<std::invalid_argument>(
      [] { static_cast<void>(PackBoardExact(0, {})); }, "1..19",
      "zero board size accepted");
  RequireThrows<std::invalid_argument>(
      [] { static_cast<void>(PackBoardExact(20, {})); }, "1..19",
      "oversized board accepted");
}

void TestFixedSeedFlatParityAllSizes() {
  std::mt19937_64 randomizer(0x19C0FFEEBADC0DEULL);
  for (int size = 1; size <= 19; ++size) {
    const Rules rules = TestRules(size);
    PersistentStateArena arena;
    PersistentStateHandle persistent = arena.Initial(rules);
    State flat = State::Initial(rules);
    RequireParity(arena, persistent, flat, rules,
                  "initial size " + std::to_string(size));

    const int point_plies = size == 19 ? 4 : (size >= 9 ? 6 : 10);
    for (int ply = 0; ply < point_plies && !flat.Terminal(rules); ++ply) {
      const std::vector<int> persistent_moves =
          arena.LegalMoves(persistent, rules, true);
      const std::vector<int> flat_moves =
          ugts_go19::LegalMoves(flat, rules, true);
      Require(persistent_moves == flat_moves,
              "legal move list mismatch at size " + std::to_string(size));
      std::vector<int> points;
      std::copy_if(flat_moves.begin(), flat_moves.end(),
                   std::back_inserter(points),
                   [](int move) { return move != kPass; });
      const int move =
          points.empty()
              ? kPass
              : points[static_cast<std::size_t>(randomizer() % points.size())];
      ApplyParity(arena, persistent, flat, move, rules,
                  "fixed trace size " + std::to_string(size));
    }

    while (!flat.Terminal(rules)) {
      ApplyParity(arena, persistent, flat, kPass, rules,
                  "terminal pass size " + std::to_string(size));
    }
    Require(arena.LegalMoves(persistent, rules, true).empty(),
            "terminal persistent state exposed moves");
    RequireThrows<IllegalMove>(
        [&] { static_cast<void>(arena.ApplyMove(persistent, kPass, rules)); },
        "terminal", "persistent move after terminal accepted");
  }
}

void TestCaptureSuicideKoSnapbackAndPoisonedPsk() {
  const Rules rules = TestRules(3);
  PersistentStateArena arena;

  State capture;
  capture.size = 3;
  capture.board = {0, 0, 0, kWhite, kBlack, kWhite, 0, kWhite, 0};
  capture.to_play = kWhite;
  capture.seen_boards = {std::vector<std::uint8_t>(9, 0), capture.board};
  capture.ply = 8;
  PersistentStateHandle persistent_capture = arena.ImportLegacy(capture, rules);
  const auto persistent_result = arena.ApplyMove(persistent_capture, 1, rules);
  const auto flat_result = ApplyMove(capture, 1, rules);
  Require(persistent_result.captured == 1 && flat_result.captured == 1,
          "focused single capture did not capture one stone");
  RequireParity(arena, persistent_result.state, flat_result.state, rules,
                "focused capture");

  State multi_capture;
  multi_capture.size = 3;
  multi_capture.board = {kBlack, kWhite, kBlack, kWhite, 0, 0, kBlack, 0, 0};
  multi_capture.to_play = kBlack;
  multi_capture.seen_boards = {multi_capture.board};
  const PersistentStateHandle persistent_multi_capture =
      arena.ImportLegacy(multi_capture, rules);
  const auto persistent_multi_result =
      arena.ApplyMove(persistent_multi_capture, 4, rules);
  const auto flat_multi_result = ApplyMove(multi_capture, 4, rules);
  Require(
      persistent_multi_result.captured == 2 && flat_multi_result.captured == 2,
      "simultaneous capture of two distinct groups did not capture both");
  RequireParity(arena, persistent_multi_result.state, flat_multi_result.state,
                rules, "simultaneous distinct-group capture");

  State suicide;
  suicide.size = 3;
  suicide.board = {0, kWhite, 0, kWhite, 0, kWhite, 0, kWhite, 0};
  suicide.to_play = kBlack;
  suicide.seen_boards = {suicide.board};
  const PersistentStateHandle persistent_suicide =
      arena.ImportLegacy(suicide, rules);
  Require(!arena.IsLegal(persistent_suicide, 4, rules),
          "persistent suicide was legal");
  Require(!ugts_go19::IsLegal(suicide, 4, rules),
          "legacy suicide fixture was legal");
  RequireThrows<IllegalMove>(
      [&] { static_cast<void>(arena.ApplyMove(persistent_suicide, 4, rules)); },
      "suicide", "persistent suicide did not fail exactly");

  State poisoned = State::Initial(rules);
  poisoned.seen_boards.push_back(WithStone(3, 0));
  const PersistentStateHandle persistent_poisoned =
      arena.ImportLegacy(poisoned, rules);
  Require(!arena.IsLegal(persistent_poisoned, 0, rules),
          "poisoned persistent PSK move was legal");
  Require(!ugts_go19::IsLegal(poisoned, 0, rules),
          "poisoned legacy PSK fixture was legal");
  RequireThrows<IllegalMove>(
      [&] {
        static_cast<void>(arena.ApplyMove(persistent_poisoned, 0, rules));
      },
      "positional superko", "persistent PSK rejection was not exact");

  PersistentStateArena snapback_arena;
  PersistentStateHandle snapback = snapback_arena.Initial(rules);
  State flat_snapback = State::Initial(rules);
  for (int move : {0, 3, 5, 4, 7, 2}) {
    ApplyParity(snapback_arena, snapback, flat_snapback, move, rules,
                "reachable snapback setup");
  }
  auto snapback_capture = snapback_arena.ApplyMove(snapback, 1, rules);
  auto flat_snapback_capture = ApplyMove(flat_snapback, 1, rules);
  Require(snapback_capture.captured == 1 && flat_snapback_capture.captured == 1,
          "reachable snapback first capture mismatch");
  auto snapback_recapture =
      snapback_arena.ApplyMove(snapback_capture.state, 2, rules);
  auto flat_snapback_recapture =
      ApplyMove(flat_snapback_capture.state, 2, rules);
  Require(
      snapback_recapture.captured == 2 && flat_snapback_recapture.captured == 2,
      "reachable snapback recapture mismatch");
  RequireParity(snapback_arena, snapback_recapture.state,
                flat_snapback_recapture.state, rules, "reachable snapback");

  const Rules ko_rules = TestRules(5);
  PersistentStateArena ko_arena;
  PersistentStateHandle ko = ko_arena.Initial(ko_rules);
  State flat_ko = State::Initial(ko_rules);
  for (int move : {1, 2, 3, 6, 20, 8, 24, 12, 7}) {
    ApplyParity(ko_arena, ko, flat_ko, move, ko_rules, "reachable ko setup");
  }
  Require(!ko_arena.IsLegal(ko, 2, ko_rules),
          "persistent reachable ko recapture was legal");
  Require(!ugts_go19::IsLegal(flat_ko, 2, ko_rules),
          "legacy reachable ko recapture was legal");
}

LocatorDigest256 ConstantLocator(std::string_view) {
  return LocatorDigest256{};
}

void TestAllLocatorCollisionsAndCanonicalSetEquality() {
  PersistentArenaConfig collision_config;
  collision_config.board_locator = ConstantLocator;
  collision_config.history_locator = ConstantLocator;
  collision_config.state_locator = ConstantLocator;
  PersistentStateArena collision_arena(collision_config);
  const Rules rules = TestRules(2);
  const std::vector<std::uint8_t> empty(4, kEmpty);
  const auto black0 = WithStone(2, 0, kBlack);
  const auto white3 = WithStone(2, 3, kWhite);
  const BoardHandle empty_handle = collision_arena.InternBoard(2, empty);
  const BoardHandle black_handle = collision_arena.InternBoard(2, black0);
  const BoardHandle white_handle = collision_arena.InternBoard(2, white3);

  auto make_history = [&](const std::vector<BoardHandle>& order) {
    HistoryHandle history = collision_arena.EmptyHistory(2);
    for (BoardHandle board : order) {
      const auto result = collision_arena.InsertHistory(history, board);
      Require(result.inserted,
              "collision history unexpectedly duplicated board");
      history = result.history;
    }
    return history;
  };
  const HistoryHandle forward =
      make_history({empty_handle, black_handle, white_handle});
  const HistoryHandle reverse =
      make_history({white_handle, black_handle, empty_handle});
  const HistoryHandle smaller = make_history({black_handle, empty_handle});
  Require(collision_arena.ExactHistoryEqual(forward, collision_arena, reverse),
          "insertion order changed exact set equality under collisions");
  Require(!collision_arena.ExactHistoryEqual(forward, collision_arena, smaller),
          "constant history locator conflated different exact sets");
  Require(collision_arena.HistoryContains(forward, white_handle),
          "full-depth collision leaf lost an exact member");
  Require(!collision_arena.HistoryContains(smaller, white_handle),
          "full-depth collision leaf created a false member");

  const PersistentStateView base{black_handle, kWhite,       0U,
                                 forward,      empty_handle, 4U};
  const PersistentStateHandle first = collision_arena.InternState(base, rules);
  const std::uint64_t records_before_equivalent =
      collision_arena.Metrics().state_records;
  PersistentStateView canonical_duplicate = base;
  canonical_duplicate.history = reverse;
  const PersistentStateHandle second =
      collision_arena.InternState(canonical_duplicate, rules);
  Require(collision_arena.Metrics().state_records == records_before_equivalent,
          "canonical insertion order produced a distinct stored state");
  Require(collision_arena.ExactStateEqual(first, rules, collision_arena, second,
                                          rules),
          "constant state locator changed exact state equality");

  PersistentStateView metadata_only = base;
  metadata_only.ply = 99U;
  const std::uint64_t records_before_metadata =
      collision_arena.Metrics().state_records;
  const PersistentStateHandle different_ply =
      collision_arena.InternState(metadata_only, rules);
  Require(
      collision_arena.Metrics().state_records == records_before_metadata + 1U &&
          collision_arena.StateValue(first).ply == 4U &&
          collision_arena.StateValue(different_ply).ply == 99U,
      "ply-distinct campaign records were conflated by state interning");
  Require(collision_arena.ExactStateEqual(first, rules, collision_arena,
                                          different_ply, rules),
          "ply metadata affected semantic state equality");

  PersistentStateView different_history = base;
  different_history.history = smaller;
  const PersistentStateHandle smaller_state =
      collision_arena.InternState(different_history, rules);
  Require(!collision_arena.ExactStateEqual(first, rules, collision_arena,
                                           smaller_state, rules),
          "constant state locator conflated different history roots");
  Require(collision_arena.ExportLegacy(first, rules).seen_boards.size() == 3U &&
              collision_arena.ExportLegacy(smaller_state, rules)
                      .seen_boards.size() == 2U,
          "collision state records did not preserve distinct histories");

  const auto metrics = collision_arena.Metrics();
  Require(metrics.maximum_board_locator_bucket == 3U,
          "forced board locator collision bucket was not exercised");
  Require(metrics.maximum_collision_leaf_members == 3U,
          "exact full-depth collision leaf was not exercised");
  Require(metrics.maximum_history_locator_bucket > 32U,
          "forced history-node locator collision bucket was not exercised");
  Require(metrics.maximum_state_locator_bucket >= 3U,
          "forced state locator collision bucket was not exercised");

  PersistentStateArena other;
  const BoardHandle other_white = other.InternBoard(2, white3);
  const BoardHandle other_black = other.InternBoard(2, black0);
  const BoardHandle other_empty = other.InternBoard(2, empty);
  HistoryHandle other_history = other.EmptyHistory(2);
  for (BoardHandle board : {other_white, other_empty, other_black}) {
    other_history = other.InsertHistory(other_history, board).history;
  }
  Require(collision_arena.ExactHistoryEqual(forward, other, other_history),
          "different arenas/digests changed exact set equality");
  const PersistentStateHandle other_state = other.InternState(
      {other_black, kWhite, 0U, other_history, other_empty, 123U}, rules);
  Require(
      collision_arena.ExactStateEqual(first, rules, other, other_state, rules),
      "different arenas/digests changed exact state equality");
}

void TestStructuralSharingMetricsAndOnePassRankPlacement() {
  PersistentArenaConfig config;
  config.board_locator = [](std::string_view material) {
    LocatorDigest256 digest{};
    std::uint8_t sum = 0;
    for (unsigned char byte : material) {
      sum = static_cast<std::uint8_t>(sum + byte);
    }
    digest[0] = sum;
    digest[31] = static_cast<std::uint8_t>(sum ^ 0xa5U);
    return digest;
  };
  PersistentStateArena arena(config);
  const Rules rules = TestRules(2);
  const BoardHandle empty =
      arena.InternBoard(2, std::vector<std::uint8_t>(4, 0));
  const BoardHandle stone = arena.InternBoard(2, WithStone(2, 0));
  HistoryHandle history = arena.EmptyHistory(2);
  history = arena.InsertHistory(history, empty).history;
  const HistoryHandle before = history;
  history = arena.InsertHistory(history, stone).history;
  Require(arena.HistoryMemberCount(before) == 1U &&
              arena.HistoryMemberCount(history) == 2U,
          "path copy mutated an older history root");
  Require(!arena.HistoryContains(before, stone) &&
              arena.HistoryContains(history, stone),
          "path copy did not preserve immutable root membership");
  Require(arena.SharedHistoryNodeCount(before, history) == 32U,
          "radix insertion did not share the untouched 32-node subtree");
  const auto metrics = arena.Metrics();
  Require(metrics.successful_history_insertions == 2U &&
              metrics.path_node_copy_attempts == 66U &&
              metrics.history_nodes == 67U,
          "32-level radix path-copy metrics changed");

  PersistentStateArena rank_arena;
  PersistentStateHandle persistent = rank_arena.Initial(rules);
  State flat = State::Initial(rules);
  const auto initial_view = rank_arena.StateValue(persistent);
  const std::uint64_t initial_rank = CheckedPersistentRank(
      rank_arena.HistoryMemberCount(initial_view.history), initial_view.passes);
  ApplyParity(rank_arena, persistent, flat, kPass, rules,
              "rank after one pass");
  const auto passed_view = rank_arena.StateValue(persistent);
  const std::uint64_t passed_rank = CheckedPersistentRank(
      rank_arena.HistoryMemberCount(passed_view.history), passed_view.passes);
  Require(passed_rank == initial_rank + 1U,
          "one pass did not place rank at 2H+1");
  ApplyParity(rank_arena, persistent, flat, 0, rules,
              "regular move after one pass");
  const auto moved_view = rank_arena.StateValue(persistent);
  const std::uint64_t moved_rank = CheckedPersistentRank(
      rank_arena.HistoryMemberCount(moved_view.history), moved_view.passes);
  Require(moved_rank == passed_rank + 1U,
          "regular move after one pass did not place rank at 2(H+1)");

  // With a noncanonical three-pass threshold, H=1/passes=2 is nonterminal,
  // but a legal placement produces H=2/passes=0 at the same rank. The native
  // persistent slice rejects that profile instead of admitting a non-acyclic
  // placement edge.
  Rules three_pass_rules = rules;
  three_pass_rules.passes_to_end = 3;
  State h1_passes2 = State::Initial(three_pass_rules);
  h1_passes2 = ApplyMove(h1_passes2, kPass, three_pass_rules).state;
  h1_passes2 = ApplyMove(h1_passes2, kPass, three_pass_rules).state;
  const State h2_passes0 = ApplyMove(h1_passes2, 0, three_pass_rules).state;
  Require(h1_passes2.seen_boards.size() == 1U && h1_passes2.passes == 2 &&
              h2_passes0.seen_boards.size() == 2U && h2_passes0.passes == 0 &&
              CheckedPersistentRank(1U, 2U) == CheckedPersistentRank(2U, 0U),
          "three-pass rank-collision regression fixture changed");
  PersistentStateArena rejected_profile_arena;
  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(
            rejected_profile_arena.ImportLegacy(h1_passes2, three_pass_rules));
      },
      "exactly two passes",
      "rank-nonmonotonic three-pass adapter input was accepted");
  const auto rejected_metrics = rejected_profile_arena.Metrics();
  Require(rejected_metrics.board_records == 0U &&
              rejected_metrics.history_nodes == 0U &&
              rejected_metrics.state_records == 0U,
          "unsupported rules mutated the arena before rejection");
}

void TestSemanticEqualityDistinctions() {
  const Rules rules = TestRules(2);
  PersistentStateArena arena;
  const BoardHandle empty =
      arena.InternBoard(2, std::vector<std::uint8_t>(4, 0));
  const BoardHandle stone = arena.InternBoard(2, WithStone(2, 0));
  const BoardHandle extra = arena.InternBoard(2, WithStone(2, 3, kWhite));
  HistoryHandle history = arena.EmptyHistory(2);
  history = arena.InsertHistory(history, empty).history;
  history = arena.InsertHistory(history, stone).history;
  HistoryHandle longer = arena.InsertHistory(history, extra).history;
  const PersistentStateHandle base =
      arena.InternState({stone, kWhite, 0U, history, empty, 7U}, rules);

  const PersistentStateHandle history_difference =
      arena.InternState({stone, kWhite, 0U, longer, empty, 7U}, rules);
  Require(!arena.ExactStateEqual(base, rules, arena, history_difference, rules),
          "different complete PSK histories compared equal");

  const PersistentStateHandle previous_difference =
      arena.InternState({stone, kWhite, 0U, history, stone, 7U}, rules);
  Require(
      !arena.ExactStateEqual(base, rules, arena, previous_difference, rules),
      "different previous boards compared equal");
  const PersistentStateHandle no_previous =
      arena.InternState({stone, kWhite, 0U, history, std::nullopt, 7U}, rules);
  Require(!arena.ExactStateEqual(base, rules, arena, no_previous, rules),
          "absent previous board compared equal to present previous board");

  const PersistentStateHandle pass_difference =
      arena.InternState({stone, kWhite, 1U, history, empty, 7U}, rules);
  Require(!arena.ExactStateEqual(base, rules, arena, pass_difference, rules),
          "different pass counts compared equal");
  const PersistentStateHandle player_difference =
      arena.InternState({stone, kBlack, 0U, history, empty, 7U}, rules);
  Require(!arena.ExactStateEqual(base, rules, arena, player_difference, rules),
          "different players compared equal");

  Rules different_komi = rules;
  different_komi.komi2 = 3;
  Require(!arena.ExactStateEqual(base, rules, arena, base, different_komi),
          "different komi rules compared equal");
  Rules different_suicide = rules;
  different_suicide.allow_suicide = true;
  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(
            arena.ExactStateEqual(base, rules, arena, base, different_suicide));
      },
      "suicide to be illegal", "suicide-enabled profile was accepted");
  PersistentStateArena unsupported_profile_arena;
  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(unsupported_profile_arena.Initial(different_suicide));
      },
      "suicide to be illegal",
      "suicide-enabled initial persistent state was accepted");
  Rules different_terminal = rules;
  different_terminal.passes_to_end = 3;
  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(arena.ExactStateEqual(base, rules, arena, base,
                                                different_terminal));
      },
      "exactly two passes", "three-pass profile was accepted");
}

void TestMalformedHandlesStateAndNumericGuards() {
  const Rules rules = TestRules(2);
  PersistentStateArena arena;
  PersistentStateArena foreign;
  const BoardHandle board =
      arena.InternBoard(2, std::vector<std::uint8_t>(4, 0));
  const BoardHandle foreign_board =
      foreign.InternBoard(2, std::vector<std::uint8_t>(4, 0));
  HistoryHandle history = arena.EmptyHistory(2);
  history = arena.InsertHistory(history, board).history;

  RequireThrows<std::invalid_argument>(
      [&] { static_cast<void>(arena.BoardValue(BoardHandle{})); }, "invalid",
      "default board handle accepted");
  RequireThrows<std::invalid_argument>(
      [&] { static_cast<void>(arena.BoardValue(foreign_board)); },
      "another arena", "foreign board handle accepted");
  RequireThrows<std::invalid_argument>(
      [&] { static_cast<void>(arena.HistoryMemberCount(HistoryHandle{})); },
      "invalid", "default history handle accepted");
  RequireThrows<std::invalid_argument>(
      [&] { static_cast<void>(arena.StateValue(PersistentStateHandle{})); },
      "invalid", "default state handle accepted");
  RequireThrows<std::invalid_argument>(
      [&] { static_cast<void>(arena.InsertHistory(history, foreign_board)); },
      "another arena", "foreign board inserted into history");

  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(arena.InternState(
            {board, 7U, 0U, history, std::nullopt, 0U}, rules));
      },
      "invalid player", "invalid persistent player accepted");
  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(arena.InternState(
            {board, kBlack, 3U, history, std::nullopt, 0U}, rules));
      },
      "exceeds", "excessive persistent pass count accepted");

  const BoardHandle stone = arena.InternBoard(2, WithStone(2, 0));
  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(arena.InternState(
            {stone, kBlack, 0U, history, std::nullopt, 0U}, rules));
      },
      "current board", "state with incomplete current history accepted");
  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(
            arena.InternState({board, kBlack, 0U, history, stone, 0U}, rules));
      },
      "previous board", "state with incomplete previous history accepted");

  const std::uint64_t maximum = std::numeric_limits<std::uint64_t>::max();
  Require(CheckedPersistentRank(maximum / 2U, 1U) == maximum,
          "maximum valid persistent rank was rejected");
  RequireThrows<std::overflow_error>(
      [&] { static_cast<void>(CheckedPersistentRank(maximum / 2U, 2U)); },
      "rank", "persistent rank addition overflow accepted");
  RequireThrows<std::overflow_error>(
      [&] { static_cast<void>(CheckedPersistentRank(maximum / 2U + 1U, 0U)); },
      "rank", "persistent rank multiplication overflow accepted");

  State exhausted = State::Initial(rules);
  exhausted.ply = maximum;
  const PersistentStateHandle exhausted_handle =
      arena.ImportLegacy(exhausted, rules);
  RequireThrows<std::overflow_error>(
      [&] { static_cast<void>(arena.IsLegal(exhausted_handle, kPass, rules)); },
      "ply", "pass ply exhaustion was hidden as move illegality");
  RequireThrows<std::overflow_error>(
      [&] { static_cast<void>(arena.IsLegal(exhausted_handle, 0, rules)); },
      "ply", "point-move ply exhaustion was hidden as move illegality");

  State occupied = ApplyMove(State::Initial(rules), 0, rules).state;
  occupied.ply = maximum;
  const PersistentStateHandle occupied_handle =
      arena.ImportLegacy(occupied, rules);
  Require(!arena.IsLegal(occupied_handle, 0, rules),
          "ordinary occupied-point illegality changed at maximum ply");
}

}  // namespace

int main() {
  try {
    TestPackedBoardsAllSizesAndMalformedInputs();
    TestFixedSeedFlatParityAllSizes();
    TestCaptureSuicideKoSnapbackAndPoisonedPsk();
    TestAllLocatorCollisionsAndCanonicalSetEquality();
    TestStructuralSharingMetricsAndOnePassRankPlacement();
    TestSemanticEqualityDistinctions();
    TestMalformedHandlesStateAndNumericGuards();
    std::cout << "ugts_go_persistent_state_tests: ok; in-memory validation; "
                 "19x19 root UNKNOWN\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ugts_go_persistent_state_tests: " << error.what() << "\n";
    return 1;
  }
}
