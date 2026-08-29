#include "ugts_go19/go_state.hpp"
#include "ugts_go19/pndag.hpp"

#include <algorithm>
#include <cstdint>
#include <iostream>
#include <limits>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace ugts_go19 {

// Defined only in this test translation unit. Friendship permits narrowly
// scoped coordinator fault fixtures without public mutation APIs.
class ProofNumberDAGTestAccess {
 public:
  [[nodiscard]] static std::pair<std::uint64_t, std::uint64_t> ProofNumbers(
      const ProofNumberDAG& dag, std::size_t node_id) {
    dag.RequireCachesValid();
    const auto& node = dag.CheckedNode(node_id);
    return {node.proof, node.disproof};
  }

  [[nodiscard]] static ProofPropagationMetrics FullRecompute(
      ProofNumberDAG& dag) {
    return dag.RecomputeAll();
  }

  [[nodiscard]] static const ProofPropagationMetrics& LastMetrics(
      const ProofNumberDAG& dag) noexcept {
    return dag.last_incremental_propagation_metrics_;
  }

  [[nodiscard]] static std::uint64_t FullRecomputePasses(
      const ProofNumberDAG& dag) noexcept {
    return dag.full_recompute_passes_;
  }

  [[nodiscard]] static bool WasRecomputed(const ProofNumberDAG& dag,
                                          std::size_t node_id) {
    dag.RequireCachesValid();
    const auto& node = dag.CheckedNode(node_id);
    constexpr std::uint64_t processed_bit = UINT64_C(1) << 63U;
    return dag.last_completed_propagation_epoch_ != 0 &&
           node.propagation_stamp ==
               (dag.last_completed_propagation_epoch_ | processed_bit);
  }

  static void ExpandIncrementally(ProofNumberDAG& dag, std::size_t node_id) {
    dag.ExpandNodeAndPropagate(node_id);
  }

  static void AddReverseParent(ProofNumberDAG& dag, std::size_t child_id,
                               std::size_t parent_id) {
    dag.nodes_.at(child_id).parents.insert(parent_id);
  }

  static void RemoveReverseParent(ProofNumberDAG& dag, std::size_t child_id,
                                  std::size_t parent_id) {
    dag.nodes_.at(child_id).parents.erase(parent_id);
  }

  [[nodiscard]] static std::pair<int, std::size_t> ReplaceChildTarget(
      ProofNumberDAG& dag, std::size_t parent_id, std::size_t edge_index,
      std::size_t replacement_child_id) {
    auto& edge = dag.nodes_.at(parent_id).children.at(edge_index);
    const auto saved = edge;
    edge.second = replacement_child_id;
    return saved;
  }

  static void RestoreChild(ProofNumberDAG& dag, std::size_t parent_id,
                           std::size_t edge_index,
                           std::pair<int, std::size_t> edge) {
    dag.nodes_.at(parent_id).children.at(edge_index) = std::move(edge);
  }

  static void ForceEpochResetOnNextPropagation(ProofNumberDAG& dag) {
    dag.propagation_epoch_ =
        std::numeric_limits<std::uint64_t>::max() >> 1U;
    for (auto& node : dag.nodes_) {
      node.propagation_stamp = std::numeric_limits<std::uint64_t>::max();
    }
  }

  [[nodiscard]] static std::uint64_t PropagationEpoch(
      const ProofNumberDAG& dag) noexcept {
    return dag.propagation_epoch_;
  }

