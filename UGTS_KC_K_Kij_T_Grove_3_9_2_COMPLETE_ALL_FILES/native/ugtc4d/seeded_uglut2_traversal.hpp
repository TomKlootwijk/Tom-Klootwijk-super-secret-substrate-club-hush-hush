#pragma once

#include "ugtc4d_decoder.hpp"

#include <cstdint>
#include <vector>

namespace ugts::chrono {

struct SeededUglut2Traversal {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::uint32_t resolution = 0;
    std::uint64_t rootSeed = 0;
    std::uint64_t recipeSeed = 0;
    Sha256Digest uglut2Sha256{};
    Sha256Digest traversalSha256{};
    std::vector<std::uint32_t> polarOrdinalToCartesian;
    // Profile-2 operator inputs. These are regenerated execution state keyed
    // by Cartesian luma address and are never serialized as a permutation.
    std::vector<std::uint32_t> rho20ByCartesian;
    std::vector<std::uint32_t> theta18ByCartesian;
};

// Regenerate the exact UGTRV1 pixel order from literal UGLUT2 lanes and seed
// state. No per-pixel permutation is accepted as input or serialized output.
SeededUglut2Traversal regenerateSeededUglut2Traversal(
    std::uint32_t width,
    std::uint32_t height,
    std::uint64_t rootSeed,
    std::uint64_t recipeSeed,
    const std::vector<std::uint8_t>& uglut2
);

} // namespace ugts::chrono
