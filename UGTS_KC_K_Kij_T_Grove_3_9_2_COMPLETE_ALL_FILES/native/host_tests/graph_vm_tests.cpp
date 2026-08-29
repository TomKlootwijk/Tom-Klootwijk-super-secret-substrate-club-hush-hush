#include "graph_vm.hpp"

#include <bit>
#include <cmath>
#include <cstdint>
#include <exception>
#include <fstream>
#include <iostream>
#include <string_view>
#include <vector>

namespace {

bool near(float a, float b) {
    return std::abs(a - b) <= 1.0e-5f;
}

int fail(std::string_view message) {
    std::cerr << "FAIL graph VM world binding: " << message << '\n';
    return 1;
}

} // namespace

int main(int argc, char** argv) {
    if (argc != 3) return fail("expected valid and invalid KCVG pack paths");
    std::ifstream stream(argv[1], std::ios::binary);
    if (!stream) return fail("could not open KCVG pack");
    std::vector<std::uint8_t> bytes;
    for (char value = 0; stream.get(value);) {
        bytes.push_back(static_cast<std::uint8_t>(static_cast<unsigned char>(value)));
    }

    std::vector<kc::NodeData> nodes(3);
    nodes[0].id = "floor";
    nodes[1].id = "player";
    nodes[1].dynamic = true;
    nodes[1].mass = 2.0f;
    nodes[2].id = "goal";
    kc::GraphVm vm;
    try {
        vm.load(bytes, nodes.size());
    } catch (const std::exception& error) {
        std::cerr << "FAIL graph VM world binding: " << error.what() << '\n';
        return 1;
    }
    if (vm.empty()) return fail("world graph was not loaded");

    vm.ready(nodes);
    if (!vm.issues().empty()) return fail("ready reported a runtime issue");
    if (!near(nodes[1].translation.x, 3.5f)) return fail("ready did not edit explicit player component");
    if (std::bit_cast<std::uint32_t>(nodes[2].translation.y) != 0xc0f72cb8u) {
        return fail("opcode 21 Repeatable Random Number did not match the binary32 golden");
    }
    if (!near(nodes[1].velocity.x, 2.0f) || !near(nodes[1].velocity.z, 3.0f)) {
        return fail("portable Apply Force did not update 3D velocity");
    }
    const auto readyEvents = vm.events();
    if (readyEvents.size() != 1 || readyEvents[0].kind != "world_ready") {
        return fail("ready event was not emitted");
    }
    if (readyEvents[0].source != -1 || readyEvents[0].target != -1) {
        return fail("world event incorrectly acquired an entity owner");
    }

    // A world graph is independent from any one entity's active lifecycle.
    nodes[1].active = false;
    vm.tick(1.0f / 120.0f, 1, {}, nodes);
    if (!vm.issues().empty()) return fail("tick reported a runtime issue");
    if (!near(nodes[1].translation.y, 7.0f)) return fail("world tick stopped with inactive player");
    if (!near(nodes[1].translation.z, 0.0f)) return fail("inactive entity-bound graph still ran");

    vm.trigger(true,2,1,1.0f/120.0f,1,{},nodes);
    if (!vm.issues().empty()) return fail("trigger enter reported a runtime issue");
    if (!near(nodes[2].translation.x,11.0f)) return fail("sensor-bound enter graph did not run");
    if (!near(nodes[1].translation.y,12.0f)) return fail("trigger player context was not portable");
    const auto enterEvents=vm.events();
    if (enterEvents.size()!=1 || enterEvents[0].kind!="player_entered" ||
        enterEvents[0].source!=2 || enterEvents[0].target!=1)
        return fail("world trigger enter context was incorrect");

    vm.trigger(false,2,1,1.0f/120.0f,1,{},nodes);
    if (!vm.issues().empty()) return fail("trigger exit reported a runtime issue");
    if (!near(nodes[2].translation.x,-11.0f)) return fail("sensor-bound exit graph did not run");
    const auto exitEvents=vm.events();
    if (exitEvents.size()!=2 || exitEvents[1].kind!="player_exited" ||
        exitEvents[1].source!=2 || exitEvents[1].target!=1)
        return fail("world trigger exit context was incorrect");

    std::ifstream invalidStream(argv[2], std::ios::binary);
    if (!invalidStream) return fail("could not open invalid-seed KCVG pack");
    std::vector<std::uint8_t> invalidBytes;
    for (char value = 0; invalidStream.get(value);) {
        invalidBytes.push_back(static_cast<std::uint8_t>(static_cast<unsigned char>(value)));
    }
    kc::GraphVm invalidVm;
    try {
        invalidVm.load(invalidBytes, nodes.size());
    } catch (const std::exception& error) {
        std::cerr << "FAIL graph VM world binding: " << error.what() << '\n';
        return 1;
    }
    invalidVm.ready(nodes);
    const auto invalidIssues = invalidVm.issues();
    if (invalidIssues.size() != 1 ||
        invalidIssues[0].code != kc::GraphVmError::InvalidSeedNumber) {
        return fail("opcode 21 accepted linked binary32 value 392.1");
    }

    std::cout << "PASS graph VM world binding\n";
    return 0;
}
