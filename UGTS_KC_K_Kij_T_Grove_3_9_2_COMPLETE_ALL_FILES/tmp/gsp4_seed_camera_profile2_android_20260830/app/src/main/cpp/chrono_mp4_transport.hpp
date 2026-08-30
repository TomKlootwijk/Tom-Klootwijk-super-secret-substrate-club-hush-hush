#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace kc {

struct ChronoMp4TransportDerivation {
    std::vector<std::uint8_t> bytes;
    std::array<std::uint8_t,4> originalCompatibleBrand{};
    std::array<std::uint8_t,4> replacementCompatibleBrand{};
    std::size_t ftypOffset=0u;
    std::size_t ftypBytes=0u;
    std::size_t compatibleBrandOffset=0u;
    std::size_t changedByteOffset=0u;
    std::size_t changedByteCount=0u;
};

// Derive an Android-extractor transport from the immutable, already SHA-bound
// source. This is deliberately not a remux: only an exact unsupported iso4
// compatible-brand field may become the truthful AOSP-recognized isom brand.
ChronoMp4TransportDerivation deriveIso4IsomTransport(
    std::span<const std::uint8_t> sourceBytes
);

} // namespace kc
