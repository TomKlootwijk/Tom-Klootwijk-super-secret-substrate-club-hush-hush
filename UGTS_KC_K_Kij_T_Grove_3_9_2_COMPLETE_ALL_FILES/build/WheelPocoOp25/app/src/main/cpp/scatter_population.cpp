#include "scatter_population.hpp"

#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string_view>
#include <utility>

namespace kc {
namespace {

constexpr std::uint64_t Golden64 = 0x9E3779B97F4A7C15ull;
constexpr std::uint64_t Fnv64Prime = 0x100000001B3ull;
constexpr std::uint32_t Endian = 0x01020304u;
constexpr std::uint32_t Version = 1u;
constexpr std::size_t HeaderBytes = 24u;
constexpr std::size_t GroupBytes = 36u;
constexpr std::uint16_t RandomYawFlag = 1u << 0;
constexpr double Tau = 6.283185307179586476925286766559;
constexpr double QuaternionEpsilon = 1.0e-12;
constexpr std::uint32_t UnsafeGameplayTags =
    TagPlayer | TagCollectible | TagGoal | TagHazard;

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

class Reader {
public:
    explicit Reader(const std::vector<std::uint8_t>& bytes) : bytes_(bytes) {}

    std::size_t remaining() const noexcept { return bytes_.size() - offset_; }

    const std::uint8_t* raw(std::size_t count) {
        if (count > remaining()) throw std::runtime_error("truncated KCSP population asset");
        const auto* result = bytes_.data() + offset_;
        offset_ += count;
        return result;
    }

    std::uint16_t u16() {
        const auto* bytes = raw(2);
        return static_cast<std::uint16_t>(
            static_cast<std::uint16_t>(bytes[0]) |
            (static_cast<std::uint16_t>(bytes[1]) << 8)
        );
    }

    std::uint32_t u32() {
        const auto* bytes = raw(4);
        return static_cast<std::uint32_t>(bytes[0]) |
            (static_cast<std::uint32_t>(bytes[1]) << 8) |
            (static_cast<std::uint32_t>(bytes[2]) << 16) |
            (static_cast<std::uint32_t>(bytes[3]) << 24);
    }

    std::uint64_t u64() {
        const auto low = static_cast<std::uint64_t>(u32());
        return low | (static_cast<std::uint64_t>(u32()) << 32);
    }

