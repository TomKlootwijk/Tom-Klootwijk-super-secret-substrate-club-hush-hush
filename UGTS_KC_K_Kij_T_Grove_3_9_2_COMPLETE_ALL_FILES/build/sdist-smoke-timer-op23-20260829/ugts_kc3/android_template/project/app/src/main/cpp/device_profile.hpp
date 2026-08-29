#pragma once
#include "scene_pack.hpp"
#include <cstdint>
#include <string>

namespace kc {

struct DeviceInfo {
    std::string model;
    std::string manufacturer;
    std::string gpu;
    std::uint32_t ramMb = 4096;
    std::uint32_t cpuCores = 4;
    std::uint8_t glesMajor = 3, glesMinor = 0;
    float refreshHz = 60.0f;
};

struct ProfileSelection {
    std::string profileId;
    std::string qualityId;
    std::uint16_t targetFps = 60;
    float renderScale = 0.82f;
    std::uint32_t maxVisibleNodes = 480;
    std::string reason;
};

ProfileSelection selectProfile(const ScenePack& scene, const DeviceInfo& device, const std::string& requested);

} // namespace kc
