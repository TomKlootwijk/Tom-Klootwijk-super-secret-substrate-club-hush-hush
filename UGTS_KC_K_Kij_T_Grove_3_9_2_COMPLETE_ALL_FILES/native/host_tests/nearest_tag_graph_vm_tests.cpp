#include "graph_vm.hpp"

#include <bit>
#include <cstdint>
#include <exception>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace {

int fail(std::string_view message) {
    std::cerr << "FAIL nearest-tag graph VM: " << message << '\n';
    return 1;
}

std::vector<std::uint8_t> readBytes(const char* path) {
    std::ifstream stream(path,std::ios::binary);
    if (!stream) throw std::runtime_error("could not open KCVG pack");
    std::vector<std::uint8_t> bytes;
    for (char value=0;stream.get(value);)
        bytes.push_back(static_cast<std::uint8_t>(static_cast<unsigned char>(value)));
    return bytes;
}

kc::NodeData node(
    const char* id,
    kc::Vec3 translation={},
    std::uint32_t tagMask=0,
    bool active=true,
    bool alive=true
) {
    kc::NodeData result;
    result.id=id;
    result.translation=translation;
    result.tagMask=tagMask;
    result.active=active;
    result.alive=alive;
    return result;
}

std::vector<kc::NodeData> sceneNodes() {
    return {
        node("origin",{0.0f,0.0f,0.0f},kc::TagPlayer|kc::TagGoal),
        // Reverse lexical order is intentional: alpha must win the exact tie.
        node("zeta",{1.1f,2.2f,3.3f},kc::TagGoal),
        node("alpha",{-1.1f,-2.2f,-3.3f},kc::TagGoal),
        node("closer_inactive",{0.1f,0.0f,0.0f},kc::TagGoal,false,true),
        node("closer_dead",{0.2f,0.0f,0.0f},kc::TagGoal,true,false),
        node("boundary",{4.2f,0.0f,0.0f},kc::TagCollectible),
        node("distance_sink"),
        node("found_marker",{},0,false,true),
        node("missing_found_marker"),
        node("missing_entity_null_marker",{},0,false,true),
        node("missing_distance_null_marker",{},0,false,true),
        node("boundary_marker",{},0,false,true),
    };
}

bool invalidPackReports(
    const char* path,
    kc::GraphVmError expected,
    std::size_t sceneNodeCount
) {
    kc::GraphVm vm;
    auto nodes=sceneNodes();
    try {
        vm.load(readBytes(path),sceneNodeCount);
    } catch (const std::exception& error) {
        std::cerr << "invalid fixture would not load: " << error.what() << '\n';
        return false;
    }
    vm.ready(nodes);
    const auto issues=vm.issues();
    return issues.size()==1 && issues[0].code==expected;
}

} // namespace

int main(int argc,char** argv) {
    if (argc!=5) return fail("expected valid, invalid-tag, invalid-radius, and missing-origin KCVG paths");
    auto nodes=sceneNodes();
    kc::GraphVm vm;
    try {
        vm.load(readBytes(argv[1]),nodes.size());
    } catch (const std::exception& error) {
        std::cerr << "FAIL nearest-tag graph VM: " << error.what() << '\n';
        return 1;
    }
    vm.ready(nodes);
    if (!vm.issues().empty()) return fail("valid nearest queries reported an issue");
    if (!nodes[7].active) return fail("found output was not true");
    if (nodes[8].active) return fail("no-match found output was not false");
    if (!nodes[9].active) return fail("no-match entity output was not null");
    if (!nodes[10].active) return fail("no-match distance output was not null");
    if (!nodes[11].active) return fail("inclusive radius rejected the boundary candidate");
    if (std::bit_cast<std::uint32_t>(nodes[6].translation.y)!=0x4083b4d2u)
        return fail("distance output did not match the fixed float32 schedule");
    const auto events=vm.events();
    if (events.size()!=2) return fail("bound and world queries did not both emit");
    for (const auto& event:events) {
        if (event.source!=0 || event.target!=2)
            return fail("lexical tie did not choose alpha from origin");
    }
    if (!invalidPackReports(argv[2],kc::GraphVmError::InvalidSpatialTag,nodes.size()))
        return fail("dynamic custom tag did not report InvalidSpatialTag");
    if (!invalidPackReports(argv[3],kc::GraphVmError::InvalidSearchRadius,nodes.size()))
        return fail("dynamic negative radius did not report InvalidSearchRadius");
    if (!invalidPackReports(argv[4],kc::GraphVmError::InvalidEntity,nodes.size()))
        return fail("world query accepted a null origin");
    std::cout << "PASS nearest-tag graph VM parity\n";
    return 0;
}
