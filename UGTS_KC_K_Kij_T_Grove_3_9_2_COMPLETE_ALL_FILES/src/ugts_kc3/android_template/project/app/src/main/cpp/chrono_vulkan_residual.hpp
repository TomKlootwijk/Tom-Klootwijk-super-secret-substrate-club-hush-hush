#pragma once

#include "chrono_capture_sha256.hpp"

#include <array>
#include <cstdint>
#include <memory>
#include <span>
#include <string>
#include <vector>

namespace kc {

struct ChronoVulkanResidualReceipt {
    std::uint64_t dispatchIndex=0;
    std::uint32_t logicalProfile=1;
    std::uint32_t workgroupSize=256;
    std::uint32_t workgroupCount=0;
    std::uint32_t lumaLaneCount=0;
    std::uint32_t operatorReceiptWordsPerLane=0;
    std::uint64_t gpuNanoseconds=0;
    std::uint64_t submitWallNanoseconds=0;
    ChronoSha256Digest residualSha256{};
    ChronoSha256Digest gpuReceiptBytesSha256{};
    ChronoSha256Digest operatorStateSha256{};
    std::array<std::uint32_t,4> selectorCounts{};
    bool fullCpuParity=false;
    bool fullOperatorStateParity=false;
};

// Integer-only Vulkan compute implementation of the canonical owner-only
// profile-1 or UGCAMNODE-FX1 profile-2 stream. UGLUT2 addresses, rho/theta
// state and GSP4 lineage are regenerated from the literal LUT and seeds; no
// per-frame map is serialized. Profile 2 also emits the canonical 20-word
// receipt per luma lane and verifies its block/frame hashes against the CPU
// oracle before returning residual bytes to the writer.
class ChronoVulkanResidual final {
public:
    ChronoVulkanResidual();
    ~ChronoVulkanResidual();
    ChronoVulkanResidual(const ChronoVulkanResidual&)=delete;
    ChronoVulkanResidual& operator=(const ChronoVulkanResidual&)=delete;

    bool configure(
        std::uint32_t width,std::uint32_t height,
        std::uint64_t rootSeed,std::uint64_t recipeSeed,
        const std::vector<std::uint8_t>& literalUglut2,
        std::uint32_t logicalProfile=1u,
        std::uint32_t blockLumaAddresses=65536u
    );
    bool compute(
        std::span<const std::uint8_t> y,
        std::span<const std::uint8_t> u,
        std::span<const std::uint8_t> v,
        bool checkpoint,
        std::uint32_t frameOrdinal,
        std::vector<std::uint8_t>& canonicalResidual,
        ChronoVulkanResidualReceipt& receipt
    );
    bool available() const;
    std::uint64_t dispatchCount() const;
    const std::string& deviceName() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace kc
