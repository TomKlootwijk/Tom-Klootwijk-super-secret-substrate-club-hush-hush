#pragma once
#include <array>
#include <cstdint>
#include <vector>

namespace kc {

// Optional, independently versioned chrono-video sampling cache. This is not
// UGLUT2 and does not carry camera/depth/geometry authority.
struct ChronoVideoLut {
    bool present=false;
    std::uint32_t sourceWidth=0,sourceHeight=0;
    std::uint32_t thetaBins=0,rhoBins=0;
    double centerX=0.0,centerY=0.0,r0=1.0,coreRadius=0.5;
    double rhoMin=0.0,rhoMax=0.0;
    std::array<std::uint8_t,32> payloadSha256{};
    // RGBA16UI: x0, y0, fx_q8|(fy_q8<<8), valid.
    std::vector<std::uint16_t> texels;

    void load(const std::vector<std::uint8_t>& bytes);
};

} // namespace kc

