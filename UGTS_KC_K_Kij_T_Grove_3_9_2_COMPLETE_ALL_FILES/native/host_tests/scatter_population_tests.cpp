#include "scatter_population.hpp"

#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

constexpr std::array<std::uint8_t, 60> Fixture{
    'K', 'C', 'S', 'P', '3', '9', '2', 0,
    0x04, 0x03, 0x02, 0x01,
    0x01, 0x00, 0x00, 0x00,
    0x01, 0x00, 0x00, 0x00,
    0x04, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00,
    0x04, 0x00,
    0x01, 0x00,
    0x07, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x41,
    0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0xC0, 0x40,
    0xCD, 0xCC, 0x4C, 0x3F,
    0x9A, 0x99, 0x99, 0x3F,
};
static_assert(Fixture.size() == 60u);

[[noreturn]] void fail(std::string_view message) {
    throw std::runtime_error(std::string(message));
}

void check(bool condition, std::string_view message) {
    if (!condition) fail(message);
}

std::uint32_t bits(float value) {
    return std::bit_cast<std::uint32_t>(value);
}

bool sameVec(kc::Vec3 left, kc::Vec3 right) {
    return bits(left.x) == bits(right.x) && bits(left.y) == bits(right.y) &&
        bits(left.z) == bits(right.z);
}

bool sameQuat(kc::Quat left, kc::Quat right) {
    return bits(left.w) == bits(right.w) && bits(left.x) == bits(right.x) &&
        bits(left.y) == bits(right.y) && bits(left.z) == bits(right.z);
}

std::vector<std::uint8_t> fixture() {
    return {Fixture.begin(), Fixture.end()};
}

void putU16(std::vector<std::uint8_t>& bytes, std::size_t offset, std::uint16_t value) {
    bytes.at(offset) = static_cast<std::uint8_t>(value);
    bytes.at(offset + 1u) = static_cast<std::uint8_t>(value >> 8);
}

void putU32(std::vector<std::uint8_t>& bytes, std::size_t offset, std::uint32_t value) {
    for (unsigned index = 0; index < 4; ++index) {
        bytes.at(offset + index) = static_cast<std::uint8_t>(value >> (index * 8));
    }
}

void putU64(std::vector<std::uint8_t>& bytes, std::size_t offset, std::uint64_t value) {
    for (unsigned index = 0; index < 8; ++index) {
        bytes.at(offset + index) = static_cast<std::uint8_t>(value >> (index * 8));
    }
}

void putF32(std::vector<std::uint8_t>& bytes, std::size_t offset, float value) {
    putU32(bytes, offset, bits(value));
}

kc::NodeData oak() {
    kc::NodeData node;
    node.id = "oak";
    node.meshIndex = 3u;
    node.materialIndex = 5u;
    node.translation = {1.25f, -2.5f, 3.75f};
    node.rotation = {0.9238795f, 0.0f, 0.38268343f, 0.0f};
    node.scale = {2.0f, 0.5f, 1.5f};
    node.tagMask = kc::TagDecorative;
    return node;
}

bool sameNode(const kc::NodeData& left, const kc::NodeData& right) {
    return left.id == right.id && left.meshIndex == right.meshIndex &&
        left.materialIndex == right.materialIndex &&
        sameVec(left.translation, right.translation) && sameQuat(left.rotation, right.rotation) &&
        sameVec(left.scale, right.scale) && sameVec(left.velocity, right.velocity) &&
        sameVec(left.angularVelocity, right.angularVelocity) &&
        left.collider.type == right.collider.type && left.collider.sensor == right.collider.sensor &&
        bits(left.collider.radius) == bits(right.collider.radius) &&
        sameVec(left.collider.halfExtents, right.collider.halfExtents) &&
        left.dynamic == right.dynamic && bits(left.mass) == bits(right.mass) &&
        bits(left.restitution) == bits(right.restitution) && left.tagMask == right.tagMask &&
        left.active == right.active && left.alive == right.alive;
}

void expectReject(
    const std::vector<std::uint8_t>& bytes,
    const std::vector<kc::NodeData>& nodes,
    std::string_view label
) {
    kc::ScatterPopulations populations;
    try {
        populations.load(bytes, nodes);
    } catch (const std::runtime_error&) {
        check(populations.empty(), "failed load retained KCSP groups");
        check(populations.totalInstances() == 0u, "failed load retained KCSP total");
        check(populations.generatedCopyCount() == 0u, "failed load retained KCSP copies");
        return;
    }
    fail(std::string("accepted invalid KCSP: ") + std::string(label));
}

