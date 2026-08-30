#pragma once

#include "scene_pack.hpp"

#include <cstddef>
#include <cstdint>
#include <string_view>
#include <vector>

namespace kc {

inline constexpr std::size_t MaxScatterPackBytes = 64u * 1024u;
inline constexpr std::uint32_t MaxScatterGroups = 64u;
inline constexpr std::uint16_t MaxScatterInstancesPerGroup = 256u;
inline constexpr std::uint32_t MaxScatterTotalInstances = 1024u;

// Public deterministic primitives make the UGTS 4.1 random-access contract
// independently testable by native hosts and future renderer integrations.
std::uint64_t scatterSplitMix64(std::uint64_t value) noexcept;
std::uint64_t scatterHash64(
    std::string_view utf8Text,
    std::uint64_t seed = 0xCBF29CE484222325ull
) noexcept;
std::uint64_t scatterCombineSeed(std::uint64_t seed, std::uint64_t value) noexcept;
std::uint64_t scatterStableId(
    std::uint64_t sessionSeed,
    std::uint64_t namespaceId,
    std::uint64_t address
) noexcept;
float scatterSeedUnitFloat(std::uint64_t value) noexcept;

struct ScatterInstanceTransform {
    // Index zero is the immutable authored prototype. Generated copies are
    // therefore always addressed from one through instanceCount - 1.
    std::uint16_t index = 0;
    std::uint64_t lineage = 0;
    Vec3 translation{};
    Quat rotation{};
    Vec3 scale{1.0f, 1.0f, 1.0f};
    float yawRadians = 0.0f;
    Mat4 model{};
};

struct ScatterPopulationGroup {
    std::uint32_t prototypeNodeIndex = 0;
    std::uint16_t instanceCount = 0;
    bool randomYaw = false;
    std::uint64_t seed = 0;
    Vec3 size{};
    float scaleMin = 1.0f;
    float scaleMax = 1.0f;
    std::vector<ScatterInstanceTransform> instances;
};

// Strict parser plus deterministic transform generator for the optional KCSP
// sidecar. Loading never mutates NodeData; renderer code consumes groups()
// together with each group's prototypeNodeIndex.
class ScatterPopulations {
public:
    void clear();
    void load(
        const std::vector<std::uint8_t>& bytes,
        const std::vector<NodeData>& nodes
    );

    bool empty() const noexcept { return groups_.empty(); }
    std::size_t groupCount() const noexcept { return groups_.size(); }
    std::size_t totalInstances() const noexcept { return totalInstances_; }
    std::size_t generatedCopyCount() const noexcept { return generatedCopyCount_; }
    const std::vector<ScatterPopulationGroup>& groups() const noexcept { return groups_; }

private:
    std::vector<ScatterPopulationGroup> groups_;
    std::size_t totalInstances_ = 0;
    std::size_t generatedCopyCount_ = 0;
};

} // namespace kc
