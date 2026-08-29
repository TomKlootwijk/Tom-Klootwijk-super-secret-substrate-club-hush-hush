#include "graph_vm.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <cstdint>
#include <exception>
#include <fstream>
#include <initializer_list>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

constexpr std::uint32_t WorldBinding=0xffffffffu;

struct TestValue {
    std::uint8_t tag=0;
    std::uint32_t index=0;
    std::array<float,4> vector{};
};

struct TestGraph {
    std::uint32_t id=0,nodeStart=0;
    std::uint16_t nodeCount=0,maxSteps=1024;
};

struct TestBinding {
    std::uint32_t graph=0,sceneNode=0;
};

struct TestNode {
    std::uint32_t inputStart=0,flowStart=0;
    std::uint16_t inputCount=0,flowZero=0,flowOne=0;
    std::uint8_t opcode=0;
};

class PackWriter {
public:
    void u8(std::uint8_t value) { bytes_.push_back(value); }
    void u16(std::uint16_t value) {
        u8(static_cast<std::uint8_t>(value));
        u8(static_cast<std::uint8_t>(value>>8));
    }
    void u32(std::uint32_t value) {
        u8(static_cast<std::uint8_t>(value));
        u8(static_cast<std::uint8_t>(value>>8));
        u8(static_cast<std::uint8_t>(value>>16));
        u8(static_cast<std::uint8_t>(value>>24));
    }
    void f32(float value) { u32(std::bit_cast<std::uint32_t>(value)); }
    void raw(std::string_view value) {
        bytes_.insert(bytes_.end(),value.begin(),value.end());
    }
    std::vector<std::uint8_t> finish() { return std::move(bytes_); }
private:
    std::vector<std::uint8_t> bytes_;
};

std::uint32_t stringIndex(
    const std::vector<std::string>& strings,
    std::string_view wanted
) {
    const auto found=std::find(strings.begin(),strings.end(),wanted);
    if (found==strings.end()) throw std::runtime_error("test pack string is missing");
    return static_cast<std::uint32_t>(found-strings.begin());
}

void appendNode(
    std::vector<TestNode>& nodes,
    std::vector<std::uint32_t>& inputs,
    std::vector<std::uint16_t>& flows,
    std::uint8_t opcode,
    std::initializer_list<std::uint32_t> nodeInputs,
    std::initializer_list<std::uint16_t> flowZero={},
    std::initializer_list<std::uint16_t> flowOne={}
) {
    nodes.push_back({
        static_cast<std::uint32_t>(inputs.size()),
        static_cast<std::uint32_t>(flows.size()),
        static_cast<std::uint16_t>(nodeInputs.size()),
        static_cast<std::uint16_t>(flowZero.size()),
        static_cast<std::uint16_t>(flowOne.size()),
        opcode,
    });
    inputs.insert(inputs.end(),nodeInputs.begin(),nodeInputs.end());
    flows.insert(flows.end(),flowZero.begin(),flowZero.end());
    flows.insert(flows.end(),flowOne.begin(),flowOne.end());
}

TestGraph appendLinearGraph(
    std::vector<TestNode>& nodes,
    std::vector<std::uint32_t>& inputs,
    std::vector<std::uint16_t>& flows,
    std::uint32_t graphId,
    std::uint8_t eventOpcode,
    std::uint16_t nodeCount,
    std::uint32_t trueValue
) {
    if (nodeCount<1) throw std::runtime_error("linear test graph needs a root");
    const auto start=static_cast<std::uint32_t>(nodes.size());
    if (nodeCount==1) appendNode(nodes,inputs,flows,eventOpcode,{});
    else appendNode(nodes,inputs,flows,eventOpcode,{}, {1});
    for (std::uint16_t local=1;local<nodeCount;++local) {
        if (local+1<nodeCount)
            appendNode(nodes,inputs,flows,4,{trueValue},{static_cast<std::uint16_t>(local+1)});
        else appendNode(nodes,inputs,flows,4,{trueValue});
    }
    return {graphId,start,nodeCount,1024};
}

