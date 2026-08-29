#include "graph_vm.hpp"

#include <algorithm>
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
    std::cerr << "FAIL timer graph VM: " << message << '\n';
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

std::vector<kc::NodeData> sceneNodes() {
    std::vector<kc::NodeData> nodes(3);
    nodes[0].id="floor";
    nodes[1].id="player";
    nodes[2].id="goal";
    return nodes;
}

std::size_t eventCount(const kc::GraphVm& vm,std::string_view kind) {
    return static_cast<std::size_t>(std::count_if(
        vm.events().begin(),vm.events().end(),
        [&](const kc::GraphEvent& event) { return event.kind==kind; }
    ));
}

void runSteps(
    kc::GraphVm& vm,
    std::vector<kc::NodeData>& nodes,
    std::uint64_t firstTick,
    std::uint64_t count,
    float dt
) {
    for (std::uint64_t offset=0;offset<count;++offset)
        vm.tick(dt,firstTick+offset,{},nodes);
}

} // namespace

int main(int argc,char** argv) {
    if (argc!=2) return fail("expected one valid KCVG pack path");
    const auto bytes=readBytes(argv[1]);
    auto nodes=sceneNodes();
    kc::GraphVm vm;
    try {
        vm.load(bytes,nodes.size());
    } catch (const std::exception& error) {
        std::cerr << "FAIL timer graph VM: " << error.what() << '\n';
        return 1;
    }
    vm.ready(nodes);
    if (!vm.issues().empty()) return fail("ready reported a runtime issue");

    constexpr float Dt=1.0f/120.0f;
    runSteps(vm,nodes,1,59,Dt);
    if (!vm.issues().empty()) return fail("pre-ring steps reported an issue");
    if (!vm.events().empty()) return fail("timer rang before active step 60");
    if (std::bit_cast<std::uint32_t>(nodes[0].translation.y)!=0x3c088889u)
        return fail("remaining did not use the float32 fixed-step schedule");

    vm.tick(Dt,60,{},nodes);
    if (!vm.issues().empty()) return fail("first ring reported an issue");
    if (nodes[0].translation.x!=1.0f || nodes[0].translation.y!=0.0f ||
        nodes[2].translation.x!=1.0f)
        return fail("count/remaining outputs were wrong on active step 60");
    if (eventCount(vm,"world_repeat")!=1 || eventCount(vm,"world_once")!=1 ||
        eventCount(vm,"bound_repeat")!=1)
        return fail("repeat and one-shot roots did not all ring at step 60");

    nodes[1].active=false;
    runSteps(vm,nodes,61,60,Dt);
    if (!vm.issues().empty()) return fail("paused-owner interval reported an issue");
    if (nodes[0].translation.x!=2.0f || nodes[2].translation.x!=1.0f)
        return fail("world timer did not advance independently of paused owner");
    if (eventCount(vm,"world_repeat")!=1 || eventCount(vm,"world_once")!=0 ||
        eventCount(vm,"bound_repeat")!=0)
        return fail("one-shot repeated or inactive entity timer advanced");

    nodes[1].active=true;
    runSteps(vm,nodes,121,60,Dt);
    if (!vm.issues().empty()) return fail("resumed-owner interval reported an issue");
    if (nodes[0].translation.x!=3.0f || nodes[2].translation.x!=2.0f)
        return fail("resumed timer did not continue from its active-step count");
    if (eventCount(vm,"world_repeat")!=1 || eventCount(vm,"bound_repeat")!=1 ||
        eventCount(vm,"world_once")!=0)
        return fail("step 120 repeat counts or one-shot flow were wrong");

    vm.ready(nodes);
    runSteps(vm,nodes,181,59,Dt);
    if (!vm.events().empty()) return fail("ready did not reset timer counters");
    vm.tick(Dt,240,{},nodes);
    if (nodes[0].translation.x!=1.0f || nodes[2].translation.x!=1.0f)
        return fail("reset timers did not ring with count one");

    auto invalidNodes=sceneNodes();
    kc::GraphVm invalid;
    invalid.load(bytes,invalidNodes.size());
    invalid.ready(invalidNodes);
    invalid.tick(0.0f,1,{},invalidNodes);
    if (invalid.issues().size()!=3 || !std::all_of(
        invalid.issues().begin(),invalid.issues().end(),
        [](const kc::GraphRuntimeIssue& issue) {
            return issue.code==kc::GraphVmError::InvalidTimerStep;
        }
    )) return fail("zero dt did not report the child-readable timer error");

    std::cout << "PASS timer graph VM parity\n";
    return 0;
}
