#pragma once

#include "chrono_capture_sha256.hpp"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace kc {

enum class ChronoSceneMode : std::uint8_t {
    Recorder=1,
    Player=2,
};

enum class ChronoSceneStorage : std::uint8_t {
    AppPrivateGsp4Seed=1,
    PackagedGsp4Seed=2,
};

struct ChronoSceneBinding {
    std::uint32_t nodeIndex=0;
    ChronoSceneMode mode=ChronoSceneMode::Recorder;
    ChronoSceneStorage storage=ChronoSceneStorage::AppPrivateGsp4Seed;
    bool autostart=false;
    std::uint32_t width=0;
    std::uint32_t height=0;
    std::uint16_t fps=0;
    std::uint16_t queueSlots=0;
    std::uint16_t uglutResolution=0;
    std::uint64_t rootSeed=0;
    std::uint64_t recipeSeed=0;
    double r0=0.0;
    double rhoMin=0.0;
    double rhoMax=0.0;
    double coreRadius=0.0;
    ChronoSha256Digest uglut2Sha256{};
    std::uint64_t sourceAssetBytes=0;
    ChronoSha256Digest sourceAssetSha256{};
    std::string cameraId;
    std::string outputBasename;
    std::string packagedAssetPath;
};

class ChronoSceneBindings final {
public:
    // An absent asset is a valid scene with no chrono ownership.
    void load(const std::vector<std::uint8_t>& bytes,std::size_t sceneNodeCount);
    const std::vector<ChronoSceneBinding>& records() const { return records_; }
    const ChronoSceneBinding* recorder() const;

private:
    std::vector<ChronoSceneBinding> records_;
};

} // namespace kc