std::vector<std::uint8_t> buildPack(
    const std::vector<std::string>& strings,
    const std::vector<TestValue>& values,
    const std::vector<TestGraph>& graphs,
    const std::vector<TestBinding>& bindings,
    const std::vector<TestNode>& nodes,
    const std::vector<std::uint32_t>& inputs,
    const std::vector<std::uint16_t>& flows
) {
    if (!std::is_sorted(strings.begin(),strings.end()))
        throw std::runtime_error("test pack strings are not canonical");
    PackWriter writer;
    writer.raw(std::string_view("KCVG001\0",8));
    writer.u32(0x01020304u);
    writer.u32(1);
    writer.u32(static_cast<std::uint32_t>(strings.size()));
    writer.u32(static_cast<std::uint32_t>(values.size()));
    writer.u32(static_cast<std::uint32_t>(graphs.size()));
    writer.u32(static_cast<std::uint32_t>(bindings.size()));
    writer.u32(static_cast<std::uint32_t>(nodes.size()));
    writer.u32(static_cast<std::uint32_t>(inputs.size()));
    writer.u32(static_cast<std::uint32_t>(flows.size()));
    writer.u32(0);
    for (const auto& value:strings) {
        writer.u16(static_cast<std::uint16_t>(value.size()));
        writer.raw(value);
    }
    for (const auto& value:values) {
        writer.u8(value.tag);
        if (value.tag==1) writer.u8(static_cast<std::uint8_t>(value.index));
        else if (value.tag==2) writer.f32(value.vector[0]);
        else if (value.tag==3) writer.u32(value.index);
        else if (value.tag==4 || value.tag==5 || value.tag==6) {
            const std::size_t count=value.tag==4?3:(value.tag==5?4:2);
            for (std::size_t index=0;index<count;++index) writer.f32(value.vector[index]);
        }
    }
    for (const auto& graph:graphs) {
        writer.u32(graph.id);
        writer.u32(graph.nodeStart);
        writer.u16(graph.nodeCount);
        writer.u16(graph.maxSteps);
    }
    for (const auto& binding:bindings) {
        writer.u32(binding.graph);
        writer.u32(binding.sceneNode);
    }
    for (const auto& node:nodes) {
        writer.u32(node.inputStart);
        writer.u32(node.flowStart);
        writer.u16(node.inputCount);
        writer.u16(node.flowZero);
        writer.u16(node.flowOne);
        writer.u8(node.opcode);
        writer.u8(0);
    }
    for (const auto input:inputs) writer.u32(input);
    for (const auto flow:flows) writer.u16(flow);
    return writer.finish();
}

std::vector<std::uint8_t> rootlessBoundaryPack(
    std::uint8_t heavyEvent,
    std::uint8_t observerEvent,
    std::string marker
) {
    std::vector<std::string> strings{"heavy","observer",marker};
    std::sort(strings.begin(),strings.end());
    const auto heavyId=stringIndex(strings,"heavy");
    const auto observerId=stringIndex(strings,"observer");
    const auto markerId=stringIndex(strings,marker);
    std::vector<TestValue> values{
        {1,1,{}},
        {0,0,{}},
        {3,markerId,{}},
    };
    std::vector<TestNode> nodes;
    std::vector<std::uint32_t> inputs;
    std::vector<std::uint16_t> flows;
    std::vector<TestGraph> graphs;
    graphs.push_back(appendLinearGraph(nodes,inputs,flows,heavyId,heavyEvent,1024,0));
    const auto observerStart=static_cast<std::uint32_t>(nodes.size());
    appendNode(nodes,inputs,flows,observerEvent,{}, {1});
    appendNode(nodes,inputs,flows,15,{2,1,1,1});
    graphs.push_back({observerId,observerStart,2,1024});
    std::vector<TestBinding> bindings;
    for (std::uint32_t scene=0;scene<16;++scene) bindings.push_back({0,scene});
    bindings.push_back({1,16});
    return buildPack(strings,values,graphs,bindings,nodes,inputs,flows);
}