  // Replace the graph with a recurrence-valid, strict-rank diamond assembled
  // from exact real states. The descendant is already expanded, but its cache
  // remains at the pre-expansion (1,1), exactly modeling the instant after a
  // committed expansion and before propagation. Edge legality is intentionally
  // outside this proof-coordinator fixture; the production legal generator is
  // covered independently by the canonical graph fingerprints.
  static void InstallDuplicateSuppressionFixture(
      ProofNumberDAG& dag, std::size_t root_id, std::size_t first_parent_id,
      std::size_t second_parent_id, std::size_t descendant_id) {
    dag.RequireCachesValid();
    const auto root_source = dag.nodes_.at(root_id);
    const auto first_source = dag.nodes_.at(first_parent_id);
    const auto second_source = dag.nodes_.at(second_parent_id);
    const auto descendant_source = dag.nodes_.at(descendant_id);
    if (root_source.state.to_play != kBlack ||
        descendant_source.expansion != NodeExpansion::kExpanded ||
        descendant_source.children.size() < 2 ||
        root_source.rank >= first_source.rank ||
        root_source.rank >= second_source.rank ||
        first_source.rank >= descendant_source.rank ||
        second_source.rank >= descendant_source.rank) {
      throw std::logic_error("duplicate-suppression fixture ranks are invalid");
    }

    std::vector<ProofNumberDAG::Node> fixture;
    fixture.reserve(4 + descendant_source.children.size());
    const auto copy_base = [&](const ProofNumberDAG::Node& source,
                               std::size_t new_id) {
      ProofNumberDAG::Node node = source;
      node.node_id = new_id;
      node.children.clear();
      node.parents.clear();
      node.propagation_stamp = 0;
      return node;
    };
    fixture.push_back(copy_base(root_source, 0));
    fixture.push_back(copy_base(first_source, 1));
    fixture.push_back(copy_base(second_source, 2));
    fixture.push_back(copy_base(descendant_source, 3));

    std::map<std::size_t, std::size_t> remapped_children;
    for (const auto& edge : descendant_source.children) {
      auto [found, inserted] =
          remapped_children.emplace(edge.second, fixture.size());
      if (inserted) {
        ProofNumberDAG::Node child =
            copy_base(dag.nodes_.at(edge.second), found->second);
        if (child.expansion == NodeExpansion::kExpanded) {
          throw std::logic_error(
              "duplicate-suppression fixture child is not a leaf");
        }
        child.parents.insert(3);
        fixture.push_back(std::move(child));
      }
      fixture[3].children.emplace_back(edge.first, found->second);
    }

    fixture[0].expansion = NodeExpansion::kExpanded;
    fixture[0].children = {{kPass, 1}, {0, 2}};
    fixture[0].proof = 1;
    fixture[0].disproof = 2;
    for (std::size_t parent_id : {std::size_t{1}, std::size_t{2}}) {
      fixture[parent_id].expansion = NodeExpansion::kExpanded;
      fixture[parent_id].children = {{kPass, 3}};
      fixture[parent_id].parents = {0};
      fixture[parent_id].proof = 1;
      fixture[parent_id].disproof = 1;
    }
    fixture[3].parents = {1, 2};
    fixture[3].proof = 1;
    fixture[3].disproof = 1;

    dag.nodes_ = std::move(fixture);
    dag.exact_index_.clear();
    for (const auto& node : dag.nodes_) {
      const auto inserted =
          dag.exact_index_.emplace(node.state_bytes, node.node_id);
      if (!inserted.second) {
        throw std::logic_error(
            "duplicate-suppression fixture contains duplicate states");
      }
    }
    dag.root_id_ = 0;
    dag.committed_expansions_ = 4;
    dag.caches_valid_ = false;
    dag.propagation_epoch_ = 0;
    dag.last_completed_propagation_epoch_ = 0;
    dag.last_incremental_propagation_metrics_ = {};
  }

  [[nodiscard]] static ProofPropagationMetrics PropagateSyntheticFixture(
      ProofNumberDAG& dag, std::size_t changed_node_id) {
    std::vector<ProofNumberDAG::PropagationWorkItem> heap;
    heap.reserve(dag.nodes_.size());
    const ProofPropagationMetrics metrics =
        dag.PropagateFrom(changed_node_id, std::move(heap));
    dag.last_incremental_propagation_metrics_ = metrics;
    dag.last_completed_propagation_epoch_ = dag.propagation_epoch_;
    dag.caches_valid_ = true;
    return metrics;
  }
};

}  // namespace ugts_go19

