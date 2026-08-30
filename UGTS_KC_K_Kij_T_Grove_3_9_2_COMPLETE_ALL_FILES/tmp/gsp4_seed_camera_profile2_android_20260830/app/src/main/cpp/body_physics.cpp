#include "body_physics.hpp"
#include <algorithm>
#include <cmath>
#include <numeric>

namespace kc {
namespace {

constexpr float Epsilon = 1.0e-12f;

bool liveDynamic(const NodeData& node) noexcept {
    return node.alive && node.active && node.dynamic;
}

} // namespace

float bodyBoundingRadius(const NodeData& node) noexcept {
    if (node.collider.type == 1) {
        const float scale = std::max({
            std::abs(node.scale.x),
            std::abs(node.scale.y),
            std::abs(node.scale.z),
        });
        return node.collider.radius * scale;
    }
    if (node.collider.type == 2) {
        return length({
            node.collider.halfExtents.x * node.scale.x,
            node.collider.halfExtents.y * node.scale.y,
            node.collider.halfExtents.z * node.scale.z,
        });
    }
    return 0.0f;
}

float bodyVerticalExtent(const NodeData& node) noexcept {
    if (node.collider.type == 1) {
        return node.collider.radius * std::abs(node.scale.y);
    }
    if (node.collider.type == 2) {
        return node.collider.halfExtents.y * std::abs(node.scale.y);
    }
    return 0.0f;
}

void integrateDynamicBodies(
    std::vector<NodeData>& nodes,
    const Vec3& gravity,
    float dt,
    std::size_t excludedNode
) {
    for (std::size_t index = 0; index < nodes.size(); ++index) {
        auto& node = nodes[index];
        if (index == excludedNode || !liveDynamic(node)) continue;
        node.velocity = node.velocity + gravity * dt;
        node.translation = node.translation + node.velocity * dt;
    }
}

void constrainDynamicBodies(
    std::vector<NodeData>& nodes,
    float floorY,
    const Vec3& boundsMin,
    const Vec3& boundsMax,
    std::size_t excludedNode
) {
    for (std::size_t index = 0; index < nodes.size(); ++index) {
        auto& node = nodes[index];
        if (index == excludedNode || !liveDynamic(node)) continue;

        const float extentY = bodyVerticalExtent(node);
        if (node.translation.y - extentY < floorY) {
            node.translation.y = floorY + extentY;
            if (node.velocity.y < 0.0f) {
                const float bounce = -node.velocity.y * node.restitution;
                node.velocity.y = bounce < 0.08f ? 0.0f : bounce;
            }
        }

        const float radius = bodyBoundingRadius(node);
        const float minimumX = boundsMin.x + radius;
        const float maximumX = boundsMax.x - radius;
        if (node.translation.x < minimumX) {
            node.translation.x = minimumX;
            node.velocity.x = std::abs(node.velocity.x) * node.restitution;
        } else if (node.translation.x > maximumX) {
            node.translation.x = maximumX;
            node.velocity.x = -std::abs(node.velocity.x) * node.restitution;
        }

        const float minimumZ = boundsMin.z + radius;
        const float maximumZ = boundsMax.z - radius;
        if (node.translation.z < minimumZ) {
            node.translation.z = minimumZ;
            node.velocity.z = std::abs(node.velocity.z) * node.restitution;
        } else if (node.translation.z > maximumZ) {
            node.translation.z = maximumZ;
            node.velocity.z = -std::abs(node.velocity.z) * node.restitution;
        }
    }
}

std::vector<BodyContact> resolveDynamicBodyPairs(
    std::vector<NodeData>& nodes
) {
    std::vector<std::uint32_t> order(nodes.size());
    std::iota(order.begin(), order.end(), 0u);
    std::sort(
        order.begin(), order.end(),
        [&nodes](std::uint32_t first, std::uint32_t second) {
            if (nodes[first].id != nodes[second].id) {
                return nodes[first].id < nodes[second].id;
            }
            return first < second;
        }
    );

    std::vector<BodyContact> contacts;
    for (std::size_t firstPosition = 0; firstPosition < order.size(); ++firstPosition) {
        const auto firstIndex = order[firstPosition];
        auto& first = nodes[firstIndex];
        if (!first.alive || !first.active || first.collider.sensor) continue;
        const float firstRadius = bodyBoundingRadius(first);
        if (firstRadius <= 0.0f) continue;

        for (std::size_t secondPosition = firstPosition + 1;
             secondPosition < order.size(); ++secondPosition) {
            const auto secondIndex = order[secondPosition];
            auto& second = nodes[secondIndex];
            if (!second.alive || !second.active || second.collider.sensor ||
                (!first.dynamic && !second.dynamic)) {
                continue;
            }
            const float secondRadius = bodyBoundingRadius(second);
            if (secondRadius <= 0.0f) continue;

            const Vec3 delta = second.translation - first.translation;
            const float distance = length(delta);
            const float target = firstRadius + secondRadius;
            if (distance >= target) continue;

            const Vec3 normal = distance <= Epsilon
                ? Vec3{1.0f, 0.0f, 0.0f}
                : delta / distance;
            const float penetration = target - distance;
            const float inverseFirst = first.dynamic ? 1.0f / first.mass : 0.0f;
            const float inverseSecond = second.dynamic ? 1.0f / second.mass : 0.0f;
            const float inverseTotal = inverseFirst + inverseSecond;
            if (inverseTotal <= Epsilon) continue;

            if (first.dynamic) {
                first.translation = first.translation -
                    normal * (penetration * inverseFirst / inverseTotal);
            }
            if (second.dynamic) {
                second.translation = second.translation +
                    normal * (penetration * inverseSecond / inverseTotal);
            }

            const float relativeVelocity = dot(
                second.velocity - first.velocity,
                normal
            );
            if (relativeVelocity < 0.0f) {
                const float impulse =
                    -(1.0f + std::min(first.restitution, second.restitution)) *
                    relativeVelocity / inverseTotal;
                if (first.dynamic) {
                    first.velocity = first.velocity -
                        normal * (impulse * inverseFirst);
                }
                if (second.dynamic) {
                    second.velocity = second.velocity +
                        normal * (impulse * inverseSecond);
                }
            }
            contacts.push_back({firstIndex, secondIndex, penetration});
        }
    }
    return contacts;
}

} // namespace kc
