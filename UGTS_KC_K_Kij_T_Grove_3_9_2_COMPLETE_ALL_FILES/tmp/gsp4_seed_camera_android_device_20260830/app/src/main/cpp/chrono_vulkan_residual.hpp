#pragma once

#include "chrono_capture_sha256.hpp"

#include <cstdint>
#include <memory>
#include <span>
#include <string>
#include <vector>

namespace kc {

struct ChronoVulkanResidualReceipt {
    std::uint64_t dispatchIndex=0;
    std::uint32_t workgroupSize=256;
    std::uint32_t workgroupCount=0;
    std::uint64_t gpuNanoseconds=0;
    std::uint64_t submitWallNanoseconds=0;
    ChronoSha256Digest residualSha256{};
    bool fullCpuParity=false;
};

// Integer-only Vulkan compute implementation of the canonical owner-only
// UGCODE24-420 residual stream. The lane-source map is regenerated from the
// literal UGLUT2 and seed; it is never serialized per frame.
class ChronoVulkanResidual final {
public:
    ChronoVulkanResidual();
    ~ChronoVulkanResidual();
    ChronoVulkanResidual(const ChronoVulkanResidual&)=delete;
    ChronoVulkanResidual& operator=(const ChronoVulkanResidual&)=delete;

    bool configure(
        std::uint32_t width,std::uint32_t height,
        std::uint64_t rootSeed,std::uint64_t recipeSeed,
        const std::vector<std::uint8_t>& literalUglut2
    );
    bool compute(
        std::span<const std::uint8_t> y,
        std::span<const std::uint8_t> u,
        std::span<const std::uint8_t> v,
        bool checkpoint,
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
