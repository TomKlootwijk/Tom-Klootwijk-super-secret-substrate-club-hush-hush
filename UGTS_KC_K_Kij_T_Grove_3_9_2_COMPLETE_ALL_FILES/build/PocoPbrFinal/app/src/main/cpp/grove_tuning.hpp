#pragma once
#include <cstdint>
#include <string>

namespace kc {
struct DeviceInfo;
struct GroveTuning {
    std::string profileId="grove_balanced_60";
    float juiceIntensity=0.75f;
    float bloom=0.45f;
    std::uint32_t particleBudget=128;
    bool post=true;
    bool maliOptimized=false;
    float targetFrameMs=16.67f;
};
GroveTuning selectGroveTuning(const DeviceInfo& info);
} // namespace kc
