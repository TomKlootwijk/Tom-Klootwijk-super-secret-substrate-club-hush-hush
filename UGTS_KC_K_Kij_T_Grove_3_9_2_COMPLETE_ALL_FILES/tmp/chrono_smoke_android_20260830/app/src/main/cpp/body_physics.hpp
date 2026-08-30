#pragma once
#include "scene_pack.hpp"
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

namespace kc {

inline constexpr std::size_t NoBodyExclusion =
    std::numeric_limits<std::size_t>::max();

struct BodyContact {
    std::uint32_t firstNode = 0;
    std::uint32_t secondNode = 0;
    float penetration = 0.0f;
};

float bodyBoundingRadius(const NodeData& node) noexcept;
float bodyVerticalExtent(const NodeData& node) noexcept;

// Angular velocity remains an engine-level transform concern because it also
// applies to static decorative nodes. These helpers own only dynamic-body
// translation and contact response.
void integrateDynamicBodies(
    std::vector<NodeData>& nodes,
    const Vec3& gravity,
    float dt,
    std::size_t excludedNode = NoBodyExclusion
);

void constrainDynamicBodies(
    std::vector<NodeData>& nodes,
    float floorY,
    const Vec3& boundsMin,
    const Vec3& boundsMax,
    std::size_t excludedNode = NoBodyExclusion
);

std::vector<BodyContact> resolveDynamicBodyPairs(
    std::vector<NodeData>& nodes
);

} // namespace kc
