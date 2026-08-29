#include "ugts_go19/go_state.hpp"
#include "ugts_go19/pndag.hpp"

#include <algorithm>
#include <cstdint>
#include <iostream>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using ugts_go19::ApplyMove;
using ugts_go19::NodeExpansion;
using ugts_go19::ProofNumberDAG;
using ugts_go19::ProofStatus;
using ugts_go19::Rules;
using ugts_go19::SaturatingProofSum;
using ugts_go19::State;
using ugts_go19::kBlack;
using ugts_go19::kPass;
using ugts_go19::kProofInfinity;

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

void TestSaturatingArithmetic() {
  Require(SaturatingProofSum({}) == 0, "empty proof sum should be zero");
  Require(SaturatingProofSum({1, 2, 3}) == 6,
          "ordinary proof sum changed");
  Require(SaturatingProofSum({kProofInfinity - 2, 1}) ==
              kProofInfinity - 1,
          "proof sum saturated too early");
  Require(SaturatingProofSum({kProofInfinity - 1, 1, 7, 9}) ==
              kProofInfinity,
          "proof sum wrapped or stopped being saturated");
}

void TestOneByOneTruthAndBudgetUnknown() {
  const Rules rules = TinyRules(1);
  ProofNumberDAG proven(rules, -1);
  const auto untouched = proven.Advance(0);
  Require(untouched.status == ProofStatus::kUnknown,
          "zero budget must leave an unfinished root UNKNOWN");
  Require(untouched.proof_number == 1 && untouched.disproof_number == 1,
          "untouched leaf proof numbers changed");
  Require(untouched.expanded_this_call == 0 &&
              untouched.committed_expansions == 0,
          "zero budget committed work");

  const auto proof = proven.Advance(10);
  Require(proof.status == ProofStatus::kProven,
          "1x1 threshold -1 should be proven");
  Require(proof.proof_number == 0 && proof.disproof_number == kProofInfinity,
          "1x1 proof terminal numbers changed");
  Require(proof.committed_expansions == 2 && proof.node_count == 3 &&
              proof.edge_count == 2,
          "1x1 proof graph differs from Python PNDAG");

  ProofNumberDAG disproven(rules, 0);
  const auto disproof = disproven.Advance(10);
  Require(disproof.status == ProofStatus::kDisproven,
          "1x1 threshold 0 should be disproven");
  Require(disproof.proof_number == kProofInfinity &&
              disproof.disproof_number == 0,
          "1x1 disproof terminal numbers changed");
  Require(disproof.committed_expansions == 2 && disproof.node_count == 3 &&
              disproof.edge_count == 2,
          "1x1 disproof graph differs from Python PNDAG");
}

