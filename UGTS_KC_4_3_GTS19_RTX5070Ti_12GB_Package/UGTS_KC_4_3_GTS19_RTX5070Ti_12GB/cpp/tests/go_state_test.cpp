#include "ugts_go19/go_state.hpp"

#include <iostream>
#include <stdexcept>
#include <vector>

namespace {

using ugts_go19::ApplyMove;
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
}

}  // namespace

int main() {
  try {
    TestRuleIllegalityReturnsFalse();
    TestInvalidStateErrorPropagates();
    std::cout << "ugts_go_core_tests: ok\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ugts_go_core_tests: " << error.what() << "\n";
    return 1;
  }
}
