#include "packed_kernels.cuh"

#include <cuda_runtime.h>

#include <algorithm>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace ugts_go19::cuda {
namespace {

constexpr unsigned int kFullWarpMask = 0xffffffffU;

struct LocalPointTopology {
  std::uint64_t valid[kLocalPointMaximumWords]{};
  std::uint64_t can_move_left[kLocalPointMaximumWords]{};
  std::uint64_t can_move_right[kLocalPointMaximumWords]{};
  int board_size = 0;
  int points = 0;
  int words = 0;
};

struct ByteRange {
  std::uintptr_t begin = 0;
  std::uintptr_t end = 0;
  const char *label = nullptr;
};

std::size_t CheckedProduct(std::size_t left, std::size_t right,
                           const char *label) {
  if (left != 0U && right > std::numeric_limits<std::size_t>::max() / left) {
    throw std::overflow_error(std::string(label) + " overflows size_t");
  }
  return left * right;
}

template <typename T>
ByteRange MakeRange(const T *pointer, std::size_t elements,
                    const char *label) {
  const std::size_t bytes = CheckedProduct(elements, sizeof(T), label);
  const auto begin = reinterpret_cast<std::uintptr_t>(pointer);
  if (begin > std::numeric_limits<std::uintptr_t>::max() - bytes) {
    throw std::overflow_error(std::string(label) + " address range overflows");
  }
  return {begin, begin + bytes, label};
}

bool Overlap(const ByteRange &left, const ByteRange &right) {
  return left.begin < right.end && right.begin < left.end;
}

void RequireWritableRangesDisjoint(const std::vector<ByteRange> &inputs,
                                   const std::vector<ByteRange> &outputs) {
  for (const auto &output : outputs) {
    for (const auto &input : inputs) {
      if (Overlap(output, input)) {
        throw std::invalid_argument(std::string(output.label) +
                                    " overlaps " + input.label);
      }
    }
  }
  for (std::size_t left = 0; left < outputs.size(); ++left) {
    for (std::size_t right = left + 1U; right < outputs.size(); ++right) {
      if (Overlap(outputs[left], outputs[right])) {
        throw std::invalid_argument(std::string(outputs[left].label) +
                                    " overlaps " + outputs[right].label);
      }
    }
  }
}

LocalPointTopology BuildTopology(int board_size) {
  LocalPointTopology topology;
  topology.board_size = board_size;
  topology.points = board_size * board_size;
  topology.words = (topology.points + 63) / 64;
  for (int point = 0; point < topology.points; ++point) {
    const int word = point / 64;
    const auto bit = UINT64_C(1) << static_cast<unsigned int>(point % 64);
    topology.valid[word] |= bit;
    const int x = point % board_size;
    if (x > 0) topology.can_move_left[word] |= bit;
    if (x + 1 < board_size) topology.can_move_right[word] |= bit;
  }
  return topology;
}

__global__ void EmptyMaskKernel(const std::uint64_t *black,
                                const std::uint64_t *white,
                                std::uint64_t *empty, std::size_t total_words,
                                std::size_t words_per_state,
                                std::uint64_t tail_mask) {
  std::size_t index = static_cast<std::size_t>(blockIdx.x) *
                          static_cast<std::size_t>(blockDim.x) +
                      static_cast<std::size_t>(threadIdx.x);
  const std::size_t stride = static_cast<std::size_t>(gridDim.x) *
                             static_cast<std::size_t>(blockDim.x);
  while (index < total_words) {
    std::uint64_t value = ~(black[index] | white[index]);
    if (index % words_per_state == words_per_state - 1U)
      value &= tail_mask;
    empty[index] = value;

    // Avoid a size_t wrap even for a formally maximal launch shape.
    if (total_words - index <= stride)
      break;
    index += stride;
  }
}

__device__ __forceinline__ std::uint64_t WarpShiftLeft(
    std::uint64_t word, int amount, unsigned int lane) {
  std::uint64_t lower = __shfl_up_sync(kFullWarpMask, word, 1U);
  if (lane == 0U) lower = 0U;
  return (word << static_cast<unsigned int>(amount)) |
         (lower >> static_cast<unsigned int>(64 - amount));
}

__device__ __forceinline__ std::uint64_t WarpShiftRight(
    std::uint64_t word, int amount, unsigned int lane) {
  std::uint64_t upper = __shfl_down_sync(kFullWarpMask, word, 1U);
  if (lane == 31U) upper = 0U;
  return (word >> static_cast<unsigned int>(amount)) |
         (upper << static_cast<unsigned int>(64 - amount));
}

__device__ __forceinline__ std::uint64_t NeighborWord(
    std::uint64_t stones, const LocalPointTopology &topology,
    unsigned int lane) {
  const bool active = lane < static_cast<unsigned int>(topology.words);
  const std::uint64_t active_stones = active ? stones : UINT64_C(0);
  const unsigned int mask_lane =
      lane < kLocalPointMaximumWords ? lane : 0U;
  const std::uint64_t horizontal_left = WarpShiftRight(
      active_stones & topology.can_move_left[mask_lane],
      1, lane);
  const std::uint64_t horizontal_right = WarpShiftLeft(
      active_stones & topology.can_move_right[mask_lane],
      1, lane);
  const std::uint64_t vertical_up =
      WarpShiftRight(stones, topology.board_size, lane);
  const std::uint64_t vertical_down =
      WarpShiftLeft(stones, topology.board_size, lane);
  const std::uint64_t valid = active ? topology.valid[lane] : UINT64_C(0);
  return (horizontal_left | horizontal_right | vertical_up | vertical_down) &
         valid;
}

__device__ bool FloodGroup(std::uint64_t seed, std::uint64_t color,
                           const LocalPointTopology &topology,
                           unsigned int lane, std::uint64_t *group) {
  *group = seed;
  for (int iteration = 0; iteration < topology.points; ++iteration) {
    const std::uint64_t expanded =
        *group | (NeighborWord(*group, topology, lane) & color);
    const bool changed = expanded != *group;
    *group = expanded;
    if (!__any_sync(kFullWarpMask, changed)) return true;
  }
  return false;
}

__device__ __forceinline__ int NeighborSeed(int move, int direction,
                                             int board_size) {
  const int x = move % board_size;
  const int y = move / board_size;
  if (direction == 0) return x > 0 ? move - 1 : -1;
  if (direction == 1) return x + 1 < board_size ? move + 1 : -1;
  if (direction == 2) return y > 0 ? move - board_size : -1;
  return y + 1 < board_size ? move + board_size : -1;
}

__global__ void LocalPointTransitionKernel(
    const std::uint64_t *black, const std::uint64_t *white,
    const std::uint8_t *to_play, const std::uint64_t *empty,
    std::uint8_t *status, std::uint16_t *captured,
    std::uint16_t *self_captured, std::uint64_t *child_black,
    std::uint64_t *child_white, std::uint32_t *batch_error_bits,
    std::size_t states, std::size_t candidate_count,
    LocalPointTopology topology) {
  const unsigned int lane = threadIdx.x & 31U;
  std::size_t candidate =
      (static_cast<std::size_t>(blockIdx.x) *
           static_cast<std::size_t>(blockDim.x) +
       static_cast<std::size_t>(threadIdx.x)) /
      32U;
  const std::size_t warp_stride =
      static_cast<std::size_t>(gridDim.x) *
      (static_cast<std::size_t>(blockDim.x) / 32U);

  while (candidate < candidate_count) {
    const std::size_t state =
        candidate / static_cast<std::size_t>(topology.points);
    const int move = static_cast<int>(
        candidate % static_cast<std::size_t>(topology.points));
    const std::size_t state_base =
        state * static_cast<std::size_t>(topology.words);
    const std::size_t child_base =
        candidate * static_cast<std::size_t>(topology.words);
    const bool active_word = lane < static_cast<unsigned int>(topology.words);
    const std::uint64_t valid =
        active_word ? topology.valid[lane] : UINT64_C(0);
    const std::uint64_t black_word =
        active_word ? black[state_base + lane] : UINT64_C(0);
    const std::uint64_t white_word =
        active_word ? white[state_base + lane] : UINT64_C(0);
    const std::uint64_t empty_word =
        active_word ? empty[state_base + lane] : UINT64_C(0);

    if (active_word) {
      child_black[child_base + lane] = 0U;
      child_white[child_base + lane] = 0U;
    }
    if (lane == 0U) {
      captured[candidate] = 0U;
      self_captured[candidate] = 0U;
    }

    int player = lane == 0U ? static_cast<int>(to_play[state]) : 0;
    player = __shfl_sync(kFullWarpMask, player, 0);
    const bool invalid_word = (black_word & white_word) != 0U ||
                              ((black_word | white_word) & ~valid) != 0U;
    const bool invalid = __any_sync(kFullWarpMask, invalid_word) ||
                         (player != 1 && player != 2) || state >= states;
    if (invalid) {
      if (lane == 0U) {
        status[candidate] =
            static_cast<std::uint8_t>(LocalPointStatus::kInvalidInput);
        atomicOr(batch_error_bits, kLocalPointInvalidInputError);
      }
      if (candidate_count - candidate <= warp_stride) break;
      candidate += warp_stride;
      continue;
    }

    const std::uint64_t expected_empty = ~(black_word | white_word) & valid;
    if (__any_sync(kFullWarpMask, expected_empty != empty_word)) {
      if (lane == 0U) {
        status[candidate] =
            static_cast<std::uint8_t>(LocalPointStatus::kInternalFailure);
        atomicOr(batch_error_bits, kLocalPointInternalError);
      }
      if (candidate_count - candidate <= warp_stride) break;
      candidate += warp_stride;
      continue;
    }

    const int move_word = move / 64;
    const std::uint64_t move_bit =
        UINT64_C(1) << static_cast<unsigned int>(move % 64);
    int move_is_empty =
        static_cast<int>(lane) == move_word && (empty_word & move_bit) != 0U;
    move_is_empty =
        __shfl_sync(kFullWarpMask, move_is_empty, move_word);
    if (!move_is_empty) {
      if (lane == 0U) {
        status[candidate] =
            static_cast<std::uint8_t>(LocalPointStatus::kOccupied);
      }
      if (candidate_count - candidate <= warp_stride) break;
      candidate += warp_stride;
      continue;
    }

    const std::uint64_t own_original = player == 1 ? black_word : white_word;
    const std::uint64_t opponent = player == 1 ? white_word : black_word;
    const std::uint64_t own =
        own_original |
        (static_cast<int>(lane) == move_word ? move_bit : UINT64_C(0));
    const std::uint64_t empty_after_move =
        empty_word &
        ~(static_cast<int>(lane) == move_word ? move_bit : UINT64_C(0));
    std::uint64_t checked = 0U;
    std::uint64_t captured_words = 0U;
    bool internal_failure = false;

    for (int direction = 0; direction < 4; ++direction) {
      int seed = lane == 0U
                     ? NeighborSeed(move, direction, topology.board_size)
                     : -1;
      seed = __shfl_sync(kFullWarpMask, seed, 0);
      if (seed < 0) continue;
      const int seed_word = seed / 64;
      const std::uint64_t seed_bit =
          UINT64_C(1) << static_cast<unsigned int>(seed % 64);
      int should_visit = static_cast<int>(lane) == seed_word &&
                         (opponent & seed_bit) != 0U &&
                         (checked & seed_bit) == 0U;
      should_visit =
          __shfl_sync(kFullWarpMask, should_visit, seed_word);
      if (!should_visit) continue;

      const std::uint64_t group_seed =
          static_cast<int>(lane) == seed_word ? seed_bit : UINT64_C(0);
      std::uint64_t group = 0U;
      if (!FloodGroup(group_seed, opponent, topology, lane, &group)) {
        internal_failure = true;
        break;
      }
      checked |= group;
      const bool has_liberty = __any_sync(
          kFullWarpMask,
          (NeighborWord(group, topology, lane) & empty_after_move) != 0U);
      if (!has_liberty) captured_words |= group;
    }

    if (internal_failure) {
      if (lane == 0U) {
        status[candidate] =
            static_cast<std::uint8_t>(LocalPointStatus::kInternalFailure);
        atomicOr(batch_error_bits, kLocalPointInternalError);
      }
      if (candidate_count - candidate <= warp_stride) break;
      candidate += warp_stride;
      continue;
    }

    const std::uint64_t opponent_after = opponent & ~captured_words;
    const std::uint64_t empty_after_capture =
        (empty_after_move | captured_words) & valid;
    const std::uint64_t own_seed =
        static_cast<int>(lane) == move_word ? move_bit : UINT64_C(0);
    std::uint64_t own_group = 0U;
    if (!FloodGroup(own_seed, own, topology, lane, &own_group)) {
      if (lane == 0U) {
        status[candidate] =
            static_cast<std::uint8_t>(LocalPointStatus::kInternalFailure);
        atomicOr(batch_error_bits, kLocalPointInternalError);
      }
      if (candidate_count - candidate <= warp_stride) break;
      candidate += warp_stride;
      continue;
    }
    const bool own_has_liberty = __any_sync(
        kFullWarpMask,
        (NeighborWord(own_group, topology, lane) & empty_after_capture) != 0U);
    if (!own_has_liberty) {
      if (lane == 0U) {
        status[candidate] =
            static_cast<std::uint8_t>(LocalPointStatus::kSuicide);
      }
      if (candidate_count - candidate <= warp_stride) break;
      candidate += warp_stride;
      continue;
    }

    unsigned int capture_count = __popcll(captured_words);
    for (int offset = 16; offset > 0; offset /= 2) {
      capture_count +=
          __shfl_down_sync(kFullWarpMask, capture_count, offset);
    }
    if (active_word) {
      child_black[child_base + lane] = player == 1 ? own : opponent_after;
      child_white[child_base + lane] = player == 1 ? opponent_after : own;
    }
    if (lane == 0U) {
      captured[candidate] = static_cast<std::uint16_t>(capture_count);
      status[candidate] = static_cast<std::uint8_t>(
          LocalPointStatus::kCandidateNeedsSuperko);
    }

    if (candidate_count - candidate <= warp_stride) break;
    candidate += warp_stride;
  }
}

} // namespace