template <typename Mutator>
void expectUnsafePrototype(Mutator mutate, std::string_view label) {
    auto node = oak();
    mutate(node);
    expectReject(fixture(), {node}, label);
}

void testSeedContract() {
    check(kc::scatterSplitMix64(0u) == 0xE220A8397B1DCDAFull, "SplitMix64 golden changed");
    check(kc::scatterHash64("oak") == 0x7E447CF1466E5484ull, "hash64 golden changed");
    check(
        kc::scatterHash64("oak", 7u) == 0x2FA018B8ECA72699ull,
        "seeded hash64 golden changed"
    );
    const std::string_view unicode{"grove\xF0\x9F\x8C\xB3", 9u};
    check(
        kc::scatterHash64(unicode) == 0x2283B1E425DA652Aull,
        "UTF-8 hash64 golden changed"
    );
    check(
        kc::scatterCombineSeed(7u, 3u) == 0xAEB185ABD810BEDFull,
        "combine-seed golden changed"
    );
    check(
        kc::scatterStableId(7u, kc::scatterHash64("tree"), 1u) ==
            0x8139DC489E25520Aull,
        "stable-id golden changed"
    );
    check(bits(kc::scatterSeedUnitFloat(0u)) == 0x3F6220A8u, "unit-float golden changed");
}

struct ExpectedInstance {
    std::uint64_t lineage;
    std::array<std::uint32_t, 3> translation;
    std::array<std::uint32_t, 4> rotation;
    std::array<std::uint32_t, 3> scale;
    std::uint32_t yaw;
};

constexpr std::array<ExpectedInstance, 3> Expected{
    ExpectedInstance{
        0xDF6E9843E9DA7E4Full,
        {0xBFF5F0B4u, 0xC0200000u, 0x402D1DDCu},
        {0x3D93123Fu, 0x00000000u, 0x3F7F56CCu, 0x00000000u},
        {0x400D140Du, 0x3F0D140Du, 0x3FD39E14u},
        0x400D98B9u,
    },
    ExpectedInstance{
        0x3C73BBA995B5F188ull,
        {0x4094CBE3u, 0xC0200000u, 0x40666EE9u},
        {0xBD0795ABu, 0x00000000u, 0x3F7FDC16u, 0x00000000u},
        {0x3FDE103Du, 0x3EDE103Du, 0x3FA68C2Eu},
        0x401B08C4u,
    },
    ExpectedInstance{
        0xAD120CE70D177C14ull,
        {0x3FBF6884u, 0xC0200000u, 0x3F8CB570u},
        {0xBF6B8A66u, 0x00000000u, 0x3EC890BBu, 0x00000000u},
        {0x400B29B6u, 0x3F0B29B6u, 0x3FD0BE91u},
        0x40962B25u,
    },
};

void checkInstance(
    const kc::ScatterInstanceTransform& instance,
    const ExpectedInstance& expected,
    std::uint16_t index
) {
    check(instance.index == index, "generated instance index changed");
    check(instance.lineage == expected.lineage, "generated lineage changed");
    check(
        bits(instance.translation.x) == expected.translation[0] &&
            bits(instance.translation.y) == expected.translation[1] &&
            bits(instance.translation.z) == expected.translation[2],
        "generated translation changed"
    );
    check(
        bits(instance.rotation.w) == expected.rotation[0] &&
            bits(instance.rotation.x) == expected.rotation[1] &&
            bits(instance.rotation.y) == expected.rotation[2] &&
            bits(instance.rotation.z) == expected.rotation[3],
        "generated rotation changed"
    );
    check(
        bits(instance.scale.x) == expected.scale[0] &&
            bits(instance.scale.y) == expected.scale[1] &&
            bits(instance.scale.z) == expected.scale[2],
        "generated scale changed"
    );
    check(bits(instance.yawRadians) == expected.yaw, "generated yaw changed");
    check(bits(instance.model(0, 3)) == expected.translation[0], "model x changed");
    check(bits(instance.model(1, 3)) == expected.translation[1], "model y changed");
    check(bits(instance.model(2, 3)) == expected.translation[2], "model z changed");
    for (float value : instance.model.v) check(std::isfinite(value), "model is non-finite");
}

