#include "ugts_go19/go_state.hpp"

#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {

using ugts_go19::ApplyMove;
using ugts_go19::CanonicalStateJson;
using ugts_go19::ExactStateEqual;
using ugts_go19::IllegalMove;
using ugts_go19::IsLegal;
using ugts_go19::Rules;
using ugts_go19::State;
using ugts_go19::kBlack;
using ugts_go19::kPass;
using ugts_go19::kWhite;

void Require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

void TestRuleIllegalityReturnsFalse() {
  Rules rules;
  rules.size = 3;
  rules.komi2 = 1;

  const State initial = State::Initial(rules);
  const State occupied = ApplyMove(initial, 0, rules).state;
  Require(!IsLegal(occupied, 0, rules), "occupied move should be illegal");
  Require(!IsLegal(initial, -2, rules),
          "invalid negative move should be illegal");
  Require(!IsLegal(initial, 9, rules), "off-board move should be illegal");

  State suicide = State::Initial(rules);
  suicide.board = {
      0, kWhite, 0,
      kWhite, 0, kWhite,
      0, kWhite, 0,
  };
  suicide.to_play = kBlack;
  suicide.seen_boards = {suicide.board};
  Require(!IsLegal(suicide, 4, rules), "suicide should be illegal");

  const State candidate = ApplyMove(initial, 1, rules).state;
  State repeated = initial;
  repeated.seen_boards.push_back(candidate.board);
  Require(!IsLegal(repeated, 1, rules), "positional superko should be illegal");

  const State one_pass = ApplyMove(initial, kPass, rules).state;
  const State terminal = ApplyMove(one_pass, kPass, rules).state;
  Require(!IsLegal(terminal, kPass, rules),
          "move after termination should be illegal");
}

void TestInvalidStateErrorPropagates() {
  Rules rules;
  rules.size = 3;
  rules.komi2 = 1;

  State malformed = State::Initial(rules);
  malformed.size = 2;

  bool invalid_state_propagated = false;
  try {
    static_cast<void>(IsLegal(malformed, 0, rules));
  } catch (const IllegalMove&) {
    throw std::runtime_error(
        "state validation was misclassified as move illegality");
  } catch (const std::invalid_argument&) {
    invalid_state_propagated = true;
  }
  Require(invalid_state_propagated,
          "state/rules mismatch should propagate from IsLegal");

  State missing_history = State::Initial(rules);
  missing_history.seen_boards.clear();
  bool missing_history_propagated = false;
  try {
    static_cast<void>(IsLegal(missing_history, 0, rules));
  } catch (const std::invalid_argument&) {
    missing_history_propagated = true;
  }
  Require(missing_history_propagated,
          "missing PSK current board should propagate from IsLegal");

  State excessive_passes = State::Initial(rules);
  excessive_passes.passes = rules.passes_to_end + 1;
  bool excessive_passes_propagated = false;
  try {
    static_cast<void>(ugts_go19::AreaScore2(excessive_passes, rules));
  } catch (const std::invalid_argument&) {
    excessive_passes_propagated = true;
  }
  Require(excessive_passes_propagated,
          "malformed terminal pass count should fail before scoring");

  State duplicate_history = State::Initial(rules);
  duplicate_history.seen_boards.push_back(duplicate_history.board);
  bool duplicate_history_propagated = false;
  try {
    static_cast<void>(CanonicalStateJson(duplicate_history, rules));
  } catch (const std::invalid_argument&) {
    duplicate_history_propagated = true;
  }
  Require(duplicate_history_propagated,
          "duplicate PSK history entries should be rejected");
}

void TestCanonicalStateIdentity() {
  Rules rules;
  rules.size = 2;
  rules.komi2 = 1;
  State initial = State::Initial(rules);
  const std::string expected =
      "{\"board_hex\":\"00000000\",\"format\":\"UGTS-GO-STATE-v1\","
      "\"passes\":0,\"previous_board_hex\":null,\"rules\":{"
      "\"allow_suicide\":false,\"komi2\":1,\"passes_to_end\":2,"
      "\"scoring\":\"area\",\"size\":2,"
      "\"superko\":\"positional_superko\"},\"seen_hex\":["
      "\"00000000\"],\"to_play\":1}";
  Require(CanonicalStateJson(initial, rules) == expected,
          "canonical initial-state JSON changed");

  State first = ApplyMove(initial, 0, rules).state;
  State reordered = first;
  std::reverse(reordered.seen_boards.begin(), reordered.seen_boards.end());
  reordered.ply += 99;
  Require(ExactStateEqual(first, rules, reordered, rules),
          "history order or ply metadata changed exact identity");
  Require(CanonicalStateJson(first, rules) ==
              CanonicalStateJson(reordered, rules),
          "canonical JSON depends on history order or ply metadata");

  State different_history = first;
  different_history.seen_boards[0] = std::vector<std::uint8_t>{0, 0, 0, 1};
  Require(!ExactStateEqual(first, rules, different_history, rules),
          "different full-history context compared equal");

  State different_previous = first;
  different_previous.previous_board = first.board;
  Require(!ExactStateEqual(first, rules, different_previous, rules),
          "different previous-board lineage compared equal");

  Rules different_rules = rules;
  different_rules.komi2 = 3;
  Require(!ExactStateEqual(first, rules, first, different_rules),
          "different scoring rules compared equal");
}

}  // namespace

int main() {
  try {
    TestRuleIllegalityReturnsFalse();
    TestInvalidStateErrorPropagates();
    TestCanonicalStateIdentity();
    std::cout << "ugts_go_core_tests: ok\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ugts_go_core_tests: " << error.what() << "\n";
    return 1;
  }
}
