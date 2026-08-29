#include "ugts_go19/cuda_verified_expander.hpp"

#include <cuda_runtime.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace ugts_go19::cuda {
namespace {

std::size_t CheckedProduct(std::size_t left, std::size_t right,
                           const char *label) {
  if (left != 0U && right > std::numeric_limits<std::size_t>::max() / left) {
    throw CudaVerificationError(std::string(label) + " overflows size_t");
  }
  return left * right;
}

std::size_t CheckedAdd(std::size_t left, std::size_t right,
                       const char *label) {
  if (right > std::numeric_limits<std::size_t>::max() - left) {
    throw CudaVerificationError(std::string(label) + " overflows size_t");
  }
  return left + right;
}

std::size_t FractionFloor(std::size_t value, std::size_t numerator,
                          std::size_t denominator) {
  return CheckedAdd(
      CheckedProduct(value / denominator, numerator, "memory fraction"),
      CheckedProduct(value % denominator, numerator, "memory fraction") /
          denominator,
      "memory fraction");
}

template <typename T>
std::size_t BytesFor(std::size_t elements, const char *label) {
  return CheckedProduct(elements, sizeof(T), label);
}

void CheckCuda(cudaError_t status, const char *operation) {
  if (status != cudaSuccess) {
    throw CudaVerificationError(std::string(operation) + ": " +
                                cudaGetErrorString(status));
  }
}

template <typename T>
class DeviceBuffer {
 public:
  DeviceBuffer() = default;
  explicit DeviceBuffer(std::size_t count) : count_(count) {
    CheckCuda(cudaMalloc(reinterpret_cast<void **>(&pointer_),
                         BytesFor<T>(count, "device allocation")),
              "cudaMalloc");
  }

  DeviceBuffer(const DeviceBuffer &) = delete;
  DeviceBuffer &operator=(const DeviceBuffer &) = delete;

  ~DeviceBuffer() {
    if (pointer_ != nullptr) static_cast<void>(cudaFree(pointer_));
  }

  [[nodiscard]] T *get() const { return pointer_; }
  [[nodiscard]] std::size_t count() const { return count_; }

  void FreeChecked() {
    if (pointer_ == nullptr) return;
    T *pointer = pointer_;
    pointer_ = nullptr;
    count_ = 0;
    CheckCuda(cudaFree(pointer), "cudaFree");
  }