void testFixtureAndGeneration() {
    auto nodes = std::vector<kc::NodeData>{oak()};
    const auto before = nodes.front();
    kc::ScatterPopulations populations;
    populations.load(fixture(), nodes);

    check(!populations.empty(), "60-byte fixture loaded empty");
    check(populations.groupCount() == 1u, "fixture group count changed");
    check(populations.totalInstances() == 4u, "fixture total changed");
    check(populations.generatedCopyCount() == 3u, "fixture generated count changed");
    check(sameNode(nodes.front(), before), "KCSP load mutated the authored prototype");

    const auto& group = populations.groups().front();
    check(group.prototypeNodeIndex == 0u, "fixture prototype changed");
    check(group.instanceCount == 4u, "fixture instance count changed");
    check(group.randomYaw, "fixture yaw flag changed");
    check(group.seed == 7u, "fixture seed changed");
    check(
        bits(group.size.x) == 0x41000000u && bits(group.size.y) == 0u &&
            bits(group.size.z) == 0x40C00000u,
        "fixture area changed"
    );
    check(
        bits(group.scaleMin) == 0x3F4CCCCDu && bits(group.scaleMax) == 0x3F99999Au,
        "fixture scale range changed"
    );
    check(group.instances.size() == Expected.size(), "fixture generated vector changed");
    for (std::size_t index = 0; index < Expected.size(); ++index) {
        checkInstance(group.instances[index], Expected[index], static_cast<std::uint16_t>(index + 1u));
    }

    auto shorter = fixture();
    putU16(shorter, 28u, 3u);
    putU32(shorter, 20u, 3u);
    kc::ScatterPopulations prefix;
    prefix.load(shorter, nodes);
    check(prefix.groups().front().instances.size() == 2u, "shorter prefix size changed");
    checkInstance(prefix.groups().front().instances[0], Expected[0], 1u);
    checkInstance(prefix.groups().front().instances[1], Expected[1], 2u);

    auto noYaw = fixture();
    putU16(noYaw, 30u, 0u);
    kc::ScatterPopulations aligned;
    aligned.load(noYaw, nodes);
    for (const auto& instance : aligned.groups().front().instances) {
        check(bits(instance.yawRadians) == 0u, "disabled yaw generated an angle");
        check(
            bits(instance.rotation.w) == 0x3F6C835Eu && bits(instance.rotation.x) == 0u &&
                bits(instance.rotation.y) == 0x3EC3EF15u && bits(instance.rotation.z) == 0u,
            "disabled yaw did not preserve normalized prototype rotation"
        );
    }

    populations.load({}, nodes);
    check(populations.empty(), "empty optional asset did not clear populations");
    check(populations.totalInstances() == 0u, "empty optional asset retained totals");
}

