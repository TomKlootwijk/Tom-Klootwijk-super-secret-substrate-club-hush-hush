#pragma once

#include "ugts_go19/go_state.hpp"
#include "packed_kernels.cuh"

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace ugts_go19::cuda {

class CudaVerificationError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

struct VerifiedPointSlot {
  std::size_t parent_index = 0;
  int move = 0;
  LocalPointStatus local_status = LocalPointStatus::kUnwritten;
  std::uint16_t captured = 0;
  std::uint16_t self_captured = 0;
  // Present only for kCandidateNeedsSuperko. These are CPU-recomputed bytes
  // after the GPU payload has matched exactly.
  std::vector<std::uint8_t> local_child_board;
  bool superko_rejected = false;
  bool globally_legal = false;
};

struct VerifiedPointChild {
  std::size_t parent_index = 0;
  int move = 0;
  // The CPU ApplyMove result is the authority returned to callers. GPU-owned
  // state is never exposed to proof coordination.
  ApplyResult result;
};

struct VerifiedExpansionStats {
  std::uint64_t states = 0;
  std::uint64_t point_slots = 0;
  std::uint64_t occupied = 0;
  std::uint64_t suicides = 0;
  std::uint64_t local_candidates = 0;
  std::uint64_t superko_rejections = 0;
  std::uint64_t globally_legal_children = 0;
  std::uint64_t compared_child_words = 0;
};

struct VerifiedExpansionBatch {
  VerifiedExpansionStats stats;
  std::vector<VerifiedPointSlot> slots;
  std::vector<VerifiedPointChild> legal_children;
};

// Exact device allocation cost per state for the dense local-transition
// buffers, excluding one four-byte batch error word and allocator overhead.
[[nodiscard]] std::size_t LocalPointDeviceBytesPerState(int board_size);

// Synchronous fail-closed boundary around the asynchronous kernel. Every point
// is recomputed with the existing CPU rules engine, including GPU rejections;
// every local candidate is checked against exact raw PSK history and ordinary
// ApplyMove. Pass remains CPU-only. Any CUDA/runtime/status/field mismatch
// throws before a result is returned.
[[nodiscard]] VerifiedExpansionBatch VerifyCudaLocalPointTransitions(
    const std::vector<State> &states, const Rules &rules,
    void *stream = nullptr);

}  // namespace ugts_go19::cuda