std::vector<std::uint8_t> unmatchedMessageBoundaryPack() {
    std::vector<std::string> strings{
        "a_emitter","b_heavy","c_tail","other","probe","z_unmatched",
    };
    std::vector<TestValue> values{
        {1,1,{}},
        {0,0,{}},
        {3,stringIndex(strings,"probe"),{}},
        {3,stringIndex(strings,"other"),{}},
    };
    std::vector<TestNode> nodes;
    std::vector<std::uint32_t> inputs;
    std::vector<std::uint16_t> flows;
    std::vector<TestGraph> graphs;
    appendNode(nodes,inputs,flows,2,{}, {1});
    appendNode(nodes,inputs,flows,15,{2,1,1,1});
    graphs.push_back({stringIndex(strings,"a_emitter"),0,2,1024});
    graphs.push_back(appendLinearGraph(
        nodes,inputs,flows,stringIndex(strings,"b_heavy"),2,1024,0
    ));
    graphs.push_back(appendLinearGraph(
        nodes,inputs,flows,stringIndex(strings,"c_tail"),2,1022,0
    ));
    const auto unmatchedStart=static_cast<std::uint32_t>(nodes.size());
    appendNode(nodes,inputs,flows,25,{3});
    graphs.push_back({stringIndex(strings,"z_unmatched"),unmatchedStart,1,1024});
    std::vector<TestBinding> bindings{{0,0}};
    for (std::uint32_t scene=1;scene<=15;++scene) bindings.push_back({1,scene});
    bindings.push_back({2,16});
    bindings.push_back({3,17});
    return buildPack(strings,values,graphs,bindings,nodes,inputs,flows);
}

std::vector<std::uint8_t> siblingAbortPack() {
    std::vector<std::string> strings{
        "a_cascade","floor","loop","sibling","z_sibling",
    };
    std::vector<TestValue> values{
        {0,0,{}},
        {3,stringIndex(strings,"loop"),{}},
        {3,stringIndex(strings,"floor"),{}},
        {6,0,{1.0f,0.0f,0.0f,0.0f}},
        {3,stringIndex(strings,"sibling"),{}},
    };
    std::vector<TestNode> nodes;
    std::vector<std::uint32_t> inputs;
    std::vector<std::uint16_t> flows;
    appendNode(nodes,inputs,flows,1,{}, {1});
    appendNode(nodes,inputs,flows,15,{1,0,0,0});
    appendNode(nodes,inputs,flows,25,{1},{3,4});
    appendNode(nodes,inputs,flows,15,{1,0,0,0});
    appendNode(nodes,inputs,flows,15,{1,0,0,0});
    const TestGraph cascade{stringIndex(strings,"a_cascade"),0,5,1024};
    const auto siblingStart=static_cast<std::uint32_t>(nodes.size());
    appendNode(nodes,inputs,flows,25,{1},{1});
    appendNode(nodes,inputs,flows,18,{2,3},{2});
    appendNode(nodes,inputs,flows,15,{4,0,0,0});
    const TestGraph sibling{stringIndex(strings,"z_sibling"),siblingStart,3,1024};
    return buildPack(
        strings,values,{cascade,sibling},
        {{0,WorldBinding},{1,WorldBinding}},nodes,inputs,flows
    );
}

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