 private:
  T *pointer_ = nullptr;
  std::size_t count_ = 0;
};

std::string SlotLabel(std::size_t parent, int move) {
  std::ostringstream stream;
  stream << "state " << parent << " point " << move;
  return stream.str();
}

bool RawBoardSeen(const State &state, const std::vector<std::uint8_t> &board) {
  return std::find(state.seen_boards.begin(), state.seen_boards.end(), board) !=
         state.seen_boards.end();
}

void RequireZeroRejectedPayload(
    std::size_t candidate, std::size_t words,
    const std::vector<std::uint16_t> &captured,
    const std::vector<std::uint16_t> &self_captured,
    const std::vector<std::uint64_t> &child_black,
    const std::vector<std::uint64_t> &child_white, const std::string &label) {
  if (captured[candidate] != 0U || self_captured[candidate] != 0U) {
    throw CudaVerificationError(label + " has nonzero rejected counts");
  }
  const std::size_t base = candidate * words;
  for (std::size_t word = 0; word < words; ++word) {
    if (child_black[base + word] != 0U ||
        child_white[base + word] != 0U) {
      throw CudaVerificationError(label + " has nonzero rejected child data");
    }
  }
}

void RequireSameLocalChild(
    std::size_t candidate, const ApplyResult &expected,
    const std::vector<std::uint16_t> &captured,
    const std::vector<std::uint16_t> &self_captured,
    const std::vector<std::uint64_t> &child_black,
    const std::vector<std::uint64_t> &child_white, const std::string &label,
    std::uint64_t *compared_child_words) {
  if (expected.captured < 0 || expected.self_captured < 0 ||
      static_cast<unsigned int>(expected.captured) >
          std::numeric_limits<std::uint16_t>::max() ||
      static_cast<unsigned int>(expected.self_captured) >
          std::numeric_limits<std::uint16_t>::max()) {
    throw CudaVerificationError(label + " CPU capture count is out of range");
  }
  if (captured[candidate] != static_cast<std::uint16_t>(expected.captured) ||
      self_captured[candidate] !=
          static_cast<std::uint16_t>(expected.self_captured)) {
    throw CudaVerificationError(label + " capture-count mismatch");
  }
  const auto expected_black = PackBlackBitplane(expected.state);
  const auto expected_white = PackWhiteBitplane(expected.state);
  if (expected_black.size() != expected_white.size()) {
    throw CudaVerificationError(label + " CPU bitplane shape mismatch");
  }
  const std::size_t base = candidate * expected_black.size();
  for (std::size_t word = 0; word < expected_black.size(); ++word) {
    if (child_black[base + word] != expected_black[word] ||
        child_white[base + word] != expected_white[word]) {
      throw CudaVerificationError(label + " child bitplane mismatch");
    }
    *compared_child_words += 2U;
  }
}

void RequireGlobalMetadataMatchesLocal(const ApplyResult &global,
                                       const ApplyResult &local,
                                       const std::string &label) {
  if (global.captured != local.captured ||
      global.self_captured != local.self_captured ||
      global.state.board != local.state.board ||
      global.state.to_play != local.state.to_play ||
      global.state.passes != local.state.passes ||
      global.state.previous_board != local.state.previous_board ||
      global.state.ply != local.state.ply) {
    throw CudaVerificationError(label + " CPU local/global metadata mismatch");
  }
}

}  // namespace

std::size_t LocalPointDeviceBytesPerState(int board_size) {
  if (board_size < 1 ||
      board_size > static_cast<int>(kLocalPointMaximumBoardSize)) {
    throw std::invalid_argument("local-point board size must be in 1..19");
  }
  const std::size_t points =
      static_cast<std::size_t>(board_size * board_size);
  const std::size_t words = (points + 63U) / 64U;
  std::size_t bytes = 0;
  // Black, white, and empty bitplanes.
  bytes = CheckedAdd(bytes, BytesFor<std::uint64_t>(3U * words, "planes"),
                     "per-state bytes");
  bytes = CheckedAdd(bytes, sizeof(std::uint8_t), "per-state bytes");
  bytes = CheckedAdd(bytes, BytesFor<std::uint8_t>(points, "status"),
                     "per-state bytes");
  bytes = CheckedAdd(bytes,
                     BytesFor<std::uint16_t>(2U * points, "counts"),
                     "per-state bytes");
  bytes = CheckedAdd(
      bytes,
      BytesFor<std::uint64_t>(2U * points * words, "child planes"),
      "per-state bytes");
  return bytes;
}

