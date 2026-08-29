#pragma once
#include "scene_pack.hpp"
#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace kc {

struct GraphInputState {
    float moveX=0.0f, moveZ=0.0f, lookX=0.0f, lookY=0.0f;
    bool jump=false, dash=false;
};

struct GraphInputFrame {
    GraphInputState current{};
    GraphInputState previous{};
};

struct GraphEvent {
    std::string_view kind{};
    std::int32_t source=-1;
    std::int32_t target=-1;
};

enum class GraphVmError : std::uint8_t {
    None,
    StepLimit,
    TotalStepLimit,
    QueueLimit,
    DataDepth,
    MissingSource,
    TypeMismatch,
    InvalidEntity,
    InvalidComponent,
    DivideByZero,
    NonFinite,
    InvalidCompare,
    MissingState,
    EventLimit,
    TriggerLimit,
    InvalidSeedNumber,
    InvalidSeedRange,
    InvalidSpatialTag,
    InvalidSearchRadius,
    InvalidTimerDuration,
    InvalidTimerStep,
    InvalidSearchCone,
};

struct GraphRuntimeIssue {
    GraphVmError code=GraphVmError::None;
    std::uint32_t graph=0;
    std::uint16_t node=0;
};

const char* graphVmErrorName(GraphVmError error);

class GraphVm {
public:
    static constexpr std::size_t MaxDispatchSteps=1024;
    static constexpr std::size_t MaxTotalSteps=16384;
    static constexpr std::size_t MaxDataDepth=128;
    static constexpr std::size_t MaxEvents=64;
    static constexpr std::size_t MaxIssues=16;
    static constexpr std::size_t MaxTriggerEvents=256;

    void load(const std::vector<std::uint8_t>& bytes,std::size_t sceneNodeCount);
    bool empty() const { return graphs_.empty() || bindings_.empty(); }
    void ready(std::vector<NodeData>& nodes);
    void tick(float dt,std::uint64_t tick,const GraphInputFrame& input,std::vector<NodeData>& nodes);
    void trigger(bool entering,std::uint32_t sensor,std::uint32_t player,float dt,
                 std::uint64_t tick,const GraphInputFrame& input,std::vector<NodeData>& nodes);
    void finishStep(float dt,std::uint64_t tick,const GraphInputFrame& input,
                    std::vector<NodeData>& nodes);
    std::span<const GraphEvent> events() const { return {events_.data(),eventCount_}; }
    std::span<const GraphRuntimeIssue> issues() const { return {issues_.data(),issueCount_}; }
    std::string_view graphId(std::uint32_t index) const;

private:
    enum class ValueTag : std::uint8_t { Null=0, Boolean=1, Number=2, String=3, Vec3=4, Vec4=5, Vec2=6, Entity=7 };
    struct Value {
        ValueTag tag=ValueTag::Null;
        std::uint32_t index=0;
        float number=0.0f;
        std::array<float,4> vector{};
    };
    struct Graph {
        std::uint32_t id=0,nodeStart=0;
        std::uint16_t nodeCount=0,maxSteps=1024;
    };
    struct Binding {
        std::uint32_t graph=0,sceneNode=0;
        std::uint64_t activeStep=0;
        bool enabled=true;
    };
    struct Node {
        std::uint32_t inputStart=0,flowStart=0;
        std::uint16_t inputCount=0,flowZero=0,flowOne=0;
        std::uint8_t opcode=0;
    };
    struct StateSlot {
        std::uint32_t key=0;
        Value value{};
        bool set=false;
    };
    enum class Dispatch : std::uint8_t { Ready, Tick, TriggerEnter, TriggerExit, Message };

    bool dispatchBinding(Binding& binding,Dispatch dispatch,float dt,std::uint64_t tick,
                         const GraphInputFrame& input,std::vector<NodeData>& nodes,
                         std::int32_t triggerSensor,std::int32_t triggerPlayer,
                         std::size_t& totalSteps);
    void dispatchMessages(float dt,std::uint64_t tick,const GraphInputFrame& input,
                          std::vector<NodeData>& nodes,std::size_t& totalSteps);
    bool executeNode(std::uint16_t local,bool queued,std::size_t depth,std::uint8_t& flowMask);
    bool resolveInput(std::uint32_t token,std::size_t depth,std::uint16_t owner,Value& result);
    bool evaluateData(std::uint16_t local,std::size_t depth);
    bool consumeStep(std::uint16_t node);
    bool fail(GraphVmError error,std::uint16_t node);
    void recordIssue(GraphVmError error,std::uint32_t graph,std::uint16_t node);
    void resetOutput(std::uint16_t local);
    bool stringValue(const Value& value,std::string_view& result) const;
    bool numberValue(const Value& value,float& result) const;
    bool boolValue(const Value& value,bool& result) const;
    std::int32_t entityValue(const Value& value,bool emptyUsesBound) const;
    bool readComponent(std::int32_t entity,std::string_view component,std::string_view field,Value& result);
    bool writeComponent(std::int32_t entity,std::string_view component,std::string_view field,const Value& value);
    StateSlot* stateSlot(std::uint32_t key);
    bool equalValues(const Value& a,const Value& b) const;
    bool orderedCompare(const Value& a,const Value& b,int& comparison) const;
    float inputValue(std::string_view action,const GraphInputState& input) const;
    bool inputPressed(std::string_view action) const;
    bool pureData(std::uint8_t opcode) const;

    std::vector<std::string> strings_;
    std::vector<Value> values_;
    std::vector<Graph> graphs_;
    std::vector<Binding> bindings_;
    std::vector<Node> nodes_;
    std::vector<std::uint32_t> inputs_;
    std::vector<std::uint16_t> flows_;
    std::vector<StateSlot> state_;

    std::vector<std::array<Value,3>> outputs_;
    std::vector<std::uint32_t> executedStamp_;
    std::vector<std::uint32_t> dataStamp_;
    std::array<std::uint16_t,MaxDispatchSteps> queue_{};
    std::array<GraphEvent,MaxEvents> events_{};
    std::array<GraphRuntimeIssue,MaxIssues> issues_{};
    std::size_t eventCount_=0,messageCursor_=0,issueCount_=0;
    std::uint32_t dispatchStamp_=0,evaluationStamp_=0;

    const Graph* currentGraph_=nullptr;
    std::uint32_t currentGraphIndex_=0,currentBound_=0;
    std::int32_t currentTriggerSensor_=-1,currentTriggerPlayer_=-1;
    GraphEvent currentMessage_{};
    std::vector<NodeData>* currentNodes_=nullptr;
    const GraphInputFrame* currentInput_=nullptr;
    float currentDt_=0.0f;
    std::uint64_t currentTick_=0;
    std::uint64_t currentActiveStep_=0;
    std::size_t currentSteps_=0,currentLimit_=MaxDispatchSteps,*currentTotalSteps_=nullptr;
    std::size_t stepTotalSteps_=0,triggerEventCount_=0;
    bool triggerLimitReported_=false;
    GraphVmError currentError_=GraphVmError::None;
    std::uint16_t currentErrorNode_=0;
};

} // namespace kc