void LaunchEmptyMask(const std::uint64_t *black, const std::uint64_t *white,
                     std::uint64_t *empty, std::size_t states,
                     std::size_t words_per_state, std::uint64_t tail_mask,
                     void *stream) {
  if (!black || !white || !empty || states == 0 || words_per_state == 0) {
    throw std::invalid_argument("invalid empty-mask launch arguments");
  }
  if (states > std::numeric_limits<std::size_t>::max() / words_per_state) {
    throw std::overflow_error("empty-mask word count overflows size_t");
  }
  const std::size_t total = states * words_per_state;
  // CUDA guarantees at least 65,535 blocks in grid dimension x. A capped
  // grid-stride launch avoids narrowing or grid-limit overflow for large
  // batches while retaining deterministic one-writer-per-word behavior.
  const std::size_t required_blocks =
      1U + (total - 1U) / kEmptyMaskThreadsPerBlock;
  const auto blocks = static_cast<unsigned int>(
      std::min(required_blocks, kEmptyMaskMaximumBlocks));
  EmptyMaskKernel<<<blocks, kEmptyMaskThreadsPerBlock, 0,
                    static_cast<cudaStream_t>(stream)>>>(
      black, white, empty, total, words_per_state, tail_mask);
  const auto status = cudaGetLastError();
  if (status != cudaSuccess) {
    throw std::runtime_error(std::string("empty-mask CUDA launch failed: ") +
                             cudaGetErrorString(status));
  }
}