namespace {

using ugts_go19::ApplyMove;
using ugts_go19::NodeExpansion;
using ugts_go19::ProofNumberDAG;
using ugts_go19::ProofNumberDAGTestAccess;
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

void RequireIncrementalCachesMatchFullOracle(ProofNumberDAG& dag) {
  const std::uint64_t full_passes_before =
      ProofNumberDAGTestAccess::FullRecomputePasses(dag);
  const auto incremental = dag.Advance(0);
  Require(ProofNumberDAGTestAccess::FullRecomputePasses(dag) ==
              full_passes_before,
          "Advance(0) invoked the graph-wide proof oracle");
  const auto incremental_root =
      ProofNumberDAGTestAccess::ProofNumbers(dag, dag.root_id());
  const auto full_metrics = ProofNumberDAGTestAccess::FullRecompute(dag);
  Require(ProofNumberDAGTestAccess::FullRecomputePasses(dag) ==
              full_passes_before + 1,
          "explicit full proof oracle pass was not recorded exactly once");
  const auto recomputed = dag.Advance(0);

  Require(full_metrics.nodes_recomputed == dag.node_count(),
          "full proof oracle did not recompute every graph node");
  Require(full_metrics.child_edges_scanned == dag.edge_count(),
          "full proof oracle did not rescan every committed edge");
  Require(full_metrics.nodes_changed == 0,
          "incremental proof caches differ from the full oracle");
  Require(full_metrics.queue_insertions == 0,
          "full proof oracle unexpectedly used the incremental queue");
  Require(incremental.status == recomputed.status &&
              incremental.proof_number == recomputed.proof_number &&
              incremental.disproof_number == recomputed.disproof_number &&
              incremental.committed_expansions ==
                  recomputed.committed_expansions &&
              incremental.node_count == recomputed.node_count &&
              incremental.edge_count == recomputed.edge_count &&
              incremental.graph_sha256 == recomputed.graph_sha256 &&
              incremental_root == ProofNumberDAGTestAccess::ProofNumbers(
                                      dag, dag.root_id()),
          "incremental result or graph hash differs from the full oracle");
}

void RequireDeterministicLastPropagationOrder(const ProofNumberDAG& dag) {
  const auto& metrics = ProofNumberDAGTestAccess::LastMetrics(dag);
  Require(metrics.nodes_recomputed == metrics.queue_insertions,
          "incremental queue/recompute cardinalities diverged");
  Require(metrics.nodes_recomputed > 0 &&
              metrics.rank_order_checks + 1 == metrics.nodes_recomputed,
          "incremental propagation did not audit every rank/ID ordering step");
}

struct RecurrenceWitnesses {
  bool saturated_sum = false;
  bool solved_child = false;
  bool mixed_solved_and_open_children = false;
};

RecurrenceWitnesses AuditExpandedRecurrences(const ProofNumberDAG& dag) {
  RecurrenceWitnesses witnesses;
  for (std::size_t node_id = 0;
       node_id < static_cast<std::size_t>(dag.node_count()); ++node_id) {
    if (dag.ExpansionFor(node_id) != NodeExpansion::kExpanded) continue;
    const auto edges = dag.ChildEdgesFor(node_id);
    Require(!edges.empty(), "expanded audit node has no children");

    std::vector<std::uint64_t> child_proofs;
    std::vector<std::uint64_t> child_disproofs;
    child_proofs.reserve(edges.size());
    child_disproofs.reserve(edges.size());
    bool has_solved = false;
    bool has_open = false;
    for (const auto& edge : edges) {
      const auto numbers =
          ProofNumberDAGTestAccess::ProofNumbers(dag, edge.second);
      child_proofs.push_back(numbers.first);
      child_disproofs.push_back(numbers.second);
      has_solved = has_solved || numbers.first == 0 || numbers.second == 0;
      has_open = has_open || (numbers.first != 0 && numbers.second != 0);
    }
    witnesses.solved_child = witnesses.solved_child || has_solved;
    witnesses.mixed_solved_and_open_children =
        witnesses.mixed_solved_and_open_children || (has_solved && has_open);

    const bool black_or_node = dag.StateForId(node_id).to_play == kBlack;
    const std::uint64_t expected_proof =
        black_or_node
            ? *std::min_element(child_proofs.begin(), child_proofs.end())
            : SaturatingProofSum(child_proofs);
    const std::uint64_t expected_disproof =
        black_or_node
            ? SaturatingProofSum(child_disproofs)
            : *std::min_element(child_disproofs.begin(),
                                child_disproofs.end());
    Require(ProofNumberDAGTestAccess::ProofNumbers(dag, node_id) ==
                std::make_pair(expected_proof, expected_disproof),
            "expanded-node local recurrence differs from exact AND/OR math");

    const auto& summed_terms =
        black_or_node ? child_disproofs : child_proofs;
    const auto positive_terms = static_cast<std::size_t>(std::count_if(
        summed_terms.begin(), summed_terms.end(),
        [](std::uint64_t value) { return value != 0; }));
    witnesses.saturated_sum =
        witnesses.saturated_sum ||
        (positive_terms >= 2 && SaturatingProofSum(summed_terms) ==
                                    kProofInfinity);
  }
  return witnesses;
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
  RequireIncrementalCachesMatchFullOracle(proven);

  const auto proof = proven.Advance(10);
  Require(proof.status == ProofStatus::kProven,
          "1x1 threshold -1 should be proven");
  Require(proof.proof_number == 0 && proof.disproof_number == kProofInfinity,
          "1x1 proof terminal numbers changed");
  Require(proof.committed_expansions == 2 && proof.node_count == 3 &&
              proof.edge_count == 2,
          "1x1 proof graph differs from Python PNDAG");
  RequireIncrementalCachesMatchFullOracle(proven);

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
  RequireIncrementalCachesMatchFullOracle(disproven);
}

void TestTwoByTwoOutcomesAndDeterministicContinuation() {
  const Rules rules = TinyRules(2);
  bool saw_saturated_sum = false;
  bool saw_solved_child = false;
  bool saw_mixed_solved_and_open_children = false;
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
    RequireIncrementalCachesMatchFullOracle(uninterrupted);
    const RecurrenceWitnesses witnesses =
        AuditExpandedRecurrences(uninterrupted);
    saw_saturated_sum = saw_saturated_sum || witnesses.saturated_sum;
    saw_solved_child = saw_solved_child || witnesses.solved_child;
    saw_mixed_solved_and_open_children =
        saw_mixed_solved_and_open_children ||
        witnesses.mixed_solved_and_open_children;

    ProofNumberDAG interrupted(rules, expected.first);
    std::uint64_t full_passes =
        ProofNumberDAGTestAccess::FullRecomputePasses(interrupted);
    const auto partial = interrupted.Advance(7);
    Require(ProofNumberDAGTestAccess::FullRecomputePasses(interrupted) ==
                full_passes,
            "normal multi-expansion Advance invoked the full proof oracle");
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
    RequireDeterministicLastPropagationOrder(interrupted);
    RequireIncrementalCachesMatchFullOracle(interrupted);
    full_passes =
        ProofNumberDAGTestAccess::FullRecomputePasses(interrupted);
    const auto second = interrupted.Advance(3);
    Require(ProofNumberDAGTestAccess::FullRecomputePasses(interrupted) ==
                full_passes,
            "continued Advance invoked the full proof oracle");
    Require(second.status == ProofStatus::kUnknown &&
                second.expanded_this_call == 3 &&
                second.committed_expansions == 10 && second.node_count == 40 &&
                second.edge_count == 39 && second.proof_number == 3 &&
                second.disproof_number == 6,
            "interrupted continuation did not preserve exact progress");
    RequireDeterministicLastPropagationOrder(interrupted);
    RequireIncrementalCachesMatchFullOracle(interrupted);
    full_passes =
        ProofNumberDAGTestAccess::FullRecomputePasses(interrupted);
    const auto resumed_complete = interrupted.Advance(10'000);
    Require(ProofNumberDAGTestAccess::FullRecomputePasses(interrupted) ==
                full_passes,
            "solving Advance invoked the full proof oracle");
    Require(resumed_complete.status == complete.status &&
                resumed_complete.proof_number == complete.proof_number &&
                resumed_complete.disproof_number == complete.disproof_number &&
                resumed_complete.committed_expansions ==
                    complete.committed_expansions &&
                resumed_complete.node_count == complete.node_count &&
                resumed_complete.edge_count == complete.edge_count &&
                resumed_complete.graph_sha256 == complete.graph_sha256,
            "interrupted and uninterrupted exact DAGs diverged");
    RequireIncrementalCachesMatchFullOracle(interrupted);
  }
  Require(saw_saturated_sum,
          "completed 2x2 recurrence audit did not exercise saturation");
  Require(saw_solved_child,
          "completed 2x2 recurrence audit did not exercise solved children");
  Require(saw_mixed_solved_and_open_children,
          "completed 2x2 recurrence audit did not exercise solved-child skips");
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
  RequireIncrementalCachesMatchFullOracle(dag);

  std::uint64_t full_passes =
      ProofNumberDAGTestAccess::FullRecomputePasses(dag);
  const auto first = dag.Advance(1);
  Require(ProofNumberDAGTestAccess::FullRecomputePasses(dag) == full_passes,
          "19x19 one-expansion Advance invoked the full proof oracle");
  Require(first.status == ProofStatus::kUnknown && first.proof_number == 1 &&
              first.disproof_number == 362 &&
              first.expanded_this_call == 1 &&
              first.committed_expansions == 1 && first.node_count == 363 &&
              first.edge_count == 362 &&
              first.graph_sha256 ==
                  "85389edf375dbf8385515edd92de54ae31c72f50bd638f5cd9570ba930d6ccdb",
          "one-expansion 19x19 frontier differs from exact legal generation");
  RequireDeterministicLastPropagationOrder(dag);
  RequireIncrementalCachesMatchFullOracle(dag);

  full_passes = ProofNumberDAGTestAccess::FullRecomputePasses(dag);
  const auto second = dag.Advance(1);
  Require(ProofNumberDAGTestAccess::FullRecomputePasses(dag) == full_passes,
          "19x19 continued Advance invoked the full proof oracle");
  Require(second.status == ProofStatus::kUnknown && second.proof_number == 1 &&
              second.disproof_number == 361 &&
              second.expanded_this_call == 1 &&
              second.committed_expansions == 2 && second.node_count == 725 &&
              second.edge_count == 724 &&
              second.graph_sha256 ==
                  "03dfd8263b423501147a0be09d2ccd1e23f51c2923992ed177da277740849618",
          "two-expansion 19x19 frontier was mislabeled or generated incompletely");
  RequireDeterministicLastPropagationOrder(dag);
  RequireIncrementalCachesMatchFullOracle(dag);
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

void TestAncestorLocalOperationCounts() {
  const Rules rules = TinyRules(2);
  ProofNumberDAG dag(rules, 1);
  dag.ExpandNodeForAudit(dag.root_id());
  const auto root_edges = dag.ChildEdgesFor(dag.root_id());
  Require(root_edges.size() >= 3,
          "locality fixture lacks two independent root branches");
  const std::size_t first_branch = root_edges[1].second;
  const std::size_t unrelated_branch = root_edges[2].second;
  dag.ExpandNodeForAudit(first_branch);
  dag.ExpandNodeForAudit(unrelated_branch);

  std::optional<std::size_t> target;
  for (const auto& edge : dag.ChildEdgesFor(first_branch)) {
    if (dag.ExpansionFor(edge.second) == NodeExpansion::kUnexpanded) {
      target = edge.second;
      break;
    }
  }
  Require(target.has_value(),
          "locality fixture lacks an unexpanded shallow descendant");
  const auto unrelated_before =
      ProofNumberDAGTestAccess::ProofNumbers(dag, unrelated_branch);
  const std::uint64_t existing_nodes = dag.node_count();
  const std::uint64_t full_passes =
      ProofNumberDAGTestAccess::FullRecomputePasses(dag);

  ProofNumberDAGTestAccess::ExpandIncrementally(dag, *target);
  Require(ProofNumberDAGTestAccess::FullRecomputePasses(dag) == full_passes,
          "incremental audit expansion invoked the full proof oracle");
  const auto& metrics = ProofNumberDAGTestAccess::LastMetrics(dag);
  Require(metrics.nodes_recomputed > 0 &&
              metrics.nodes_recomputed < existing_nodes,
          "shallow expansion recomputed unrelated graph nodes");
  Require(metrics.child_edges_scanned < dag.edge_count(),
          "shallow expansion rescanned the complete graph edge set");
  Require(!ProofNumberDAGTestAccess::WasRecomputed(dag, unrelated_branch),
          "unrelated sibling branch entered the ancestor work queue");
  Require(ProofNumberDAGTestAccess::ProofNumbers(dag, unrelated_branch) ==
              unrelated_before,
          "unrelated sibling branch cache changed");
  RequireDeterministicLastPropagationOrder(dag);
  RequireIncrementalCachesMatchFullOracle(dag);
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

  Require(dag.ExpansionFor(first.second) == NodeExpansion::kUnexpanded,
          "transposition fixture endpoint is not an open frontier");
  ProofNumberDAGTestAccess::ExpandIncrementally(dag, first.second);
  Require(ProofNumberDAGTestAccess::WasRecomputed(dag, first.second) &&
              ProofNumberDAGTestAccess::WasRecomputed(dag, first.first) &&
              ProofNumberDAGTestAccess::WasRecomputed(dag, second.first),
          "real transposition propagation missed a direct reverse parent");
  RequireDeterministicLastPropagationOrder(dag);
  RequireIncrementalCachesMatchFullOracle(dag);
}

void TestSyntheticDiamondDuplicateSuppression() {
  const Rules rules = TinyRules(2);
  const State initial = State::Initial(rules);
  const std::vector<int> first_moves{0, 2, 3, kPass, 1,
                                     2, kPass, 1, kPass};
  const std::vector<int> second_moves{0, kPass, 3, kPass, 1,
                                      2, 0,     1,     kPass};
  ProofNumberDAG dag(rules, 1);
  const auto first = ExpandPath(dag, initial, rules, first_moves);
  const auto second = ExpandPath(dag, initial, rules, second_moves);
  Require(first.second == second.second && first.first != second.first,
          "synthetic diamond source transposition changed");
  dag.ExpandNodeForAudit(first.second);

  ProofNumberDAGTestAccess::InstallDuplicateSuppressionFixture(
      dag, dag.root_id(), first.first, second.first, first.second);
  const auto metrics =
      ProofNumberDAGTestAccess::PropagateSyntheticFixture(dag, 3);
  Require(metrics.nodes_recomputed == 4 && metrics.nodes_changed == 4 &&
              metrics.queue_insertions == 4 &&
              metrics.duplicate_queue_suppressions > 0 &&
              metrics.rank_order_checks == 3,
          "synthetic diamond did not propagate/deduplicate exactly once");
  for (std::size_t node_id = 0; node_id < 4; ++node_id) {
    Require(ProofNumberDAGTestAccess::WasRecomputed(dag, node_id),
            "synthetic diamond omitted an affected proof node");
  }

  const std::string incremental_sha256 = dag.GraphSha256();
  const auto oracle = ProofNumberDAGTestAccess::FullRecompute(dag);
  Require(oracle.nodes_changed == 0 &&
              dag.GraphSha256() == incremental_sha256,
          "synthetic diamond differs from the exact full oracle");
}

void TestCommittedPropagationFailureRepairsAndResumes() {
  const Rules rules = TinyRules(2);
  ProofNumberDAG dag(rules, 1);
  static_cast<void>(dag.Advance(1));
  const auto root_edges = dag.ChildEdgesFor(dag.root_id());
  Require(root_edges.size() >= 3,
          "repair fixture lacks equal-rank sibling frontiers");
  const std::size_t target = root_edges[1].second;
  const std::size_t invalid_parent = root_edges[2].second;
  const std::uint64_t committed_before = dag.committed_expansions();
  const std::uint64_t full_passes_before =
      ProofNumberDAGTestAccess::FullRecomputePasses(dag);
  ProofNumberDAGTestAccess::AddReverseParent(dag, target, invalid_parent);

  bool propagation_threw = false;
  try {
    ProofNumberDAGTestAccess::ExpandIncrementally(dag, target);
  } catch (const std::invalid_argument&) {
    propagation_threw = true;
  }
  ProofNumberDAGTestAccess::RemoveReverseParent(dag, target, invalid_parent);
  Require(propagation_threw &&
              dag.committed_expansions() == committed_before + 1 &&
              dag.ExpansionFor(target) == NodeExpansion::kExpanded &&
              ProofNumberDAGTestAccess::FullRecomputePasses(dag) ==
                  full_passes_before + 1,
          "post-commit propagation failure was not repaired and rethrown");

  const std::string repaired_sha256 = dag.GraphSha256();
  const auto oracle = ProofNumberDAGTestAccess::FullRecompute(dag);
  Require(oracle.nodes_changed == 0 && dag.GraphSha256() == repaired_sha256,
          "successful propagation repair left stale caches");
  const auto resumed = dag.Advance(1);
  Require(resumed.expanded_this_call == 1 &&
              resumed.committed_expansions == committed_before + 2,
          "repaired graph could not resume exact incremental work");
}

void TestFailedRepairPoisonsCachesUntilAuditRecovery() {
  const Rules rules = TinyRules(2);
  ProofNumberDAG dag(rules, 1);
  static_cast<void>(dag.Advance(1));
  const auto root_edges = dag.ChildEdgesFor(dag.root_id());
  const std::size_t target = root_edges[1].second;
  const std::size_t invalid_parent = root_edges[2].second;
  const auto saved_edge = ProofNumberDAGTestAccess::ReplaceChildTarget(
      dag, dag.root_id(), 0, dag.root_id());
  ProofNumberDAGTestAccess::AddReverseParent(dag, target, invalid_parent);

  bool repair_threw = false;
  try {
    ProofNumberDAGTestAccess::ExpandIncrementally(dag, target);
  } catch (const std::invalid_argument&) {
    repair_threw = true;
  }
  Require(repair_threw &&
              dag.ExpansionFor(target) == NodeExpansion::kExpanded,
          "forced full-oracle repair failure did not occur post-commit");

  bool advance_rejected = false;
  bool hash_rejected = false;
  try {
    static_cast<void>(dag.Advance(0));
  } catch (const std::logic_error&) {
    advance_rejected = true;
  }
  try {
    static_cast<void>(dag.GraphSha256());
  } catch (const std::logic_error&) {
    hash_rejected = true;
  }
  Require(advance_rejected && hash_rejected,
          "poisoned proof caches crossed a result/hash boundary");

  ProofNumberDAGTestAccess::RestoreChild(dag, dag.root_id(), 0, saved_edge);
  ProofNumberDAGTestAccess::RemoveReverseParent(dag, target, invalid_parent);
  static_cast<void>(ProofNumberDAGTestAccess::FullRecompute(dag));
  const auto second_oracle = ProofNumberDAGTestAccess::FullRecompute(dag);
  Require(second_oracle.nodes_changed == 0 &&
              dag.Advance(0).status == ProofStatus::kUnknown,
          "audit recovery did not restore exact usable caches");
}

void TestPropagationEpochReset() {
  const Rules rules = TinyRules(2);
  ProofNumberDAG dag(rules, 1);
  static_cast<void>(dag.Advance(1));
  const auto root_edges = dag.ChildEdgesFor(dag.root_id());
  const std::size_t target = root_edges[1].second;
  ProofNumberDAGTestAccess::ForceEpochResetOnNextPropagation(dag);
  ProofNumberDAGTestAccess::ExpandIncrementally(dag, target);
  Require(ProofNumberDAGTestAccess::PropagationEpoch(dag) == 1 &&
              ProofNumberDAGTestAccess::WasRecomputed(dag, target),
          "propagation epoch reset did not clear stale duplicate stamps");
  RequireIncrementalCachesMatchFullOracle(dag);
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
    TestAncestorLocalOperationCounts();
    TestRealTranspositionReuse();
    TestSyntheticDiamondDuplicateSuppression();
    TestCommittedPropagationFailureRepairsAndResumes();
    TestFailedRepairPoisonsCachesUntilAuditRecovery();
    TestPropagationEpochReset();
    TestScopeGuards();
    std::cout << "ugts_go_pndag_tests: ok\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ugts_go_pndag_tests: " << error.what() << "\n";
    return 1;
  }
}