std::size_t eventCount(const kc::GraphVm& vm,std::string_view kind) {
    return static_cast<std::size_t>(std::count_if(
        vm.events().begin(),vm.events().end(),
        [&](const kc::GraphEvent& event) { return event.kind==kind; }
    ));
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

        std::vector<kc::NodeData> boundaryNodes(17);
        kc::GraphVm readyBoundary;
        readyBoundary.load(rootlessBoundaryPack(1,2,"ready.rootless.survived"),boundaryNodes.size());
        readyBoundary.ready(boundaryNodes);
        if (!readyBoundary.issues().empty())
            return fail("a rootless Ready binding was charged at the exact total-step boundary");
        readyBoundary.tick(Dt,2,{},boundaryNodes);
        if (!readyBoundary.issues().empty() ||
            eventCount(readyBoundary,"ready.rootless.survived")!=1)
            return fail("the rootless Ready binding was disabled before its Tick root could run");

        kc::GraphVm tickBoundary;
        tickBoundary.load(rootlessBoundaryPack(2,1,"tick.rootless.survived"),boundaryNodes.size());
        tickBoundary.ready(boundaryNodes);
        if (!tickBoundary.issues().empty() ||
            eventCount(tickBoundary,"tick.rootless.survived")!=1)
            return fail("Tick boundary observer did not run during initial Ready");
        tickBoundary.tick(Dt,3,{},boundaryNodes);
        if (!tickBoundary.issues().empty())
            return fail("a rootless Tick binding was charged at the exact total-step boundary");
        tickBoundary.ready(boundaryNodes);
        if (!tickBoundary.issues().empty() ||
            eventCount(tickBoundary,"tick.rootless.survived")!=1)
            return fail("the rootless Tick binding was disabled by the boundary precheck");

        std::vector<kc::NodeData> messageBoundaryNodes(18);
        kc::GraphVm messageBoundary;
        messageBoundary.load(unmatchedMessageBoundaryPack(),messageBoundaryNodes.size());
        messageBoundary.ready(messageBoundaryNodes);
        messageBoundary.tick(Dt,4,{},messageBoundaryNodes);
        if (!messageBoundary.issues().empty() ||
            eventCount(messageBoundary,"probe")!=1)
            return fail("message boundary producer did not reach exactly 16384 steps");
        messageBoundary.finishStep(Dt,4,{},messageBoundaryNodes);
        if (!messageBoundary.issues().empty() ||
            eventCount(messageBoundary,"probe")!=1)
            return fail("an unmatched Message root was charged after the total-step boundary");

        std::vector<kc::NodeData> siblingNodes(1);
        siblingNodes[0].id="floor";
        siblingNodes[0].dynamic=true;
        siblingNodes[0].mass=1.0f;
        kc::GraphVm siblingAbort;
        siblingAbort.load(siblingAbortPack(),siblingNodes.size());
        siblingAbort.ready(siblingNodes);
        if (siblingAbort.events().size()!=kc::GraphVm::MaxEvents ||
            eventCount(siblingAbort,"loop")!=43 ||
            eventCount(siblingAbort,"sibling")!=21)
            return fail("EventLimit did not preserve the 64 accepted events before aborting");
        if (siblingAbort.issues().size()!=1 ||
            siblingAbort.issues()[0].code!=kc::GraphVmError::EventLimit)
            return fail("EventLimit continued into a sibling handler or reported more than once");
        if (siblingNodes[0].velocity.x!=21.0f)
            return fail("EventLimit continued the current sibling or a pending message");
        if (std::string_view(kc::graphVmErrorName(kc::GraphVmError::EventLimit))!=
            "EventLimit: message queue exceeded 64 events")
            return fail("native EventLimit diagnostics do not expose the literal error name");
        siblingAbort.finishStep(0.0f,0,{},siblingNodes);
        if (siblingAbort.issues().size()!=1 ||
            siblingAbort.events().size()!=kc::GraphVm::MaxEvents ||
            siblingNodes[0].velocity.x!=21.0f)
            return fail("EventLimit did not clear the pending outer message batch");
    } catch (const std::exception& error) {
        std::cerr << "FAIL message graph VM: " << error.what() << '\n';
        return 1;
    }

    std::cout << "PASS message graph VM routing and limits\n";
    return 0;
}