void LaunchLocalPointTransitions(
    const std::uint64_t *black, const std::uint64_t *white,
    const std::uint8_t *to_play, std::uint64_t *empty_workspace,
    std::uint8_t *status, std::uint16_t *captured,
    std::uint16_t *self_captured, std::uint64_t *child_black,
    std::uint64_t *child_white, std::uint32_t *batch_error_bits,
    std::size_t states, int board_size, void *stream) {
  if (!black || !white || !to_play || !empty_workspace || !status ||
      !captured || !self_captured || !child_black || !child_white ||
      !batch_error_bits || states == 0U) {
    throw std::invalid_argument("invalid local-point launch arguments");
  }
  if (board_size < 1 ||
      board_size > static_cast<int>(kLocalPointMaximumBoardSize)) {
    throw std::invalid_argument("local-point board size must be in 1..19");
  }
  const LocalPointTopology topology = BuildTopology(board_size);
  const std::size_t points = static_cast<std::size_t>(topology.points);
  const std::size_t words = static_cast<std::size_t>(topology.words);
  const std::size_t state_words =
      CheckedProduct(states, words, "local-point state word count");
  const std::size_t candidates =
      CheckedProduct(states, points, "local-point candidate count");
  const std::size_t child_words =
      CheckedProduct(candidates, words, "local-point child word count");

  const std::vector<ByteRange> inputs = {
      MakeRange(black, state_words, "black input"),
      MakeRange(white, state_words, "white input"),
      MakeRange(to_play, states, "player input"),
  };
  const std::vector<ByteRange> outputs = {
      MakeRange(empty_workspace, state_words, "empty workspace"),
      MakeRange(status, candidates, "status output"),
      MakeRange(captured, candidates, "capture output"),
      MakeRange(self_captured, candidates, "self-capture output"),
      MakeRange(child_black, child_words, "black-child output"),
      MakeRange(child_white, child_words, "white-child output"),
      MakeRange(batch_error_bits, 1U, "batch-error output"),
  };
  RequireWritableRangesDisjoint(inputs, outputs);

  const auto cuda_stream = static_cast<cudaStream_t>(stream);
  auto cuda_status = cudaMemsetAsync(
      status, static_cast<int>(LocalPointStatus::kUnwritten), candidates,
      cuda_stream);
  if (cuda_status != cudaSuccess) {
    throw std::runtime_error(std::string("local-point status initialization failed: ") +
                             cudaGetErrorString(cuda_status));
  }
  cuda_status = cudaMemsetAsync(batch_error_bits, 0, sizeof(std::uint32_t),
                                cuda_stream);
  if (cuda_status != cudaSuccess) {
    throw std::runtime_error(std::string("local-point error initialization failed: ") +
                             cudaGetErrorString(cuda_status));
  }

  LaunchEmptyMask(black, white, empty_workspace, states, words,
                  topology.valid[topology.words - 1], stream);

  constexpr std::size_t warps_per_block = kLocalPointThreadsPerBlock / 32U;
  const std::size_t required_blocks =
      1U + (candidates - 1U) / warps_per_block;
  const auto blocks = static_cast<unsigned int>(
      std::min(required_blocks, kLocalPointMaximumBlocks));
  LocalPointTransitionKernel<<<blocks, kLocalPointThreadsPerBlock, 0,
                               cuda_stream>>>(
      black, white, to_play, empty_workspace, status, captured, self_captured,
      child_black, child_white, batch_error_bits, states, candidates, topology);
  cuda_status = cudaGetLastError();
  if (cuda_status != cudaSuccess) {
    throw std::runtime_error(std::string("local-point CUDA launch failed: ") +
                             cudaGetErrorString(cuda_status));
  }
}

} // namespace ugts_go19::cuda
