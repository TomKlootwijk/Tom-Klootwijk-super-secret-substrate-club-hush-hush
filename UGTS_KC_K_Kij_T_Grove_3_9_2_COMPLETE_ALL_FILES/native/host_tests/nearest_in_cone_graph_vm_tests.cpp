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
    std::cerr << "FAIL nearest-in-cone graph VM: " << message << '\n';
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
        node("zeta",{1.1f,2.2f,3.3f},kc::TagGoal),
        node("alpha",{1.1f,-2.2f,-3.3f},kc::TagGoal),
        node("inactive_closer",{0.1f,0.0f,0.0f},kc::TagGoal,false,true),
        node("dead_closer",{0.2f,0.0f,0.0f},kc::TagGoal,true,false),
        node("cone_boundary",{3.0f,4.0f,0.0f},kc::TagCollectible),
        node("closer_outside",{0.0f,1.0f,0.0f},kc::TagCollectible),
        node("coincident",{0.0f,0.0f,0.0f},kc::TagHazard),
        node("distance_sink"),
        node("tie_found_marker",{},0,false,true),
        node("boundary_marker",{},0,false,true),
        node("coincident_zero_marker",{},0,false,true),
        node("coincident_positive_marker",{},0,true,true),
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
    if (argc!=4)
        return fail("expected valid, invalid-cone, and missing-origin KCVG paths");
    auto nodes=sceneNodes();
    kc::GraphVm vm;
    try {
        vm.load(readBytes(argv[1]),nodes.size());
    } catch (const std::exception& error) {
        std::cerr << "FAIL nearest-in-cone graph VM: " << error.what() << '\n';
        return 1;
    }
    vm.ready(nodes);
    if (!vm.issues().empty()) return fail("valid cone queries reported an issue");
    if (!nodes[9].active) return fail("nearest tie query did not report found");
    if (!nodes[10].active) return fail("inclusive radial/angular boundary was rejected");
    if (!nodes[11].active) return fail("zero-cosine cone rejected a coincident candidate");
    if (nodes[12].active) return fail("positive-cosine cone accepted a coincident candidate");
    if (std::bit_cast<std::uint32_t>(nodes[8].translation.y)!=0x4083b4d2u)
        return fail("distance output did not match the fixed float32 schedule");

    bool sawAlpha=false,sawBoundary=false,sawCoincident=false;
    for (const auto& event:vm.events()) {
        if (event.target==2) sawAlpha=true;
        else if (event.target==5) sawBoundary=true;
        else if (event.target==7) sawCoincident=true;
    }
    if (!sawAlpha) return fail("UTF-8 lexical tie did not choose alpha");
    if (!sawBoundary) return fail("boundary query did not select cone_boundary");
    if (!sawCoincident) return fail("zero-cosine query did not select coincident candidate");

    if (!invalidPackReports(argv[2],kc::GraphVmError::InvalidSearchCone,nodes.size()))
        return fail("dynamic zero-axis cone did not report InvalidSearchCone");
    if (!invalidPackReports(argv[3],kc::GraphVmError::InvalidEntity,nodes.size()))
        return fail("world cone query accepted a null origin");
    std::cout << "PASS nearest-in-cone graph VM parity\n";
    return 0;
}
