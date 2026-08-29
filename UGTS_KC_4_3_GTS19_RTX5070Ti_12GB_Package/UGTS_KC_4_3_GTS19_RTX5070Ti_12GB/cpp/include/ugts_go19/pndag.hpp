#pragma once

#include "ugts_go19/go_state.hpp"

#include <cstddef>
#include <cstdint>
#include <limits>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace ugts_go19 {

class NativePNDAGCheckpointCodec;
#if defined(UGTS_GO19_ENABLE_PNDAG_TEST_ACCESS)
class ProofNumberDAGTestAccess;
#endif

constexpr std::uint64_t kProofInfinity =
    std::numeric_limits<std::uint64_t>::max();

// Proof-number addition is unsigned-64 saturation, never wraparound.  The
// loop deliberately continues after saturation; uint64_t makes every operand
// representable, while callers with decoded/untyped input must validate it at
// their interchange boundary before calling this typed primitive.
[[nodiscard]] std::uint64_t SaturatingProofSum(
    const std::vector<std::uint64_t>& values);

enum class ProofStatus {
  kUnknown,
  kProven,
  kDisproven,
};

[[nodiscard]] const char* ProofStatusName(ProofStatus status);

enum class NodeExpansion {
  kUnexpanded,
  kExpanded,
  kTerminal,
};

struct ProofNumberDAGResult {
  ProofStatus status = ProofStatus::kUnknown;
  std::int64_t threshold2 = 0;
  std::uint64_t proof_number = 1;
  std::uint64_t disproof_number = 1;
  std::uint64_t expanded_this_call = 0;
  std::uint64_t committed_expansions = 0;
  std::uint64_t node_count = 0;
  std::uint64_t edge_count = 0;
  std::string graph_sha256;
};

// Proof-cache work performed by one propagation/recomputation pass.  These
// counters are diagnostic only: they are deliberately absent from graph and
// checkpoint serialization and can never influence proof selection.
struct ProofPropagationMetrics {
  std::uint64_t nodes_recomputed = 0;
  std::uint64_t nodes_changed = 0;
  std::uint64_t child_edges_scanned = 0;
  std::uint64_t queue_insertions = 0;
  std::uint64_t duplicate_queue_suppressions = 0;
  std::uint64_t rank_order_checks = 0;
};

// An exact in-memory proof-number DAG for 1x1 through 19x19 area-scored
// positional-superko games with two-pass ending.  Advance() is explicitly
// bounded by committed node expansions; an unfinished bounded advance always
// reports UNKNOWN.  This class does not by itself make storage or whole-game
// resource bounds practical for large boards.
class ProofNumberDAG {
 public:
  ProofNumberDAG(Rules rules, std::int64_t threshold2,
                 std::optional<State> root_state = std::nullopt);

  [[nodiscard]] ProofNumberDAGResult Advance(
      std::uint64_t additional_expansions);

  [[nodiscard]] std::optional<std::size_t> LookupStateId(
      const State& state) const;
  [[nodiscard]] const State& StateForId(std::size_t node_id) const;
  [[nodiscard]] std::vector<std::size_t> ParentIdsFor(
      std::size_t node_id) const;
  [[nodiscard]] std::vector<std::pair<int, std::size_t>> ChildEdgesFor(
      std::size_t node_id) const;
  [[nodiscard]] NodeExpansion ExpansionFor(std::size_t node_id) const;
  [[nodiscard]] std::uint64_t RankFor(std::size_t node_id) const;

  // Exact audit hook used to construct bounded transposition fixtures.  It
  // commits one specified unexpanded node and then independently recomputes
  // all proof numbers.  Normal search should use Advance().
  void ExpandNodeForAudit(std::size_t node_id);

  [[nodiscard]] std::uint64_t committed_expansions() const noexcept {
    return committed_expansions_;
  }
  [[nodiscard]] std::uint64_t node_count() const;
  [[nodiscard]] std::uint64_t edge_count() const;
  [[nodiscard]] std::size_t root_id() const noexcept { return root_id_; }
  [[nodiscard]] const Rules& rules() const noexcept { return rules_; }
  [[nodiscard]] std::int64_t threshold2() const noexcept { return threshold2_; }
  [[nodiscard]] std::string GraphSha256() const;

 private:
  friend class NativePNDAGCheckpointCodec;
#if defined(UGTS_GO19_ENABLE_PNDAG_TEST_ACCESS)
  friend class ProofNumberDAGTestAccess;
#endif

  struct Node {
    std::size_t node_id = 0;
    std::string state_bytes;
    State state;
    std::uint64_t rank = 0;
    NodeExpansion expansion = NodeExpansion::kUnexpanded;
    std::vector<std::pair<int, std::size_t>> children;
    std::set<std::size_t> parents;
    std::uint64_t proof = 1;
    std::uint64_t disproof = 1;

    // Transient duplicate-suppression state for incremental propagation.
    // It is not proof-authoritative and is never serialized or hashed.
    std::uint64_t propagation_stamp = 0;
  };

  struct ProofNumbers {
    std::uint64_t proof = 1;
    std::uint64_t disproof = 1;
    std::uint64_t child_edges_scanned = 0;
  };

  struct PropagationWorkItem {
    std::uint64_t rank = 0;
    std::size_t node_id = 0;
  };

  struct CanonicalChild {
    int move = kPass;
    std::string state_bytes;
    State state;
  };

  [[nodiscard]] State NormalizeState(const State& state) const;
  [[nodiscard]] std::uint64_t Rank(const State& state) const;
  [[nodiscard]] std::size_t InternState(const State& state);
  [[nodiscard]] std::vector<CanonicalChild> CanonicalChildren(
      const State& state) const;
  void InitializeLeaf(Node& node) const;
  void ExpandNode(std::size_t node_id);
  void ExpandNodeAndPropagate(std::size_t node_id);
  [[nodiscard]] ProofNumbers EvaluateNode(std::size_t node_id) const;
  [[nodiscard]] ProofPropagationMetrics PropagateFrom(
      std::size_t node_id,
      std::vector<PropagationWorkItem> propagation_heap);
  ProofPropagationMetrics RecomputeAll();
  void RequireCachesValid() const;
  [[nodiscard]] std::size_t SelectMostProving() const;
  [[nodiscard]] static ProofStatus Status(std::uint64_t proof,
                                          std::uint64_t disproof);
  [[nodiscard]] const Node& CheckedNode(std::size_t node_id) const;

  Rules rules_;
  std::int64_t threshold2_ = 0;
  std::size_t root_id_ = 0;
  std::uint64_t committed_expansions_ = 0;
  std::vector<Node> nodes_;
  bool caches_valid_ = false;
  std::uint64_t propagation_epoch_ = 0;
  std::uint64_t last_completed_propagation_epoch_ = 0;
  std::uint64_t full_recompute_passes_ = 0;
  ProofPropagationMetrics last_incremental_propagation_metrics_;

  // Exact canonical bytes are the authority.  This intentionally uses an
  // ordered comparison tree rather than a hash index, so no hash collision can
  // merge proof states.
  std::map<std::string, std::size_t> exact_index_;
};

}  // namespace ugts_go19