void testFormatRejections() {
    const auto nodes = std::vector<kc::NodeData>{oak()};

    auto bytes = fixture();
    bytes[0] = 'X';
    expectReject(bytes, nodes, "magic");

    bytes = fixture();
    putU32(bytes, 8u, 0x04030201u);
    expectReject(bytes, nodes, "endian");

    bytes = fixture();
    putU32(bytes, 12u, 2u);
    expectReject(bytes, nodes, "version");

    bytes = fixture();
    putU32(bytes, 16u, 0u);
    expectReject(bytes, nodes, "zero groups");

    bytes = fixture();
    putU32(bytes, 16u, 65u);
    expectReject(bytes, nodes, "too many groups");

    bytes = fixture();
    putU32(bytes, 20u, 3u);
    expectReject(bytes, nodes, "total mismatch");

    bytes = fixture();
    putU32(bytes, 20u, 1025u);
    expectReject(bytes, nodes, "total cap");

    bytes = fixture();
    bytes.pop_back();
    expectReject(bytes, nodes, "truncated group");

    bytes = fixture();
    bytes.push_back(0u);
    expectReject(bytes, nodes, "trailing byte");

    expectReject(std::vector<std::uint8_t>(kc::MaxScatterPackBytes + 1u), nodes, "pack cap");

    bytes = fixture();
    putU32(bytes, 24u, 1u);
    expectReject(bytes, nodes, "prototype index");

    bytes = fixture();
    putU16(bytes, 28u, 1u);
    expectReject(bytes, nodes, "count below range");

    bytes = fixture();
    putU16(bytes, 28u, 257u);
    expectReject(bytes, nodes, "count above range");

    bytes = fixture();
    putU16(bytes, 30u, 2u);
    expectReject(bytes, nodes, "flags");

    bytes = fixture();
    putU64(bytes, 32u, 0x100000000ull);
    expectReject(bytes, nodes, "seed range");

    bytes = fixture();
    putF32(bytes, 40u, -1.0f);
    expectReject(bytes, nodes, "negative area");

    bytes = fixture();
    putF32(bytes, 40u, std::numeric_limits<float>::quiet_NaN());
    expectReject(bytes, nodes, "non-finite area");

    bytes = fixture();
    putF32(bytes, 40u, 0.0f);
    putF32(bytes, 48u, 0.0f);
    expectReject(bytes, nodes, "empty horizontal area");

    bytes = fixture();
    putF32(bytes, 52u, 0.04f);
    expectReject(bytes, nodes, "scale below range");

    bytes = fixture();
    putF32(bytes, 56u, 8.01f);
    expectReject(bytes, nodes, "scale above range");

    bytes = fixture();
    putF32(bytes, 52u, 2.0f);
    putF32(bytes, 56u, 1.0f);
    expectReject(bytes, nodes, "reversed scale range");

    bytes = fixture();
    putF32(bytes, 52u, std::numeric_limits<float>::infinity());
    expectReject(bytes, nodes, "non-finite scale");

    auto canonical = fixture();
    canonical.insert(canonical.end(), Fixture.begin() + 24, Fixture.end());
    putU32(canonical, 16u, 2u);
    putU32(canonical, 20u, 8u);
    putU32(canonical, 60u, 1u);
    auto second = oak();
    second.id = "birch";
    kc::ScatterPopulations populations;
    populations.load(canonical, {oak(), second});
    check(populations.groupCount() == 2u, "canonical multi-group fixture failed");
    check(populations.totalInstances() == 8u, "multi-group total changed");
    check(populations.generatedCopyCount() == 6u, "multi-group copies changed");

    putU32(canonical, 60u, 0u);
    expectReject(canonical, {oak(), second}, "non-canonical prototypes");
}

void testUnsafePrototypeRejections() {
    expectUnsafePrototype([](kc::NodeData& node) { node.dynamic = true; }, "dynamic prototype");
    expectUnsafePrototype([](kc::NodeData& node) { node.collider.type = 1u; }, "collider");
    expectUnsafePrototype([](kc::NodeData& node) { node.collider.sensor = true; }, "trigger area");
    expectUnsafePrototype([](kc::NodeData& node) { node.velocity.x = 1.0f; }, "velocity");
    expectUnsafePrototype(
        [](kc::NodeData& node) { node.angularVelocity.z = -1.0f; },
        "angular velocity"
    );
    expectUnsafePrototype(
        [](kc::NodeData& node) { node.tagMask |= kc::TagPlayer; },
        "gameplay tag"
    );
    expectUnsafePrototype([](kc::NodeData& node) { node.active = false; }, "inactive prototype");
    expectUnsafePrototype([](kc::NodeData& node) { node.alive = false; }, "dead prototype");
    expectUnsafePrototype(
        [](kc::NodeData& node) { node.translation.x = std::numeric_limits<float>::infinity(); },
        "non-finite translation"
    );
    expectUnsafePrototype(
        [](kc::NodeData& node) { node.rotation = {0.0f, 0.0f, 0.0f, 0.0f}; },
        "zero quaternion"
    );
    expectUnsafePrototype([](kc::NodeData& node) { node.id.clear(); }, "empty id");
    expectUnsafePrototype(
        [](kc::NodeData& node) { node.id.assign("\xC0\x80", 2u); },
        "invalid UTF-8 id"
    );
    expectUnsafePrototype(
        [](kc::NodeData& node) { node.scale.x = std::numeric_limits<float>::max(); },
        "overflowing generated scale"
    );
}

} // namespace

int main() {
    try {
        testSeedContract();
        testFixtureAndGeneration();
        testFormatRejections();
        testUnsafePrototypeRejections();
    } catch (const std::exception& error) {
        std::cerr << "FAIL scatter populations: " << error.what() << '\n';
        return 1;
    }
    std::cout << "PASS scatter populations\n";
    return 0;
}
