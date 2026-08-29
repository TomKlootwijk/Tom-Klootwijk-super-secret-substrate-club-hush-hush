#include "ugts_go19/go_state.hpp"
#include "ugts_go19/pndag.hpp"
#include "ugts_go19/pndag_checkpoint.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

using ugts_go19::NativePNDAGCheckpointCodec;
using ugts_go19::NativePNDAGCheckpointLimits;
using ugts_go19::ApplyMove;
using ugts_go19::kBlack;
using ugts_go19::kEmpty;
using ugts_go19::kWhite;
using ugts_go19::ProofNumberDAG;
using ugts_go19::ProofStatus;
using ugts_go19::Rules;
using ugts_go19::State;

void Require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

Rules TinyRules(int size) {
  Rules rules;
  rules.size = size;
  rules.komi2 = 1;
  rules.allow_suicide = false;
  rules.passes_to_end = 2;
  return rules;
}

class TemporaryDirectory {
 public:
  TemporaryDirectory() {
    const auto serial = std::chrono::high_resolution_clock::now()
                            .time_since_epoch()
                            .count();
    path_ = std::filesystem::temp_directory_path() /
            ("ugts-native-pndag-checkpoint-test-" + std::to_string(serial));
    if (!std::filesystem::create_directory(path_)) {
      throw std::runtime_error("failed to create checkpoint test directory");
    }
  }

  ~TemporaryDirectory() {
    std::error_code error;
    std::filesystem::remove_all(path_, error);
  }

  const std::filesystem::path& path() const { return path_; }

 private:
  std::filesystem::path path_;
};

void TestNineteenByNineteenResumeAndIdempotence() {
  TemporaryDirectory directory;
  Rules rules;
  rules.size = 19;
  rules.komi2 = 15;
  rules.allow_suicide = false;
  rules.passes_to_end = 2;

  ProofNumberDAG first(rules, 1);
  const auto first_result = first.Advance(1);
  const auto first_tip = NativePNDAGCheckpointCodec::Publish(
      directory.path(), first);
  Require(first_result.status == ProofStatus::kUnknown &&
              first_tip.status == ProofStatus::kUnknown &&
              first_tip.generation == 1,
          "first 19x19 checkpoint lost UNKNOWN status");

  ProofNumberDAG repeated(rules, 1);
  static_cast<void>(repeated.Advance(1));
  const auto repeated_tip = NativePNDAGCheckpointCodec::Publish(
      directory.path(), repeated);
  Require(repeated_tip.checkpoint_file_sha256 ==
              first_tip.checkpoint_file_sha256 &&
              repeated_tip.path == first_tip.path,
          "identical checkpoint publication is not idempotent");

  auto loaded = NativePNDAGCheckpointCodec::Load(
      first_tip.path, first_tip.checkpoint_file_sha256, rules, 1,
      State::Initial(rules));
  const auto resumed_result = loaded.dag.Advance(1);
  const auto second_tip = NativePNDAGCheckpointCodec::Publish(
      directory.path(), loaded.dag, loaded.tip);
  Require(resumed_result.status == ProofStatus::kUnknown &&
              resumed_result.proof_number == 1 &&
              resumed_result.disproof_number == 361 &&
              resumed_result.committed_expansions == 2 &&
              resumed_result.node_count == 725 &&
              resumed_result.edge_count == 724 &&
              resumed_result.graph_sha256 ==
                  "03dfd8263b423501147a0be09d2ccd1e23f51c2923992ed177da277740849618" &&
              second_tip.generation == 2 &&
              second_tip.previous_checkpoint_file_sha256 ==
                  first_tip.checkpoint_file_sha256,
          "19x19 checkpoint resume differs from uninterrupted exact graph");

  State wrong_root = ApplyMove(State::Initial(rules), 0, rules).state;
  bool rejected = false;
  try {
    static_cast<void>(NativePNDAGCheckpointCodec::Load(
        first_tip.path, first_tip.checkpoint_file_sha256, rules, 1,
        wrong_root));
  } catch (const std::invalid_argument&) {
    rejected = true;
  }
  Require(rejected, "checkpoint loader accepted the wrong exact root");

  auto forged_previous = first_tip;
  forged_previous.graph_sha256.assign(64, '0');
  rejected = false;
  try {
    static_cast<void>(NativePNDAGCheckpointCodec::Publish(
        directory.path(), loaded.dag, forged_previous));
  } catch (const std::invalid_argument&) {
    rejected = true;
  }
  Require(rejected,
          "checkpoint publisher trusted forged predecessor-tip metadata");

  NativePNDAGCheckpointLimits too_few_nodes;
  too_few_nodes.max_nodes = 1;
  bool limit_rejected = false;
  try {
    static_cast<void>(NativePNDAGCheckpointCodec::Load(
        first_tip.path, first_tip.checkpoint_file_sha256, rules, 1,
        State::Initial(rules), too_few_nodes));
  } catch (const std::length_error&) {
    limit_rejected = true;
  }
  Require(limit_rejected, "checkpoint node decode cap was ignored");

  NativePNDAGCheckpointLimits too_few_bytes;
  too_few_bytes.max_file_bytes = first_tip.byte_length - 1;
  limit_rejected = false;
  try {
    static_cast<void>(NativePNDAGCheckpointCodec::Load(
        first_tip.path, first_tip.checkpoint_file_sha256, rules, 1,
        State::Initial(rules), too_few_bytes));
  } catch (const std::length_error&) {
    limit_rejected = true;
  }
  Require(limit_rejected, "checkpoint file-byte decode cap was ignored");
}