    float f32() {
        const auto bits = u32();
        float result = 0.0f;
        std::memcpy(&result, &bits, sizeof(result));
        return result;
    }

private:
    const std::vector<std::uint8_t>& bytes_;
    std::size_t offset_ = 0;
};

bool finite(Vec3 value) noexcept {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

bool finite(Quat value) noexcept {
    return std::isfinite(value.w) && std::isfinite(value.x) &&
        std::isfinite(value.y) && std::isfinite(value.z);
}

bool zero(Vec3 value) noexcept {
    return value.x == 0.0f && value.y == 0.0f && value.z == 0.0f;
}

bool validUtf8(std::string_view text) noexcept {
    std::size_t index = 0;
    while (index < text.size()) {
        const auto first = static_cast<unsigned char>(text[index++]);
        if (first < 0x80u) continue;

        unsigned continuationCount = 0;
        std::uint32_t value = 0;
        if ((first & 0xE0u) == 0xC0u) {
            continuationCount = 1;
            value = first & 0x1Fu;
            if (value < 2u) return false;
        } else if ((first & 0xF0u) == 0xE0u) {
            continuationCount = 2;
            value = first & 0x0Fu;
        } else if ((first & 0xF8u) == 0xF0u) {
            continuationCount = 3;
            value = first & 0x07u;
        } else {
            return false;
        }

        if (index + continuationCount > text.size()) return false;
        for (unsigned item = 0; item < continuationCount; ++item) {
            const auto next = static_cast<unsigned char>(text[index++]);
            if ((next & 0xC0u) != 0x80u) return false;
            value = (value << 6) | (next & 0x3Fu);
        }
        if ((continuationCount == 2 && value < 0x800u) ||
            (continuationCount == 3 && value < 0x10000u) ||
            (value >= 0xD800u && value <= 0xDFFFu) || value > 0x10FFFFu) {
            return false;
        }
    }
    return true;
}

void validatePrototype(const NodeData& prototype) {
    require(!prototype.id.empty(), "KCSP prototype id is empty");
    require(validUtf8(prototype.id), "KCSP prototype id is not valid UTF-8");
    require(prototype.active && prototype.alive, "KCSP prototype is not render-active");
    require(!prototype.dynamic, "KCSP prototype must be static");
    require(
        prototype.collider.type == 0u && !prototype.collider.sensor,
        "KCSP prototype cannot have a collider or trigger area"
    );
    require(
        finite(prototype.velocity) && finite(prototype.angularVelocity) &&
            zero(prototype.velocity) && zero(prototype.angularVelocity),
        "KCSP prototype must have zero velocity"
    );
    require(
        (prototype.tagMask & UnsafeGameplayTags) == 0u,
        "KCSP prototype has a gameplay tag"
    );
    require(
        finite(prototype.translation) && finite(prototype.rotation) && finite(prototype.scale),
        "KCSP prototype transform is not finite"
    );

    const double w = static_cast<double>(prototype.rotation.w);
    const double x = static_cast<double>(prototype.rotation.x);
    const double y = static_cast<double>(prototype.rotation.y);
    const double z = static_cast<double>(prototype.rotation.z);
    double squaredNorm = w * w;
    squaredNorm += x * x;
    squaredNorm += y * y;
    squaredNorm += z * z;
    require(
        std::sqrt(squaredNorm) > QuaternionEpsilon,
        "KCSP prototype rotation is a zero quaternion"
    );
}

struct DoubleQuat {
    double w = 1.0;
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

DoubleQuat normalizeExact(DoubleQuat value) {
    double squaredNorm = value.w * value.w;
    squaredNorm += value.x * value.x;
    squaredNorm += value.y * value.y;
    squaredNorm += value.z * value.z;
    const double norm = std::sqrt(squaredNorm);
    require(
        std::isfinite(norm) && norm > QuaternionEpsilon,
        "KCSP generated rotation is invalid"
    );
    return {value.w / norm, value.x / norm, value.y / norm, value.z / norm};
}

DoubleQuat multiplyExact(DoubleQuat a, DoubleQuat b) noexcept {
    return {
        a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
        a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
        a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
        a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
    };
}

float lane(std::uint64_t lineage, std::uint64_t laneIndex) noexcept {
    return scatterSeedUnitFloat(scatterCombineSeed(lineage, laneIndex));
}

float centeredOffset(std::uint64_t lineage, std::uint64_t laneIndex, float size) {
    const double centered = static_cast<double>(lane(lineage, laneIndex)) - 0.5;
    const float result = static_cast<float>(centered * static_cast<double>(size));
    require(std::isfinite(result), "KCSP generated offset is not finite");
    return result;
}

float translated(float base, float offset) {
    const float result = static_cast<float>(
        static_cast<double>(base) + static_cast<double>(offset)
    );
    require(std::isfinite(result), "KCSP generated translation is not finite");
    return result;
}

float scaled(float base, float scalar) {
    const float result = static_cast<float>(
        static_cast<double>(base) * static_cast<double>(scalar)
    );
    require(std::isfinite(result), "KCSP generated scale is not finite");
    return result;
}

Quat generatedRotation(const NodeData& prototype, float yaw) {
    DoubleQuat rotation = normalizeExact({
        static_cast<double>(prototype.rotation.w),
        static_cast<double>(prototype.rotation.x),
        static_cast<double>(prototype.rotation.y),
        static_cast<double>(prototype.rotation.z),
    });
    if (yaw != 0.0f) {
        const double half = static_cast<double>(yaw) * 0.5;
        const DoubleQuat yawRotation{std::cos(half), 0.0, std::sin(half), 0.0};
        rotation = normalizeExact(multiplyExact(yawRotation, rotation));
    }
    const Quat result{
        static_cast<float>(rotation.w),
        static_cast<float>(rotation.x),
        static_cast<float>(rotation.y),
        static_cast<float>(rotation.z),
    };
    require(finite(result), "KCSP generated rotation is not finite");
    return result;
}

void validateModel(const Mat4& model) {
    for (float value : model.v) {
        require(std::isfinite(value), "KCSP generated model matrix is not finite");
    }
}

ScatterInstanceTransform generateInstance(
    const NodeData& prototype,
    const ScatterPopulationGroup& group,
    std::uint16_t index
) {
    ScatterInstanceTransform result;
    result.index = index;
    const auto namespaceId = scatterHash64(prototype.id);
    result.lineage = scatterStableId(group.seed, namespaceId, index);

    const Vec3 offset{
        centeredOffset(result.lineage, 1u, group.size.x),
        centeredOffset(result.lineage, 2u, group.size.y),
        centeredOffset(result.lineage, 3u, group.size.z),
    };
    result.translation = {
        translated(prototype.translation.x, offset.x),
        translated(prototype.translation.y, offset.y),
        translated(prototype.translation.z, offset.z),
    };

    const double scalarValue = static_cast<double>(group.scaleMin) +
        static_cast<double>(lane(result.lineage, 4u)) *
            (static_cast<double>(group.scaleMax) - static_cast<double>(group.scaleMin));
    const float scalar = static_cast<float>(scalarValue);
    require(std::isfinite(scalar), "KCSP generated scale scalar is not finite");
    result.scale = {
        scaled(prototype.scale.x, scalar),
        scaled(prototype.scale.y, scalar),
        scaled(prototype.scale.z, scalar),
    };

    if (group.randomYaw) {
        result.yawRadians = static_cast<float>(
            static_cast<double>(lane(result.lineage, 5u)) * Tau
        );
        require(std::isfinite(result.yawRadians), "KCSP generated yaw is not finite");
    }
    result.rotation = generatedRotation(prototype, result.yawRadians);
    result.model = trs(result.translation, result.rotation, result.scale);
    validateModel(result.model);
    return result;
}

} // namespace

std::uint64_t scatterSplitMix64(std::uint64_t value) noexcept {
    value += Golden64;
    value = (value ^ (value >> 30)) * 0xBF58476D1CE4E5B9ull;
    value = (value ^ (value >> 27)) * 0x94D049BB133111EBull;
    return value ^ (value >> 31);
}

std::uint64_t scatterHash64(std::string_view utf8Text, std::uint64_t seed) noexcept {
    auto value = seed;
    for (char item : utf8Text) {
        value = (value ^ static_cast<unsigned char>(item)) * Fnv64Prime;
    }
    return scatterSplitMix64(value ^ static_cast<std::uint64_t>(utf8Text.size()));
}

std::uint64_t scatterCombineSeed(std::uint64_t seed, std::uint64_t value) noexcept {
    const auto mixed = scatterSplitMix64(value) + Golden64 + (seed << 6) + (seed >> 2);
    return scatterSplitMix64(seed ^ mixed);
}

std::uint64_t scatterStableId(
    std::uint64_t sessionSeed,
    std::uint64_t namespaceId,
    std::uint64_t address
) noexcept {
    return scatterCombineSeed(scatterCombineSeed(sessionSeed, namespaceId), address);
}

float scatterSeedUnitFloat(std::uint64_t value) noexcept {
    const auto upper = scatterSplitMix64(value) >> 40;
    return static_cast<float>(static_cast<double>(upper) / 16777216.0);
}

void ScatterPopulations::clear() {
    groups_.clear();
    totalInstances_ = 0;
    generatedCopyCount_ = 0;
}

void ScatterPopulations::load(
    const std::vector<std::uint8_t>& bytes,
    const std::vector<NodeData>& nodes
) {
    clear();
    if (bytes.empty()) return;

    try {
        require(bytes.size() <= MaxScatterPackBytes, "KCSP asset exceeds its byte limit");
        require(bytes.size() >= HeaderBytes, "truncated KCSP population asset");
        Reader reader(bytes);
        require(std::memcmp(reader.raw(8), "KCSP392\0", 8) == 0, "KCSP magic mismatch");
        require(reader.u32() == Endian, "KCSP endian marker mismatch");
        require(reader.u32() == Version, "unsupported KCSP version");
        const auto groupCount = reader.u32();
        const auto packedTotalInstances = reader.u32();
        require(
            groupCount >= 1u && groupCount <= MaxScatterGroups,
            "KCSP population group count is invalid"
        );
        require(
            packedTotalInstances <= MaxScatterTotalInstances,
            "KCSP population total exceeds the runtime safety limit"
        );

        const auto expectedBytes = HeaderBytes + static_cast<std::size_t>(groupCount) * GroupBytes;
        require(bytes.size() >= expectedBytes, "truncated KCSP population group record");
        require(bytes.size() == expectedBytes, "KCSP population asset has trailing bytes");

        std::vector<ScatterPopulationGroup> parsed;
        parsed.reserve(groupCount);
        std::uint32_t countedInstances = 0;
        std::uint32_t previousPrototype = 0;
        for (std::uint32_t groupIndex = 0; groupIndex < groupCount; ++groupIndex) {
            ScatterPopulationGroup group;
            group.prototypeNodeIndex = reader.u32();
            group.instanceCount = reader.u16();
            const auto flags = reader.u16();
            group.seed = reader.u64();
            group.size = {reader.f32(), reader.f32(), reader.f32()};
            group.scaleMin = reader.f32();
            group.scaleMax = reader.f32();

            if (groupIndex > 0u) {
                require(
                    group.prototypeNodeIndex > previousPrototype,
                    "KCSP population groups are not sparse-canonical"
                );
            }
            require(
                group.prototypeNodeIndex < nodes.size(),
                "KCSP population group has an invalid prototype node"
            );
            require(
                group.instanceCount >= 2u &&
                    group.instanceCount <= MaxScatterInstancesPerGroup,
                "KCSP population instance count is invalid"
            );
            require(
                (flags & ~RandomYawFlag) == 0u,
                "KCSP population flags contain unsupported bits"
            );
            require(
                group.seed <= std::numeric_limits<std::uint32_t>::max(),
                "KCSP population world number is outside the supported range"
            );
            require(
                finite(group.size) && group.size.x >= 0.0f &&
                    group.size.y >= 0.0f && group.size.z >= 0.0f,
                "KCSP population area size is invalid"
            );
            require(
                group.size.x > 0.0f || group.size.z > 0.0f,
                "KCSP population area width or depth must be positive"
            );
            require(
                std::isfinite(group.scaleMin) && std::isfinite(group.scaleMax) &&
                    group.scaleMin >= 0.05f && group.scaleMin <= 8.0f &&
                    group.scaleMax >= 0.05f && group.scaleMax <= 8.0f &&
                    group.scaleMin <= group.scaleMax,
                "KCSP population size variation is invalid"
            );
            validatePrototype(nodes[group.prototypeNodeIndex]);

            group.randomYaw = (flags & RandomYawFlag) != 0u;
            previousPrototype = group.prototypeNodeIndex;
            countedInstances += group.instanceCount;
            parsed.push_back(std::move(group));
        }
        require(reader.remaining() == 0u, "KCSP population asset has trailing bytes");
        require(
            countedInstances == packedTotalInstances,
            "KCSP population total does not match its group records"
        );
        require(
            countedInstances <= MaxScatterTotalInstances,
            "KCSP population total exceeds the runtime safety limit"
        );

        for (auto& group : parsed) {
            const auto& prototype = nodes[group.prototypeNodeIndex];
            group.instances.reserve(static_cast<std::size_t>(group.instanceCount) - 1u);
            for (std::uint16_t index = 1u; index < group.instanceCount; ++index) {
                group.instances.push_back(generateInstance(prototype, group, index));
            }
        }

        groups_ = std::move(parsed);
        totalInstances_ = countedInstances;
        generatedCopyCount_ = countedInstances - groupCount;
    } catch (...) {
        clear();
        throw;
    }
}

} // namespace kc