VerifiedExpansionBatch VerifyCudaLocalPointTransitions(
    const std::vector<State> &states, const Rules &rules, void *stream) {
  if (states.empty()) {
    throw std::invalid_argument("verified CUDA batch cannot be empty");
  }
  if (rules.allow_suicide) {
    throw std::invalid_argument(
        "verified CUDA local transitions require no-suicide rules");
  }
  if (rules.size < 1 ||
      rules.size > static_cast<int>(kLocalPointMaximumBoardSize)) {
    throw std::invalid_argument("verified CUDA board size must be in 1..19");
  }
  for (const auto &state : states) {
    // CanonicalStateJson performs the exact C++ state/rules validation without
    // changing game state.
    static_cast<void>(CanonicalStateJson(state, rules));
    if (state.Terminal(rules)) {
      throw std::invalid_argument(
          "terminal states must remain on the CPU transition path");
    }
    if (state.ply == std::numeric_limits<std::uint64_t>::max()) {
      throw std::overflow_error(
          "ply-exhausted states must remain on the CPU transition path");
    }
  }

  const std::size_t state_count = states.size();
  const std::size_t points =
      static_cast<std::size_t>(rules.size * rules.size);
  const std::size_t words = (points + 63U) / 64U;
  const std::size_t state_words =
      CheckedProduct(state_count, words, "state word count");
  const std::size_t candidate_count =
      CheckedProduct(state_count, points, "candidate count");
  const std::size_t child_word_count =
      CheckedProduct(candidate_count, words, "child word count");

  const std::size_t per_state = LocalPointDeviceBytesPerState(rules.size);
  const std::size_t requested =
      CheckedAdd(CheckedProduct(per_state, state_count, "batch bytes"),
                 sizeof(std::uint32_t), "batch bytes");
  std::size_t free_bytes = 0;
  std::size_t total_bytes = 0;
  CheckCuda(cudaMemGetInfo(&free_bytes, &total_bytes), "cudaMemGetInfo");
  if (total_bytes == 0U || free_bytes > total_bytes) {
    throw CudaVerificationError(
        "cudaMemGetInfo returned inconsistent memory totals");
  }
  const std::size_t reserve = FractionFloor(free_bytes, 18U, 100U);
  const std::size_t workspace_budget =
      FractionFloor(free_bytes - reserve, 16U, 100U);
  if (requested > workspace_budget) {
    throw CudaVerificationError(
        "verified CUDA batch exceeds the 16% post-reserve workspace budget");
  }

  std::vector<std::uint64_t> host_black;
  std::vector<std::uint64_t> host_white;
  std::vector<std::uint8_t> host_to_play;
  host_black.reserve(state_words);
  host_white.reserve(state_words);
  host_to_play.reserve(state_count);
  for (const auto &state : states) {
    const auto black = PackBlackBitplane(state);
    const auto white = PackWhiteBitplane(state);
    host_black.insert(host_black.end(), black.begin(), black.end());
    host_white.insert(host_white.end(), white.begin(), white.end());
    host_to_play.push_back(state.to_play);
  }

  DeviceBuffer<std::uint64_t> device_black(state_words);
  DeviceBuffer<std::uint64_t> device_white(state_words);
  DeviceBuffer<std::uint8_t> device_to_play(state_count);
  DeviceBuffer<std::uint64_t> device_empty(state_words);
  DeviceBuffer<std::uint8_t> device_status(candidate_count);
  DeviceBuffer<std::uint16_t> device_captured(candidate_count);
  DeviceBuffer<std::uint16_t> device_self_captured(candidate_count);
  DeviceBuffer<std::uint64_t> device_child_black(child_word_count);
  DeviceBuffer<std::uint64_t> device_child_white(child_word_count);
  DeviceBuffer<std::uint32_t> device_error_bits(1U);

  const auto cuda_stream = static_cast<cudaStream_t>(stream);
  CheckCuda(cudaMemcpyAsync(device_black.get(), host_black.data(),
                            BytesFor<std::uint64_t>(state_words,
                                                    "black upload"),
                            cudaMemcpyHostToDevice, cuda_stream),
            "cudaMemcpyAsync black upload");
  CheckCuda(cudaMemcpyAsync(device_white.get(), host_white.data(),
                            BytesFor<std::uint64_t>(state_words,
                                                    "white upload"),
                            cudaMemcpyHostToDevice, cuda_stream),
            "cudaMemcpyAsync white upload");
  CheckCuda(cudaMemcpyAsync(device_to_play.get(), host_to_play.data(),
                            BytesFor<std::uint8_t>(state_count,
                                                   "player upload"),
                            cudaMemcpyHostToDevice, cuda_stream),
            "cudaMemcpyAsync player upload");

  LaunchLocalPointTransitions(
      device_black.get(), device_white.get(), device_to_play.get(),
      device_empty.get(), device_status.get(), device_captured.get(),
      device_self_captured.get(), device_child_black.get(),
      device_child_white.get(), device_error_bits.get(), state_count,
      rules.size, stream);

  std::vector<std::uint8_t> host_status(candidate_count);
  std::vector<std::uint16_t> host_captured(candidate_count);
  std::vector<std::uint16_t> host_self_captured(candidate_count);
  std::vector<std::uint64_t> host_child_black(child_word_count);
  std::vector<std::uint64_t> host_child_white(child_word_count);
  std::uint32_t host_error_bits = 0;
  CheckCuda(cudaMemcpyAsync(host_status.data(), device_status.get(),
                            BytesFor<std::uint8_t>(candidate_count,
                                                   "status download"),
                            cudaMemcpyDeviceToHost, cuda_stream),
            "cudaMemcpyAsync status download");
  CheckCuda(cudaMemcpyAsync(host_captured.data(), device_captured.get(),
                            BytesFor<std::uint16_t>(candidate_count,
                                                    "capture download"),
                            cudaMemcpyDeviceToHost, cuda_stream),
            "cudaMemcpyAsync capture download");
  CheckCuda(cudaMemcpyAsync(host_self_captured.data(),
                            device_self_captured.get(),
                            BytesFor<std::uint16_t>(candidate_count,
                                                    "self-capture download"),
                            cudaMemcpyDeviceToHost, cuda_stream),
            "cudaMemcpyAsync self-capture download");
  CheckCuda(cudaMemcpyAsync(host_child_black.data(), device_child_black.get(),
                            BytesFor<std::uint64_t>(child_word_count,
                                                    "black-child download"),
                            cudaMemcpyDeviceToHost, cuda_stream),
            "cudaMemcpyAsync black-child download");
  CheckCuda(cudaMemcpyAsync(host_child_white.data(), device_child_white.get(),
                            BytesFor<std::uint64_t>(child_word_count,
                                                    "white-child download"),
                            cudaMemcpyDeviceToHost, cuda_stream),
            "cudaMemcpyAsync white-child download");
  CheckCuda(cudaMemcpyAsync(&host_error_bits, device_error_bits.get(),
                            sizeof(host_error_bits), cudaMemcpyDeviceToHost,
                            cuda_stream),
            "cudaMemcpyAsync error-bits download");
  CheckCuda(cudaStreamSynchronize(cuda_stream), "cudaStreamSynchronize");

  // Resource cleanup happens before semantic replay. A cleanup failure also
  // prevents any result from crossing the verification boundary.
  device_error_bits.FreeChecked();
  device_child_white.FreeChecked();
  device_child_black.FreeChecked();
  device_self_captured.FreeChecked();
  device_captured.FreeChecked();
  device_status.FreeChecked();
  device_empty.FreeChecked();
  device_to_play.FreeChecked();
  device_white.FreeChecked();
  device_black.FreeChecked();

  if (host_error_bits != 0U) {
    throw CudaVerificationError("CUDA local-point batch reported fatal error bits");
  }

  VerifiedExpansionBatch verified;
  verified.stats.states = static_cast<std::uint64_t>(state_count);
  verified.stats.point_slots = static_cast<std::uint64_t>(candidate_count);
  verified.slots.reserve(candidate_count);
  for (std::size_t parent = 0; parent < state_count; ++parent) {
    const State &state = states[parent];
    for (int move = 0; move < static_cast<int>(points); ++move) {
      const std::size_t candidate =
          parent * points + static_cast<std::size_t>(move);
      const std::string label = SlotLabel(parent, move);
      const auto gpu_status =
          static_cast<LocalPointStatus>(host_status[candidate]);
      if (gpu_status == LocalPointStatus::kUnwritten ||
          gpu_status == LocalPointStatus::kInvalidInput ||
          gpu_status == LocalPointStatus::kInternalFailure) {
        throw CudaVerificationError(label + " has a fatal GPU status");
      }

      VerifiedPointSlot slot;
      slot.parent_index = parent;
      slot.move = move;
      slot.local_status = gpu_status;

      if (state.board[static_cast<std::size_t>(move)] != kEmpty) {
        if (gpu_status != LocalPointStatus::kOccupied) {
          throw CudaVerificationError(label + " occupied-status mismatch");
        }
        RequireZeroRejectedPayload(candidate, words, host_captured,
                                   host_self_captured, host_child_black,
                                   host_child_white, label);
        bool cpu_rejected = false;
        try {
          static_cast<void>(ApplyMove(state, move, rules));
        } catch (const IllegalMove &) {
          cpu_rejected = true;
        }
        if (!cpu_rejected) {
          throw CudaVerificationError(label + " CPU accepted an occupied point");
        }
        ++verified.stats.occupied;
        verified.slots.push_back(std::move(slot));
        continue;
      }

      State local_state;
      local_state.size = state.size;
      local_state.board = state.board;
      local_state.to_play = state.to_play;
      local_state.passes = state.passes;
      local_state.seen_boards.push_back(local_state.board);
      local_state.previous_board = std::nullopt;
      local_state.ply = state.ply;
      std::optional<ApplyResult> local_result;
      try {
        local_result = ApplyMove(local_state, move, rules);
      } catch (const IllegalMove &) {
        // With a validated nonterminal, non-exhausted state, an empty point,
        // no-suicide rules, and history reduced to the current board, the only
        // ordinary local rejection is suicide.
      }

      if (!local_result.has_value()) {
        if (gpu_status != LocalPointStatus::kSuicide) {
          throw CudaVerificationError(label + " suicide-status mismatch");
        }
        RequireZeroRejectedPayload(candidate, words, host_captured,
                                   host_self_captured, host_child_black,
                                   host_child_white, label);
        bool cpu_rejected = false;
        try {
          static_cast<void>(ApplyMove(state, move, rules));
        } catch (const IllegalMove &) {
          cpu_rejected = true;
        }
        if (!cpu_rejected) {
          throw CudaVerificationError(label + " CPU accepted a suicide point");
        }
        ++verified.stats.suicides;
        verified.slots.push_back(std::move(slot));
        continue;
      }

      if (gpu_status != LocalPointStatus::kCandidateNeedsSuperko) {
        throw CudaVerificationError(label + " local-candidate status mismatch");
      }
      RequireSameLocalChild(candidate, *local_result, host_captured,
                            host_self_captured, host_child_black,
                            host_child_white, label,
                            &verified.stats.compared_child_words);
      slot.captured = host_captured[candidate];
      slot.self_captured = host_self_captured[candidate];
      slot.local_child_board = local_result->state.board;
      ++verified.stats.local_candidates;

      const bool seen = RawBoardSeen(state, local_result->state.board);
      if (seen) {
        bool rejected = false;
        try {
          static_cast<void>(ApplyMove(state, move, rules));
        } catch (const IllegalMove &) {
          rejected = true;
        }
        if (!rejected) {
          throw CudaVerificationError(label + " CPU failed to reject exact PSK");
        }
        slot.superko_rejected = true;
        ++verified.stats.superko_rejections;
      } else {
        ApplyResult global_result;
        try {
          global_result = ApplyMove(state, move, rules);
        } catch (const IllegalMove &) {
          throw CudaVerificationError(
              label + " CPU rejected a non-repeating local candidate");
        }
        RequireGlobalMetadataMatchesLocal(global_result, *local_result, label);
        slot.globally_legal = true;
        verified.legal_children.push_back(
            {parent, move, std::move(global_result)});
        ++verified.stats.globally_legal_children;
      }
      verified.slots.push_back(std::move(slot));
    }
  }
  return verified;
}

}  // namespace ugts_go19::cuda