void TestTwoByTwoOutcomesAndDeterministicContinuation() {
  const Rules rules = TinyRules(2);
  for (const auto& expected :
       std::vector<std::pair<std::int64_t, ProofStatus>>{
           {1, ProofStatus::kProven}, {3, ProofStatus::kDisproven}}) {
    ProofNumberDAG uninterrupted(rules, expected.first);
    const auto complete = uninterrupted.Advance(10'000);
    Require(complete.status == expected.second,
            "2x2 outcome differs from Python PNDAG");
    const std::uint64_t expected_expansions = expected.first == 1 ? 171 : 198;
    const std::uint64_t expected_nodes = expected.first == 1 ? 397 : 483;
    const std::uint64_t expected_edges = expected.first == 1 ? 396 : 482;
    // These fingerprints were independently emitted from the Python flat
    // PNDAG using the documented UGTS-CPP-PNDAG-GRAPH-v1 field framing.  They
    // cover every exact state byte string, node rank, proof/disproof value, and
    // ordered edge in the completed graph, not only the aggregate counts.
    const std::string expected_graph_sha256 =
        expected.first == 1
            ? "c1c47dfb493114a09fb3814a89e5f906d5e92322f455433e54ac0d2218c017a3"
            : "f8e84302f74e8355f02a0590f90ea4b3966ff67c3fd8dcf2d53e9481b90f83bb";
    Require(complete.committed_expansions == expected_expansions &&
                complete.node_count == expected_nodes &&
                complete.edge_count == expected_edges &&
                complete.graph_sha256 == expected_graph_sha256,
            "2x2 canonical search graph differs from Python PNDAG");

    ProofNumberDAG interrupted(rules, expected.first);
    const auto partial = interrupted.Advance(7);
    Require(partial.status == ProofStatus::kUnknown,
            "budgeted 2x2 frontier was mislabeled solved");
    Require(partial.proof_number == 3 && partial.disproof_number == 4 &&
                partial.committed_expansions == 7 && partial.node_count == 31 &&
                partial.edge_count == 30 &&
                partial.graph_sha256 ==
                    (expected.first == 1
                         ? "1e28038a81a6d3bb671cf56d49592435ff026ef4def95ec6b367db845377e1f7"
                         : "edeb3193cc61b8e9ecf125d38dc31795541c34287117a919a229ebb8d0c67bb3"),
            "2x2 seven-expansion frontier differs from Python PNDAG");
    const auto second = interrupted.Advance(3);
    Require(second.status == ProofStatus::kUnknown &&
                second.expanded_this_call == 3 &&
                second.committed_expansions == 10 && second.node_count == 40 &&
                second.edge_count == 39 && second.proof_number == 3 &&
                second.disproof_number == 6,
            "interrupted continuation did not preserve exact progress");
    const auto resumed_complete = interrupted.Advance(10'000);
    Require(resumed_complete.status == complete.status &&
                resumed_complete.proof_number == complete.proof_number &&
                resumed_complete.disproof_number == complete.disproof_number &&
                resumed_complete.committed_expansions ==
                    complete.committed_expansions &&
                resumed_complete.node_count == complete.node_count &&
                resumed_complete.edge_count == complete.edge_count &&
                resumed_complete.graph_sha256 == complete.graph_sha256,
            "interrupted and uninterrupted exact DAGs diverged");
  }
}

void TestNineteenByNineteenBoundedUnknown() {
  Rules rules;
  rules.size = 19;
  rules.komi2 = 15;
  rules.allow_suicide = false;
  rules.passes_to_end = 2;
  ProofNumberDAG dag(rules, 1);

  const auto untouched = dag.Advance(0);
  Require(untouched.status == ProofStatus::kUnknown &&
              untouched.proof_number == 1 && untouched.disproof_number == 1 &&
              untouched.expanded_this_call == 0 &&
              untouched.committed_expansions == 0 &&
              untouched.node_count == 1 && untouched.edge_count == 0 &&
              untouched.graph_sha256 ==
                  "1b925b87f7aa54dce94771e58904b0364edf61fb5c1a1832bff0acaece36c9e9",
          "zero-budget 19x19 root did not remain exactly UNKNOWN");

  const auto first = dag.Advance(1);
  Require(first.status == ProofStatus::kUnknown && first.proof_number == 1 &&
              first.disproof_number == 362 &&
              first.expanded_this_call == 1 &&
              first.committed_expansions == 1 && first.node_count == 363 &&
              first.edge_count == 362 &&
              first.graph_sha256 ==
                  "85389edf375dbf8385515edd92de54ae31c72f50bd638f5cd9570ba930d6ccdb",
          "one-expansion 19x19 frontier differs from exact legal generation");

  const auto second = dag.Advance(1);
  Require(second.status == ProofStatus::kUnknown && second.proof_number == 1 &&
              second.disproof_number == 361 &&
              second.expanded_this_call == 1 &&
              second.committed_expansions == 2 && second.node_count == 725 &&
              second.edge_count == 724 &&
              second.graph_sha256 ==
                  "03dfd8263b423501147a0be09d2ccd1e23f51c2923992ed177da277740849618",
          "two-expansion 19x19 frontier was mislabeled or generated incompletely");
}

void TestCanonicalEdgesRanksAndExactIdentity() {
  const Rules rules = TinyRules(2);
  const State root = State::Initial(rules);
  ProofNumberDAG dag(rules, 1, root);

  State same_semantics = root;
  same_semantics.ply = std::numeric_limits<std::uint64_t>::max();
  Require(dag.LookupStateId(same_semantics) ==
              std::optional<std::size_t>(dag.root_id()),
          "campaign ply incorrectly entered semantic identity");

  State extra_history = root;
  extra_history.seen_boards.push_back({kBlack, 0, 0, 0});
  Require(!dag.LookupStateId(extra_history).has_value(),
          "different complete PSK context merged");

  State different_previous = root;
  different_previous.previous_board = root.board;
  Require(!dag.LookupStateId(different_previous).has_value(),
          "different previous-board lineage merged");

  dag.ExpandNodeForAudit(dag.root_id());
  const auto edges = dag.ChildEdgesFor(dag.root_id());
  Require(edges.size() == 5, "2x2 root should have four placements and pass");
  const std::vector<int> expected_moves{kPass, 0, 1, 2, 3};
  std::vector<int> actual_moves;
  for (const auto& edge : edges) {
    actual_moves.push_back(edge.first);
    Require(dag.RankFor(edge.second) > dag.RankFor(dag.root_id()),
            "edge failed strict semantic rank ordering");
  }
  Require(actual_moves == expected_moves,
          "canonical legal edge order is not numeric/pass-minus-one");

  State first_child = ApplyMove(root, 0, rules).state;
  State reordered = first_child;
  std::reverse(reordered.seen_boards.begin(), reordered.seen_boards.end());
  reordered.ply = 999;
  Require(dag.LookupStateId(first_child) == dag.LookupStateId(reordered),
          "seen order or ply changed exact interning");

  Rules different_rules = rules;
  different_rules.komi2 = 3;
  ProofNumberDAG different_run(different_rules, 1);
  Require(dag.GraphSha256() != different_run.GraphSha256(),
          "semantic rules were omitted from graph identity");
}

std::pair<std::size_t, std::size_t> ExpandPath(
    ProofNumberDAG& dag, State root, const Rules& rules,
    const std::vector<int>& moves) {
  std::size_t node_id = dag.root_id();
  std::size_t parent_id = node_id;
  for (const int move : moves) {
    if (dag.ExpansionFor(node_id) == NodeExpansion::kUnexpanded) {
      dag.ExpandNodeForAudit(node_id);
    }
    parent_id = node_id;
    root = ApplyMove(root, move, rules).state;
    const auto child_id = dag.LookupStateId(root);
    Require(child_id.has_value(), "expanded path child was not exact-interned");
    Require(dag.RankFor(*child_id) > dag.RankFor(parent_id),
            "controlled path contains a non-DAG edge");
    node_id = *child_id;
  }
  return {parent_id, node_id};
}

void TestRealTranspositionReuse() {
  const Rules rules = TinyRules(2);
  const State initial = State::Initial(rules);
  const std::vector<int> first_moves{0, 2, 3, kPass, 1,
                                     2, kPass, 1, kPass};
  const std::vector<int> second_moves{0, kPass, 3, kPass, 1,
                                      2, 0,     1,     kPass};
  ProofNumberDAG dag(rules, 1);
  const auto first = ExpandPath(dag, initial, rules, first_moves);
  const auto second = ExpandPath(dag, initial, rules, second_moves);
  Require(first.second == second.second,
          "equal full states failed to reuse a DAG node");
  Require(first.first != second.first,
          "transposition fixture did not have distinct parents");
  const auto parents = dag.ParentIdsFor(first.second);
  Require(std::find(parents.begin(), parents.end(), first.first) !=
              parents.end() &&
              std::find(parents.begin(), parents.end(), second.first) !=
                  parents.end(),
          "reverse edges lost a transposition parent");
}

void TestScopeGuards() {
  for (int size = 1; size <= 19; ++size) {
    ProofNumberDAG accepted_dag(TinyRules(size), 1);
    const auto result = accepted_dag.Advance(0);
    Require(result.status == ProofStatus::kUnknown && result.node_count == 1 &&
                result.edge_count == 0,
            "PNDAG rejected or mutated an in-scope zero-budget board");
  }

  Rules too_large = TinyRules(20);
  bool size_rejected = false;
  try {
    static_cast<void>(ProofNumberDAG(too_large, 1));
  } catch (const std::invalid_argument&) {
    size_rejected = true;
  }
  Require(size_rejected, "PNDAG accepted a board larger than 19x19");

  Rules too_small = TinyRules(1);
  too_small.size = 0;
  bool zero_size_rejected = false;
  try {
    static_cast<void>(ProofNumberDAG(too_small, 1));
  } catch (const std::invalid_argument&) {
    zero_size_rejected = true;
  }
  Require(zero_size_rejected, "PNDAG accepted a zero-sized board");

  Rules wrong_end = TinyRules(2);
  wrong_end.passes_to_end = 3;
  bool end_rejected = false;
  try {
    static_cast<void>(ProofNumberDAG(wrong_end, 1));
  } catch (const std::invalid_argument&) {
    end_rejected = true;
  }
  Require(end_rejected, "PNDAG accepted non-two-pass termination");
}

}  // namespace

int main() {
  try {
    TestSaturatingArithmetic();
    TestOneByOneTruthAndBudgetUnknown();
    TestTwoByTwoOutcomesAndDeterministicContinuation();
    TestNineteenByNineteenBoundedUnknown();
    TestCanonicalEdgesRanksAndExactIdentity();
    TestRealTranspositionReuse();
    TestScopeGuards();
    std::cout << "ugts_go_pndag_tests: ok\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ugts_go_pndag_tests: " << error.what() << "\n";
    return 1;
  }
}
