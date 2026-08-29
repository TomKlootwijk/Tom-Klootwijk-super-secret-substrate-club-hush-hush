#include "graph_vm.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <exception>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace {

struct ExpectedEvent {
    std::string_view kind;
    std::int32_t source;
    std::int32_t target;
};

int fail(std::string_view message) {
    std::cerr << "FAIL message graph VM: " << message << '\n';
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
    std::vector<kc::NodeData> nodes(4);
    nodes[0].id="floor";
    nodes[1].id="player";
    nodes[2].id="goal";
    nodes[3].id="dead";
    return nodes;
}

bool eventsEqual(
    const kc::GraphVm& vm,
    std::span<const ExpectedEvent> expected,
    std::string_view phase
) {
    const auto actual=vm.events();
    if (actual.size()!=expected.size()) {
        std::cerr << "FAIL message graph VM: " << phase << " produced "
                  << actual.size() << " events, expected " << expected.size() << '\n';
        return false;
    }
    for (std::size_t index=0;index<expected.size();++index) {
        if (actual[index].kind!=expected[index].kind ||
            actual[index].source!=expected[index].source ||
            actual[index].target!=expected[index].target) {
            std::cerr << "FAIL message graph VM: " << phase << " event " << index
                      << " was " << actual[index].kind << " ("
                      << actual[index].source << ',' << actual[index].target
                      << "), expected " << expected[index].kind << " ("
                      << expected[index].source << ',' << expected[index].target
                      << ")\n";
            return false;
        }
    }
    return true;
}

} // namespace

int main(int argc,char** argv) {
    if (argc!=3) return fail("expected routing and EventLimit KCVG pack paths");

    try {
        auto nodes=sceneNodes();
        nodes[0].active=false;
        nodes[3].alive=false;

        kc::GraphVm vm;
        vm.load(readBytes(argv[1]),nodes.size());
        vm.ready(nodes);
        if (!vm.issues().empty()) return fail("Ready message drain reported a runtime issue");

        constexpr std::array<ExpectedEvent,7> ReadyEvents{{
            {"alpha",1,-1},
            {"beta",1,2},
            {"seen.player.alpha",1,1},
            {"seen.goal.alpha",1,2},
            {"seen.world.alpha",1,-1},
            {"seen.goal.beta",1,2},
            {"seen.world.beta",2,-1},
        }};
        if (!eventsEqual(vm,ReadyEvents,"Ready")) return 1;

        constexpr float Dt=1.0f/120.0f;
        vm.tick(Dt,1,{},nodes);
        constexpr std::array<ExpectedEvent,1> BeforeFinish{{
            {"tick.ping",1,-1},
        }};
        if (!eventsEqual(vm,BeforeFinish,"pre-finish tick")) return 1;
        if (!vm.issues().empty()) return fail("Tick producer reported a runtime issue");

        vm.finishStep(Dt,1,{},nodes);
        constexpr std::array<ExpectedEvent,4> FinishedEvents{{
            {"tick.ping",1,-1},
            {"seen.player.tick",1,-1},
            {"seen.goal.tick",2,-1},
            {"seen.world.tick",-1,-1},
        }};
        if (!eventsEqual(vm,FinishedEvents,"finished tick")) return 1;
        if (!vm.issues().empty()) return fail("message handlers reported a runtime issue");

        vm.finishStep(Dt,1,{},nodes);
        if (!eventsEqual(vm,FinishedEvents,"second finish")) return 1;

        auto limitNodes=sceneNodes();
        kc::GraphVm limited;
        limited.load(readBytes(argv[2]),limitNodes.size());
        limited.ready(limitNodes);
        if (limited.events().size()!=kc::GraphVm::MaxEvents)
            return fail("self-message cascade did not stop at the 64-event boundary");
        if (!std::all_of(
            limited.events().begin(),limited.events().end(),
            [](const kc::GraphEvent& event) {
                return event.kind=="loop" && event.source==-1 && event.target==-1;
            }
        )) return fail("EventLimit fixture changed the queued message context");
        if (limited.issues().size()!=1 ||
            limited.issues()[0].code!=kc::GraphVmError::EventLimit)
            return fail("self-message cascade did not report exactly one EventLimit");
        if (limited.graphId(limited.issues()[0].graph)!="limit_loop")
            return fail("EventLimit was attributed to the wrong graph");

        const auto issueCount=limited.issues().size();
        limited.finishStep(0.0f,0,{},limitNodes);
        if (limited.issues().size()!=issueCount ||
            limited.events().size()!=kc::GraphVm::MaxEvents)
            return fail("a completed EventLimit drain was not idempotent");
    } catch (const std::exception& error) {
        std::cerr << "FAIL message graph VM: " << error.what() << '\n';
        return 1;
    }

    std::cout << "PASS message graph VM routing and limits\n";
    return 0;
}
