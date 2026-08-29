#include "ugts_go19/go_state.hpp"
#include "ugts_go19/sha256.hpp"

#include <algorithm>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using ugts_go19::ApplyMove;
using ugts_go19::CanonicalStateJson;
using ugts_go19::CanonicalStateObjectId;
using ugts_go19::ExactStateEqual;
using ugts_go19::IllegalMove;
using ugts_go19::IsLegal;
using ugts_go19::LegalMoves;
using ugts_go19::Rules;
using ugts_go19::Sha256Hex;
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

  State missing_previous_history = State::Initial(rules);
  missing_previous_history.previous_board =
      std::vector<std::uint8_t>{kBlack, 0, 0, 0, 0, 0, 0, 0, 0};
  bool missing_previous_history_propagated = false;
  try {
    static_cast<void>(IsLegal(missing_previous_history, 0, rules));
  } catch (const std::invalid_argument&) {
    missing_previous_history_propagated = true;
  }
  Require(missing_previous_history_propagated,
          "PSK previous board missing from history should propagate");

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
  Require(CanonicalStateObjectId(initial, rules) ==
              "cd1790d0eb6f28d9fe8a17dd162bc1fa54830a5d104dbe8f76c9efa4e2290fd7",
          "canonical state object ID changed");

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
  different_history.seen_boards.push_back(
      std::vector<std::uint8_t>{0, 0, 0, kBlack});
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

void TestSha256Vectors() {
  Require(Sha256Hex("") ==
              "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
          "SHA-256 empty-message vector failed");
  Require(Sha256Hex("abc") ==
              "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
          "SHA-256 abc vector failed");
  Require(
      Sha256Hex("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq") ==
          "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
      "SHA-256 multi-block vector failed");
  Require(Sha256Hex(std::string(1'000'000, 'a')) ==
              "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0",
          "SHA-256 million-a vector failed");
}

void TestNumericRangeGuards() {
  Rules score_rules;
  score_rules.size = 1;
  score_rules.komi2 = std::numeric_limits<int>::min();
  const State score_state = State::Initial(score_rules);
  Require(ugts_go19::AreaScore2(score_state, score_rules) == 2147483648LL,
          "score2 overflowed the int32 range");

  Rules rules;
  rules.size = 3;
  rules.komi2 = 1;
  State exhausted = State::Initial(rules);
  exhausted.ply = std::numeric_limits<std::uint64_t>::max();

  bool pass_overflow_propagated = false;
  try {
    static_cast<void>(IsLegal(exhausted, kPass, rules));
  } catch (const IllegalMove&) {
    throw std::runtime_error("ply exhaustion was classified as move illegality");
  } catch (const std::overflow_error&) {
    pass_overflow_propagated = true;
  }
  Require(pass_overflow_propagated,
          "IsLegal should propagate ply representation exhaustion");

  State occupied = ApplyMove(State::Initial(rules), 0, rules).state;
  occupied.ply = std::numeric_limits<std::uint64_t>::max();
  Require(!IsLegal(occupied, 0, rules),
          "occupied remains ordinary move illegality at maximum ply");

  bool legal_moves_overflow_propagated = false;
  try {
    static_cast<void>(LegalMoves(exhausted, rules));
  } catch (const std::overflow_error&) {
    legal_moves_overflow_propagated = true;
  }
  Require(legal_moves_overflow_propagated,
          "LegalMoves should not hide ply representation exhaustion");
}

}  // namespace

int main() {
  try {
    TestRuleIllegalityReturnsFalse();
    TestInvalidStateErrorPropagates();
    TestCanonicalStateIdentity();
    TestSha256Vectors();
    TestNumericRangeGuards();
    std::cout << "ugts_go_core_tests: ok\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ugts_go_core_tests: " << error.what() << "\n";
    return 1;
  }
}
