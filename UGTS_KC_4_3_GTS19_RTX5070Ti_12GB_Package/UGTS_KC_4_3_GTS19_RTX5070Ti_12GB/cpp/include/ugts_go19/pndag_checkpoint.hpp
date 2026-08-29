#pragma once

#include "ugts_go19/pndag.hpp"

#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>

namespace ugts_go19 {

inline constexpr const char* kNativePNDAGCheckpointFormat =
    "UGTS-CPP-PNDAG-CHECKPOINT-v1";
inline constexpr const char* kNativePNDAGCheckpointTipFormat =
    "UGTS-CPP-PNDAG-CHECKPOINT-TIP-v1";

// These are hard decoder/allocation guards, not a claim that the live proof
// DAG has a campaign-scale memory bound. Callers may lower or explicitly raise
// them, but a rejected checkpoint never becomes proof-authoritative.
struct NativePNDAGCheckpointLimits {
  std::uint64_t max_file_bytes = 1ULL << 30U;
  std::uint64_t max_nodes = 2'000'000;
  std::uint64_t max_edges = 50'000'000;
  std::uint64_t max_history_members = 20'000'000;
  std::uint64_t max_lineage_generations = 1'024;
};

struct NativePNDAGCheckpointTip {
  std::uint64_t generation = 0;
  std::optional<std::string> previous_checkpoint_file_sha256;
  std::string checkpoint_file_sha256;
  std::string checkpoint_payload_sha256;
  std::string run_sha256;
  std::string root_state_object_id;
  std::string graph_sha256;
  std::uint64_t committed_expansions = 0;
  std::uint64_t node_count = 0;
  std::uint64_t edge_count = 0;
  std::uint64_t byte_length = 0;
  ProofStatus status = ProofStatus::kUnknown;
  std::filesystem::path path;
};

struct NativePNDAGLoadedCheckpoint;
struct NativePNDAGEncodedCheckpoint;

// Exact full-snapshot codec plus immutable content-addressed publication.
// There is deliberately no CURRENT pointer and no newest-generation scan.
// Resume is legal only through an exact externally supplied full-file hash.
class NativePNDAGCheckpointCodec {
 public:
  [[nodiscard]] static NativePNDAGCheckpointTip Publish(
      const std::filesystem::path& store_root, ProofNumberDAG& dag,
      const std::optional<NativePNDAGCheckpointTip>& previous_tip = std::nullopt,
      const NativePNDAGCheckpointLimits& limits = {});

  [[nodiscard]] static NativePNDAGLoadedCheckpoint Load(
      const std::filesystem::path& checkpoint_path,
      const std::string& expected_checkpoint_file_sha256,
      const Rules& expected_rules, std::int64_t expected_threshold2,
      const State& expected_root_state,
      const NativePNDAGCheckpointLimits& limits = {});

 private:
  [[nodiscard]] static ProofStatus RootStatus(const ProofNumberDAG& dag);
  static void ValidateStructureAndEdges(ProofNumberDAG& dag);
  static void ValidateForSave(ProofNumberDAG& dag);
  static void ValidateExtension(const ProofNumberDAG& previous,
                                const ProofNumberDAG& newer);
  [[nodiscard]] static std::uint64_t TotalHistoryMembers(
      const ProofNumberDAG& dag);
  [[nodiscard]] static NativePNDAGEncodedCheckpoint EncodeCheckpoint(
      ProofNumberDAG& dag, std::uint64_t generation,
      const std::optional<NativePNDAGCheckpointTip>& previous_tip,
      const NativePNDAGCheckpointLimits& limits);
  [[nodiscard]] static NativePNDAGLoadedCheckpoint DecodeCheckpoint(
      std::string bytes, const std::filesystem::path& path,
      const std::string& expected_file_sha256, const Rules& expected_rules,
      std::int64_t expected_threshold2, const State& expected_root_state,
      const NativePNDAGCheckpointLimits& limits);
};

struct NativePNDAGLoadedCheckpoint {
  ProofNumberDAG dag;
  NativePNDAGCheckpointTip tip;
};

}  // namespace ugts_go19
