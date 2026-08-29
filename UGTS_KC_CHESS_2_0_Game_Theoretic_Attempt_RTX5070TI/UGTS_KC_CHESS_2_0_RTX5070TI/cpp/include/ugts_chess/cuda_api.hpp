#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

#include "ugts_chess/packed_chess.hpp"

namespace ugts::chess {

struct DeviceInfo {
    bool cuda_compiled{};
    bool device_available{};
    int device_index{-1};
    int compute_major{};
    int compute_minor{};
    std::uint64_t total_memory{};
    std::uint64_t free_memory{};
    int multiprocessors{};
    int warp_size{};
    int max_threads_per_block{};
    std::string name;
    std::string error;
};

DeviceInfo query_device(int requested_device = 0);

// Returns true on successful expansion.  The caller owns all buffers.
// output_moves is a fixed [count][kMaxMoves] matrix and output_counts has
// one count per input.  CUDA remains proposal-only; an independent host
// legal kernel must verify the result before proof use.
bool expand_batch_cuda(
    const PackedPosition* positions,
    std::size_t count,
    std::uint16_t* output_moves,
    std::uint16_t* output_counts,
    int device_index,
    std::string& error);

}  // namespace ugts::chess
