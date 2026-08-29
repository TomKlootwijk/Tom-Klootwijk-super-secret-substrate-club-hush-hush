#pragma once

#include <cstddef>
#include <cstdint>

namespace ugts_go19::cuda {

// Produce exact empty-point bitmasks from black/white bitplanes. This is only
// the occupancy stage. Capture, suicide, and superko guards remain mandatory
// before any candidate becomes a proof-authoritative move.
void LaunchEmptyMask(const std::uint64_t* black, const std::uint64_t* white,
                     std::uint64_t* empty, std::size_t states,
                     std::size_t words_per_state, std::uint64_t tail_mask,
                     void* stream);

}  // namespace ugts_go19::cuda