void TestNonmonotonicCaptureHistoryRoundTrip() {
  TemporaryDirectory directory;
  const Rules rules = TinyRules(3);
  State capture_ready;
  capture_ready.size = 3;
  capture_ready.board = {kEmpty, kEmpty, kEmpty, kWhite, kBlack,
                         kWhite, kEmpty, kWhite, kEmpty};
  capture_ready.to_play = kWhite;
  capture_ready.passes = 0;
  capture_ready.seen_boards = {
      std::vector<std::uint8_t>(9, kEmpty), capture_ready.board};
  const auto capture = ApplyMove(capture_ready, 1, rules);
  Require(capture.captured == 1 && capture.state.board[4] == kEmpty,
          "capture-history checkpoint fixture did not capture exactly");

  State nonmonotonic = capture.state;
  std::reverse(nonmonotonic.seen_boards.begin(),
               nonmonotonic.seen_boards.end());
  ProofNumberDAG dag(rules, 1, nonmonotonic);
  static_cast<void>(dag.Advance(1));
  const auto tip =
      NativePNDAGCheckpointCodec::Publish(directory.path(), dag);
  const auto loaded = NativePNDAGCheckpointCodec::Load(
      tip.path, tip.checkpoint_file_sha256, rules, 1, nonmonotonic);
  Require(loaded.tip.graph_sha256 == dag.GraphSha256() &&
              loaded.dag.StateForId(loaded.dag.root_id()).seen_boards ==
                  dag.StateForId(dag.root_id()).seen_boards,
          "nonmonotonic capture history did not round-trip canonically");
}

void TestTinySolvedResume() {
  for (const auto& fixture :
       {std::pair<std::int64_t, ProofStatus>{1, ProofStatus::kProven},
        std::pair<std::int64_t, ProofStatus>{3,
                                             ProofStatus::kDisproven}}) {
    TemporaryDirectory directory;
    const Rules rules = TinyRules(2);
    ProofNumberDAG interrupted(rules, fixture.first);
    const auto partial = interrupted.Advance(7);
    Require(partial.status == ProofStatus::kUnknown,
            "tiny checkpoint fixture solved before interruption");
    const auto partial_tip = NativePNDAGCheckpointCodec::Publish(
        directory.path(), interrupted);
    auto loaded = NativePNDAGCheckpointCodec::Load(
        partial_tip.path, partial_tip.checkpoint_file_sha256, rules,
        fixture.first, State::Initial(rules));
    const auto resumed = loaded.dag.Advance(10'000);

    ProofNumberDAG uninterrupted(rules, fixture.first);
    const auto complete = uninterrupted.Advance(10'000);
    Require(resumed.status == fixture.second && resumed.status == complete.status &&
                resumed.proof_number == complete.proof_number &&
                resumed.disproof_number == complete.disproof_number &&
                resumed.committed_expansions == complete.committed_expansions &&
                resumed.node_count == complete.node_count &&
                resumed.edge_count == complete.edge_count &&
                resumed.graph_sha256 == complete.graph_sha256,
            "tiny solved checkpoint resume differs from uninterrupted proof");
    const auto solved_tip = NativePNDAGCheckpointCodec::Publish(
        directory.path(), loaded.dag, loaded.tip);
    Require(solved_tip.status == fixture.second,
            "tiny solved checkpoint tip status was not derived exactly");
  }
}

}  // namespace

int main() {
  try {
    TestNineteenByNineteenResumeAndIdempotence();
    TestNonmonotonicCaptureHistoryRoundTrip();
    TestTinySolvedResume();
    std::cout << "ugts_go_pndag_checkpoint_tests: ok\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ugts_go_pndag_checkpoint_tests: " << error.what() << '\n';
    return 1;
  }
}
