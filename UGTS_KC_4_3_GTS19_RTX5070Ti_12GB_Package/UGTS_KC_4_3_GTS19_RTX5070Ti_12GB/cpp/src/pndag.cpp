#include "ugts_go19/pndag.hpp"

#include "ugts_go19/sha256.hpp"

#include <algorithm>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <tuple>

namespace ugts_go19 {
namespace {

std::uint64_t SaturatingAdd(std::uint64_t left, std::uint64_t right) {
  if (left > kProofInfinity - right) return kProofInfinity;
  return left + right;
}

void AppendScalar(std::string& output, std::uint64_t value) {
  output.append(std::to_string(value));
  output.push_back(';');
}

void AppendSignedScalar(std::string& output, std::int64_t value) {
  output.append(std::to_string(value));
  output.push_back(';');
}

void AppendBytes(std::string& output, const std::string& value) {
  output.append(std::to_string(value.size()));
  output.push_back(':');
  output.append(value);
  output.push_back(';');
}

std::uint64_t CheckedSize(std::size_t value, const char* label) {
  if (value > static_cast<std::size_t>(
                  std::numeric_limits<std::uint64_t>::max())) {
    throw std::overflow_error(std::string(label) + " exceeds uint64");
  }
  return static_cast<std::uint64_t>(value);
}

}  // namespace

std::uint64_t SaturatingProofSum(
    const std::vector<std::uint64_t>& values) {
  std::uint64_t total = 0;
  for (const std::uint64_t value : values) {
    total = SaturatingAdd(total, value);
  }
  return total;
}

const char* ProofStatusName(ProofStatus status) {
  switch (status) {
    case ProofStatus::kUnknown:
      return "UNKNOWN";
    case ProofStatus::kProven:
      return "PROVEN";
    case ProofStatus::kDisproven:
      return "DISPROVEN";
  }
  throw std::invalid_argument("unknown proof status");
}

ProofNumberDAG::ProofNumberDAG(Rules rules, std::int64_t threshold2,
                               std::optional<State> root_state)
    : rules_(rules), threshold2_(threshold2) {
  if (rules_.size < 1 || rules_.size > 19) {
    throw std::invalid_argument("ProofNumberDAG requires a board size in 1..19");
  }
  if (rules_.passes_to_end != 2) {
    throw std::invalid_argument(
        "ProofNumberDAG requires two-pass termination");
  }

  // Match the Python verifier's signed-64 terminal-score interchange guard.
  const auto points =
      static_cast<std::int64_t>(rules_.size) * rules_.size;
  const auto komi2 = static_cast<std::int64_t>(rules_.komi2);
  const auto minimum_score2 = -2 * points - komi2;
  const auto maximum_score2 = 2 * points - komi2;
  if (minimum_score2 > maximum_score2) {
    throw std::overflow_error("possible score2 interval is invalid");
  }

  const State root =
      root_state.has_value() ? std::move(*root_state) : State::Initial(rules_);
  root_id_ = InternState(root);
  if (root_id_ != 0) {
    throw std::logic_error("root must be the first interned state");
  }
  RecomputeAll();
}

State ProofNumberDAG::NormalizeState(const State& state) const {
  // CanonicalStateJson performs complete validation against rules_.
  static_cast<void>(CanonicalStateJson(state, rules_));
  State normalized = state;
  std::sort(normalized.seen_boards.begin(), normalized.seen_boards.end());
  // Ply is campaign metadata, deliberately absent from exact state identity.
  normalized.ply = 0;
  return normalized;
}

std::uint64_t ProofNumberDAG::Rank(const State& state) const {
  const std::uint64_t seen = CheckedSize(state.seen_boards.size(), "history");
  if (seen > (kProofInfinity - 2U) / 2U) {
    throw std::overflow_error("semantic rank exceeds uint64");
  }
  if (state.passes < 0) {
    throw std::invalid_argument("negative pass count in semantic rank");
  }
  const auto passes = static_cast<std::uint64_t>(state.passes);
  if (2U * seen > kProofInfinity - passes) {
    throw std::overflow_error("semantic rank exceeds uint64");
  }
  return 2U * seen + passes;
}

void ProofNumberDAG::InitializeLeaf(Node& node) const {
  if (node.state.Terminal(rules_)) {
    if (AreaScore2(node.state, rules_) >= threshold2_) {
      node.proof = 0;
      node.disproof = kProofInfinity;
    } else {
      node.proof = kProofInfinity;
      node.disproof = 0;
    }
    return;
  }
  node.proof = 1;
  node.disproof = 1;
}

std::size_t ProofNumberDAG::InternState(const State& state) {
  State normalized = NormalizeState(state);
  std::string state_bytes = CanonicalStateJson(normalized, rules_);
  const auto existing = exact_index_.find(state_bytes);
  if (existing != exact_index_.end()) return existing->second;

  const std::size_t node_id = nodes_.size();
  Node node;
  node.node_id = node_id;
  node.state_bytes = state_bytes;
  node.state = std::move(normalized);
  node.rank = Rank(node.state);
  node.expansion = node.state.Terminal(rules_) ? NodeExpansion::kTerminal
                                               : NodeExpansion::kUnexpanded;
  InitializeLeaf(node);

  nodes_.push_back(std::move(node));
  try {
    const auto inserted = exact_index_.emplace(std::move(state_bytes), node_id);
    if (!inserted.second) {
      nodes_.pop_back();
      return inserted.first->second;
    }
  } catch (...) {
    nodes_.pop_back();
    throw;
  }
  return node_id;
}

std::vector<ProofNumberDAG::CanonicalChild>
ProofNumberDAG::CanonicalChildren(const State& state) const {
  std::vector<CanonicalChild> children;
  const auto legal_moves = LegalMoves(state, rules_, true);
  children.reserve(legal_moves.size());
  for (const int move : legal_moves) {
    State child = NormalizeState(ApplyMove(state, move, rules_).state);
    children.push_back(
        CanonicalChild{move, CanonicalStateJson(child, rules_), std::move(child)});
  }
  std::sort(children.begin(), children.end(),
            [](const CanonicalChild& left, const CanonicalChild& right) {
              return std::tie(left.move, left.state_bytes) <
                     std::tie(right.move, right.state_bytes);
            });
  return children;
}

void ProofNumberDAG::ExpandNode(std::size_t node_id) {
  const Node& original_node = CheckedNode(node_id);
  if (original_node.expansion != NodeExpansion::kUnexpanded) {
    throw std::invalid_argument(
        "only an unexpanded nonterminal node can be expanded");
  }
  if (committed_expansions_ == kProofInfinity) {
    throw std::overflow_error("committed expansion count exceeds uint64");
  }

  const State parent_state = original_node.state;
  const std::uint64_t parent_rank = original_node.rank;
  const std::size_t original_node_count = nodes_.size();
  const std::uint64_t original_expansions = committed_expansions_;
  std::vector<std::pair<int, std::size_t>> edges;

  try {
    const auto children = CanonicalChildren(parent_state);
    edges.reserve(children.size());
    for (const auto& child : children) {
      const std::size_t child_id = InternState(child.state);
      if (nodes_[child_id].rank <= parent_rank) {
        throw std::invalid_argument(
            "PSK edge did not strictly increase semantic rank");
      }
      edges.emplace_back(child.move, child_id);
    }
    if (edges.empty()) {
      throw std::invalid_argument("a nonterminal Go state must have a pass edge");
    }
    for (std::size_t index = 1; index < edges.size(); ++index) {
      if (edges[index - 1].first == edges[index].first) {
        throw std::invalid_argument("generated child moves are not unique");
      }
    }

    // Publish only after every child is exact-interned and rank-checked.
    nodes_[node_id].children = edges;
    for (const auto& edge : edges) {
      nodes_[edge.second].parents.insert(node_id);
    }
    nodes_[node_id].expansion = NodeExpansion::kExpanded;
    committed_expansions_ += 1;
  } catch (...) {
    // Roll back every edge candidate, including a parent insertion that may
    // already have completed before a later allocation failed.
    for (const auto& edge : edges) {
      if (edge.second < nodes_.size()) {
        nodes_[edge.second].parents.erase(node_id);
      }
    }
    if (node_id < nodes_.size()) {
      nodes_[node_id].children.clear();
      nodes_[node_id].expansion = NodeExpansion::kUnexpanded;
    }
    committed_expansions_ = original_expansions;
    while (nodes_.size() > original_node_count) {
      exact_index_.erase(nodes_.back().state_bytes);
      nodes_.pop_back();
    }
    throw;
  }
}

void ProofNumberDAG::RecomputeAll() {
  // Process only ranks that actually occur.  This stays allocation-free after
  // an expansion commits graph facts, even when a caller supplies a large but
  // sparse 19x19 PSK history.  Every edge has a strictly greater rank, so all
  // children at the next selected rank have already been recomputed. Terminal
  // values are rederived from exact area score and threshold, while open leaves
  // always reset to (1, 1). This makes deserialized caches non-authoritative.
  std::uint64_t maximum_rank = 0;
  for (const auto& node : nodes_) maximum_rank = std::max(maximum_rank, node.rank);
  std::uint64_t rank = maximum_rank;
  while (true) {
    for (Node& node : nodes_) {
      if (node.rank != rank) continue;
      if (node.expansion == NodeExpansion::kUnexpanded) {
        node.proof = 1;
        node.disproof = 1;
        continue;
      }
      if (node.expansion == NodeExpansion::kTerminal) {
        const bool proven = AreaScore2(node.state, rules_) >= threshold2_;
        node.proof = proven ? 0 : kProofInfinity;
        node.disproof = proven ? kProofInfinity : 0;
        continue;
      }
      if (node.children.empty()) {
        throw std::invalid_argument("expanded node has no complete edge set");
      }

      const bool black_or_node = node.state.to_play == kBlack;
      std::uint64_t proof = black_or_node ? kProofInfinity : 0;
      std::uint64_t disproof = black_or_node ? 0 : kProofInfinity;
      for (const auto& edge : node.children) {
        const Node& child = CheckedNode(edge.second);
        if (child.rank <= node.rank) {
          throw std::invalid_argument("edge violates strict PSK rank ordering");
        }
        if (black_or_node) {
          proof = std::min(proof, child.proof);
          disproof = SaturatingAdd(disproof, child.disproof);
        } else {
          proof = SaturatingAdd(proof, child.proof);
          disproof = std::min(disproof, child.disproof);
        }
      }
      if (proof == 0 && disproof == 0) {
        throw std::invalid_argument("proof and disproof cannot both be zero");
      }
      node.proof = proof;
      node.disproof = disproof;
    }
    bool found_lower_rank = false;
    std::uint64_t next_rank = 0;
    for (const auto& node : nodes_) {
      if (node.rank < rank &&
          (!found_lower_rank || node.rank > next_rank)) {
        next_rank = node.rank;
        found_lower_rank = true;
      }
    }
    if (!found_lower_rank) break;
    rank = next_rank;
  }
}

std::size_t ProofNumberDAG::SelectMostProving() const {
  std::size_t node_id = root_id_;
  while (true) {
    const Node& node = CheckedNode(node_id);
    if (node.expansion != NodeExpansion::kExpanded || node.proof == 0 ||
        node.disproof == 0) {
      if (node.expansion != NodeExpansion::kUnexpanded) {
        throw std::invalid_argument(
            "most-proving traversal did not reach an open frontier");
      }
      return node_id;
    }
    if (node.children.empty()) {
      throw std::invalid_argument("expanded node has no children");
    }

    const bool black_or_node = node.state.to_play == kBlack;
    const auto better = [&](const auto& left, const auto& right) {
      const Node& left_child = CheckedNode(left.second);
      const Node& right_child = CheckedNode(right.second);
      const std::uint64_t left_primary =
          black_or_node ? left_child.proof : left_child.disproof;
      const std::uint64_t right_primary =
          black_or_node ? right_child.proof : right_child.disproof;
      if (left_primary != right_primary) return left_primary < right_primary;
      const std::uint64_t left_secondary =
          black_or_node ? left_child.disproof : left_child.proof;
      const std::uint64_t right_secondary =
          black_or_node ? right_child.disproof : right_child.proof;
      if (left_secondary != right_secondary) {
        return left_secondary < right_secondary;
      }
      if (left.first != right.first) return left.first < right.first;
      return left_child.state_bytes < right_child.state_bytes;
    };
    auto selected = node.children.end();
    for (auto candidate = node.children.begin(); candidate != node.children.end();
         ++candidate) {
      const Node& child = CheckedNode(candidate->second);
      // UINT64_MAX is both terminal infinity and the saturation value for a
      // still-open aggregate.  Excluding solved children is therefore
      // essential: otherwise a solved losing child can win a saturated tie
      // and traversal terminates at a non-frontier node.
      if (child.proof == 0 || child.disproof == 0) continue;
      if (selected == node.children.end() || better(*candidate, *selected)) {
        selected = candidate;
      }
    }
    if (selected == node.children.end()) {
      throw std::invalid_argument("unresolved parent has no unresolved child");
    }
    node_id = selected->second;
  }
}

ProofStatus ProofNumberDAG::Status(std::uint64_t proof,
                                   std::uint64_t disproof) {
  if (proof == 0 && disproof == 0) {
    throw std::invalid_argument("proof and disproof cannot both be zero");
  }
  if (proof == 0) return ProofStatus::kProven;
  if (disproof == 0) return ProofStatus::kDisproven;
  return ProofStatus::kUnknown;
}

ProofNumberDAGResult ProofNumberDAG::Advance(
    std::uint64_t additional_expansions) {
  RecomputeAll();
  std::uint64_t expanded = 0;
  while (nodes_[root_id_].proof != 0 && nodes_[root_id_].disproof != 0 &&
         expanded < additional_expansions) {
    const std::size_t frontier = SelectMostProving();
    ExpandNode(frontier);
    expanded += 1;
    RecomputeAll();
  }

  const Node& root = nodes_[root_id_];
  ProofNumberDAGResult result;
  result.status = Status(root.proof, root.disproof);
  result.threshold2 = threshold2_;
  result.proof_number = root.proof;
  result.disproof_number = root.disproof;
  result.expanded_this_call = expanded;
  result.committed_expansions = committed_expansions_;
  result.node_count = node_count();
  result.edge_count = edge_count();
  result.graph_sha256 = GraphSha256();
  return result;
}

std::optional<std::size_t> ProofNumberDAG::LookupStateId(
    const State& state) const {
  const State normalized = NormalizeState(state);
  const std::string state_bytes = CanonicalStateJson(normalized, rules_);
  const auto found = exact_index_.find(state_bytes);
  if (found == exact_index_.end()) return std::nullopt;
  return found->second;
}

const ProofNumberDAG::Node& ProofNumberDAG::CheckedNode(
    std::size_t node_id) const {
  if (node_id >= nodes_.size()) {
    throw std::out_of_range("proof DAG node ID is out of range");
  }
  return nodes_[node_id];
}

const State& ProofNumberDAG::StateForId(std::size_t node_id) const {
  return CheckedNode(node_id).state;
}

std::vector<std::size_t> ProofNumberDAG::ParentIdsFor(
    std::size_t node_id) const {
  const auto& parents = CheckedNode(node_id).parents;
  return {parents.begin(), parents.end()};
}

std::vector<std::pair<int, std::size_t>> ProofNumberDAG::ChildEdgesFor(
    std::size_t node_id) const {
  return CheckedNode(node_id).children;
}

NodeExpansion ProofNumberDAG::ExpansionFor(std::size_t node_id) const {
  return CheckedNode(node_id).expansion;
}

std::uint64_t ProofNumberDAG::RankFor(std::size_t node_id) const {
  return CheckedNode(node_id).rank;
}

void ProofNumberDAG::ExpandNodeForAudit(std::size_t node_id) {
  RecomputeAll();
  ExpandNode(node_id);
  RecomputeAll();
}

std::uint64_t ProofNumberDAG::node_count() const {
  return CheckedSize(nodes_.size(), "node count");
}

std::uint64_t ProofNumberDAG::edge_count() const {
  std::uint64_t total = 0;
  for (const auto& node : nodes_) {
    const std::uint64_t count = CheckedSize(node.children.size(), "edge count");
    if (total > kProofInfinity - count) {
      throw std::overflow_error("edge count exceeds uint64");
    }
    total += count;
  }
  return total;
}

std::string ProofNumberDAG::GraphSha256() const {
  std::string payload = "UGTS-CPP-PNDAG-GRAPH-v1;";
  AppendSignedScalar(payload, threshold2_);
  AppendScalar(payload, committed_expansions_);
  AppendScalar(payload, CheckedSize(root_id_, "root ID"));
  AppendScalar(payload, node_count());
  for (const auto& node : nodes_) {
    AppendScalar(payload, CheckedSize(node.node_id, "node ID"));
    AppendBytes(payload, node.state_bytes);
    AppendScalar(payload, node.rank);
    AppendScalar(payload, static_cast<std::uint64_t>(node.expansion));
    AppendScalar(payload, node.proof);
    AppendScalar(payload, node.disproof);
    AppendScalar(payload, CheckedSize(node.children.size(), "child count"));
    for (const auto& edge : node.children) {
      AppendSignedScalar(payload, static_cast<std::int64_t>(edge.first));
      AppendScalar(payload, CheckedSize(edge.second, "child ID"));
    }
  }
  return Sha256Hex(payload);
}

}  // namespace ugts_go19
