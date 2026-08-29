#include "graph_vm.hpp"
#include "scatter_population.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>

namespace kc {
namespace {

constexpr char Magic[8]={'K','C','V','G','0','0','1','\0'};
constexpr std::uint32_t Endian=0x01020304u,Version=1u;
constexpr std::uint32_t MaxGraphs=256,MaxBindings=4096,MaxNodes=8192;
constexpr std::uint32_t MaxNodesPerGraph=1024,MaxInputs=65535,MaxFlows=65535;
constexpr std::uint32_t MaxValues=65535,MaxStrings=65535,MaxState=4096;
constexpr std::size_t MaxStringBytes=1024u*1024u,MaxPackBytes=8u*1024u*1024u;
constexpr std::uint32_t WorldBinding=0xffffffffu;

class Reader {
public:
    explicit Reader(const std::vector<std::uint8_t>& data):data_(data) {}
    std::size_t remaining() const { return data_.size()-offset_; }
    const std::uint8_t* raw(std::size_t count) {
        if (count>remaining()) throw std::runtime_error("truncated KCVG graph pack");
        const auto* result=data_.data()+offset_; offset_+=count; return result;
    }
    std::uint8_t u8() { return *raw(1); }
    std::uint16_t u16() {
        const auto* p=raw(2); return static_cast<std::uint16_t>(p[0] | (static_cast<std::uint16_t>(p[1])<<8));
    }
    std::uint32_t u32() {
        const auto* p=raw(4);
        return static_cast<std::uint32_t>(p[0]) |
               (static_cast<std::uint32_t>(p[1])<<8) |
               (static_cast<std::uint32_t>(p[2])<<16) |
               (static_cast<std::uint32_t>(p[3])<<24);
    }
    float f32() {
        const auto bits=u32(); float result=0.0f;
        std::memcpy(&result,&bits,sizeof(result));
        if (!std::isfinite(result)) throw std::runtime_error("KCVG number is not finite");
        return result;
    }
private:
    const std::vector<std::uint8_t>& data_;
    std::size_t offset_=0;
};

void require(bool condition,const char* message) {
    if (!condition) throw std::runtime_error(message);
}

std::uint16_t expectedInputs(std::uint8_t opcode) {
    switch (opcode) {
        case 1: case 2: case 19: case 20: return 0;
        case 3: case 4: case 5: case 16: case 17: return opcode==16?2:1;
        case 6: case 8: case 9: case 10: case 11: case 13: case 18: return 2;
        case 7: case 14: case 15: return 4;
        case 21: return 4;
        case 22: return 3;
        case 12: return 3;
        default: throw std::runtime_error("KCVG opcode is unknown");
    }
}

std::uint8_t dataOutputs(std::uint8_t opcode) {
    switch (opcode) {
        case 1: return 1;
        case 2: case 3: case 19: case 20: return 3;
        case 5: case 6: case 7: case 8: case 9: case 10: case 11: case 12: case 15: return 1;
        case 21: return 1;
        case 22: return 3;
        default: return 0;
    }
}

std::uint8_t flowOutputs(std::uint8_t opcode) {
    if (opcode==4) return 2;
    if (opcode==1 || opcode==2 || opcode==3 || opcode==19 || opcode==20 ||
        (opcode>=13 && opcode<=18)) return 1;
    return 0;
}

bool fieldIndex3(std::string_view field,int& index) {
    if (field=="x" || field=="0") index=0;
    else if (field=="y" || field=="1") index=1;
    else if (field=="z" || field=="2") index=2;
    else return false;
    return true;
}

bool fieldIndex4(std::string_view field,int& index) {
    if (field=="w" || field=="0") index=0;
    else if (field=="x" || field=="1") index=1;
    else if (field=="y" || field=="2") index=2;
    else if (field=="z" || field=="3") index=3;
    else return false;
    return true;
}

float vec3At(const Vec3& value,int index) {
    return index==0?value.x:(index==1?value.y:value.z);
}

void setVec3At(Vec3& value,int index,float item) {
    if (index==0) value.x=item; else if (index==1) value.y=item; else value.z=item;
}

float quatAt(const Quat& value,int index) {
    return index==0?value.w:(index==1?value.x:(index==2?value.y:value.z));
}

void setQuatAt(Quat& value,int index,float item) {
    if (index==0) value.w=item; else if (index==1) value.x=item; else if (index==2) value.y=item; else value.z=item;
}

float roundedFloat(float value) {
    volatile float rounded=value;
    return rounded;
}

bool portableTagMask(std::string_view tag,std::uint32_t& mask) {
    if (tag=="player") mask=TagPlayer;
    else if (tag=="collectible") mask=TagCollectible;
    else if (tag=="goal") mask=TagGoal;
    else if (tag=="decorative") mask=TagDecorative;
    else if (tag=="hazard") mask=TagHazard;
    else return false;
    return true;
}

bool finiteVec3(const Vec3& value) {
    return std::isfinite(value.x) && std::isfinite(value.y) &&
           std::isfinite(value.z);
}

bool utf8Less(std::string_view left,std::string_view right) {
    return std::lexicographical_compare(
        left.begin(),left.end(),right.begin(),right.end(),
        [](char a,char b) {
            return static_cast<unsigned char>(a)<static_cast<unsigned char>(b);
        }
    );
}

} // namespace

const char* graphVmErrorName(GraphVmError error) {
    switch (error) {
        case GraphVmError::None: return "none";
        case GraphVmError::StepLimit: return "step limit";
        case GraphVmError::TotalStepLimit: return "fixed-step graph budget";
        case GraphVmError::QueueLimit: return "flow queue limit";
        case GraphVmError::DataDepth: return "data depth limit";
        case GraphVmError::MissingSource: return "data source has not run";
        case GraphVmError::TypeMismatch: return "value type mismatch";
        case GraphVmError::InvalidEntity: return "invalid entity";
        case GraphVmError::InvalidComponent: return "invalid component field/value";
        case GraphVmError::DivideByZero: return "division by zero";
        case GraphVmError::NonFinite: return "non-finite math result";
        case GraphVmError::InvalidCompare: return "unsupported comparison";
        case GraphVmError::MissingState: return "missing packed state key";
        case GraphVmError::EventLimit: return "event queue limit";
        case GraphVmError::TriggerLimit: return "trigger event limit";
        case GraphVmError::InvalidSeedNumber: return "World number and Pick number must be whole numbers from 0 to 65535";
        case GraphVmError::InvalidSeedRange: return "Smallest must not be bigger than Largest";
        case GraphVmError::InvalidSpatialTag: return "tag must be player, collectible, goal, decorative, or hazard";
        case GraphVmError::InvalidSearchRadius: return "radius must be finite, non-negative, and fit deterministic float32 math";
    }
    return "unknown graph error";
}

std::string_view GraphVm::graphId(std::uint32_t index) const {
    if (index>=graphs_.size() || graphs_[index].id>=strings_.size()) return {};
    return strings_[graphs_[index].id];
}

void GraphVm::load(const std::vector<std::uint8_t>& bytes,std::size_t sceneNodeCount) {
    strings_.clear(); values_.clear(); graphs_.clear(); bindings_.clear(); nodes_.clear();
    inputs_.clear(); flows_.clear(); state_.clear(); outputs_.clear();
    executedStamp_.clear(); dataStamp_.clear(); eventCount_=issueCount_=0;
    dispatchStamp_=evaluationStamp_=0;
    if (bytes.empty()) return;
    require(bytes.size()<=MaxPackBytes,"KCVG byte limit exceeded");
    Reader r(bytes);
    require(std::memcmp(r.raw(8),Magic,8)==0,"KCVG magic mismatch");
    require(r.u32()==Endian,"KCVG endian marker mismatch");
    require(r.u32()==Version,"unsupported KCVG version");
    const auto stringCount=r.u32(),valueCount=r.u32(),graphCount=r.u32(),bindingCount=r.u32();
    const auto nodeCount=r.u32(),inputCount=r.u32(),flowCount=r.u32(),stateCount=r.u32();
    require(stringCount<=MaxStrings && valueCount<=MaxValues && graphCount<=MaxGraphs && bindingCount<=MaxBindings,
            "KCVG table count limit exceeded");
    require(nodeCount<=MaxNodes && inputCount<=MaxInputs && flowCount<=MaxFlows && stateCount<=MaxState,
            "KCVG program count limit exceeded");

    strings_.reserve(stringCount);
    std::size_t stringBytes=0;
    for (std::uint32_t i=0;i<stringCount;++i) {
        const auto length=r.u16(); stringBytes+=length;
        require(stringBytes<=MaxStringBytes,"KCVG string byte limit exceeded");
        const auto* text=r.raw(length);
        strings_.emplace_back(reinterpret_cast<const char*>(text),length);
        if (i>0) require(strings_[i-1]<strings_[i],"KCVG strings are not canonical");
    }
    values_.reserve(valueCount);
    for (std::uint32_t i=0;i<valueCount;++i) {
        Value value; const auto tag=r.u8();
        require(tag<=static_cast<std::uint8_t>(ValueTag::Vec2),"KCVG value tag invalid");
        value.tag=static_cast<ValueTag>(tag);
        if (value.tag==ValueTag::Boolean) {
            const auto raw=r.u8(); require(raw<=1,"KCVG boolean invalid"); value.index=raw;
        } else if (value.tag==ValueTag::Number) value.number=r.f32();
        else if (value.tag==ValueTag::String) {
            value.index=r.u32(); require(value.index<stringCount,"KCVG string value reference invalid");
        } else if (value.tag==ValueTag::Vec2 || value.tag==ValueTag::Vec3 || value.tag==ValueTag::Vec4) {
            const int count=value.tag==ValueTag::Vec2?2:(value.tag==ValueTag::Vec3?3:4);
            for (int j=0;j<count;++j) value.vector[static_cast<std::size_t>(j)]=r.f32();
        }
        values_.push_back(value);
    }
    state_.reserve(stateCount);
    std::uint32_t previousState=0;
    for (std::uint32_t i=0;i<stateCount;++i) {
        const auto key=r.u32(); require(key<stringCount,"KCVG state string reference invalid");
        if (i>0) require(previousState<key,"KCVG state keys are not canonical");
        previousState=key; state_.push_back({key,{},false});
    }
    graphs_.reserve(graphCount);
    std::uint32_t expectedNodeStart=0,previousGraphId=0;
    for (std::uint32_t i=0;i<graphCount;++i) {
        Graph graph; graph.id=r.u32(); graph.nodeStart=r.u32(); graph.nodeCount=r.u16(); graph.maxSteps=r.u16();
        require(graph.id<stringCount && graph.nodeStart==expectedNodeStart && graph.nodeCount<=MaxNodesPerGraph,
                "KCVG graph range invalid");
        require(graph.maxSteps>0 && graph.maxSteps<=MaxDispatchSteps,"KCVG graph step limit invalid");
        if (i>0) require(strings_[previousGraphId]<strings_[graph.id],"KCVG graphs are not canonical");
        previousGraphId=graph.id; expectedNodeStart+=graph.nodeCount; graphs_.push_back(graph);
    }
    require(expectedNodeStart==nodeCount,"KCVG graph node totals differ");
    bindings_.reserve(bindingCount);
    std::uint32_t previousScene=0,previousBindingGraph=0;
    for (std::uint32_t i=0;i<bindingCount;++i) {
        Binding binding; binding.graph=r.u32(); binding.sceneNode=r.u32();
        require(binding.graph<graphCount &&
                (binding.sceneNode==WorldBinding || binding.sceneNode<sceneNodeCount),
                "KCVG binding reference invalid");
        if (i>0) {
            const bool ordered=binding.sceneNode>previousScene ||
                (binding.sceneNode==previousScene && strings_[graphs_[previousBindingGraph].id]<strings_[graphs_[binding.graph].id]);
            require(ordered,"KCVG bindings are not canonical");
        }
        previousScene=binding.sceneNode; previousBindingGraph=binding.graph;
        bindings_.push_back(binding);
    }
    nodes_.reserve(nodeCount);
    std::uint32_t expectedInput=0,expectedFlow=0;
    for (std::uint32_t i=0;i<nodeCount;++i) {
        Node node; node.inputStart=r.u32(); node.flowStart=r.u32(); node.inputCount=r.u16();
        node.flowZero=r.u16(); node.flowOne=r.u16(); node.opcode=r.u8(); const auto flags=r.u8();
        require(flags==0 && node.inputStart==expectedInput && node.flowStart==expectedFlow,"KCVG node range/flags invalid");
        require(node.inputCount==expectedInputs(node.opcode),"KCVG node input count invalid");
        const auto ports=flowOutputs(node.opcode);
        require((ports>=1 || node.flowZero==0) && (ports>=2 || node.flowOne==0),"KCVG node flow output invalid");
        expectedInput+=node.inputCount; expectedFlow+=node.flowZero+node.flowOne;
        nodes_.push_back(node);
    }
    require(expectedInput==inputCount && expectedFlow==flowCount,"KCVG input/flow totals differ");
    inputs_.resize(inputCount); for (auto& input:inputs_) input=r.u32();
    flows_.resize(flowCount); for (auto& flow:flows_) flow=r.u16();
    require(r.remaining()==0,"KCVG trailing bytes");

    std::size_t maxGraphNodes=0;
    for (const auto& graph:graphs_) {
        maxGraphNodes=std::max(maxGraphNodes,static_cast<std::size_t>(graph.nodeCount));
        for (std::uint16_t local=0;local<graph.nodeCount;++local) {
            const auto& node=nodes_[graph.nodeStart+local];
            for (std::uint16_t j=0;j<node.inputCount;++j) {
                const auto token=inputs_[node.inputStart+j],kind=token>>30,payload=token&0xffffu,output=(token>>16)&0xffu;
                if (kind==0) require((token&0x3fff0000u)==0 && payload<valueCount,"KCVG literal input invalid");
                else if (kind==1) {
                    require((token&0x3f000000u)==0 && payload<graph.nodeCount,"KCVG source input invalid");
                    require(output<dataOutputs(nodes_[graph.nodeStart+payload].opcode),"KCVG source output invalid");
                } else throw std::runtime_error("KCVG input kind reserved");
            }
            const auto count=static_cast<std::uint32_t>(node.flowZero)+node.flowOne;
            for (std::uint32_t j=0;j<count;++j) require(flows_[node.flowStart+j]<graph.nodeCount,"KCVG flow target invalid");
        }
    }
    outputs_.resize(maxGraphNodes); executedStamp_.assign(maxGraphNodes,0); dataStamp_.assign(maxGraphNodes,0);
}

void GraphVm::ready(std::vector<NodeData>& nodes) {
    eventCount_=issueCount_=0; std::size_t totalSteps=0; const GraphInputFrame input{};
    for (auto& binding:bindings_) {
        const bool world=binding.sceneNode==WorldBinding;
        if (!binding.enabled || (!world && (binding.sceneNode>=nodes.size() ||
            !nodes[binding.sceneNode].alive || !nodes[binding.sceneNode].active))) continue;
        if (totalSteps>=MaxTotalSteps) {
            binding.enabled=false; recordIssue(GraphVmError::TotalStepLimit,binding.graph,0); break;
        }
        dispatchBinding(binding,Dispatch::Ready,0.0f,0,input,nodes,-1,-1,totalSteps);
    }
}

void GraphVm::tick(float dt,std::uint64_t tick,const GraphInputFrame& input,std::vector<NodeData>& nodes) {
    eventCount_=issueCount_=0; stepTotalSteps_=0; triggerEventCount_=0; triggerLimitReported_=false;
    for (auto& binding:bindings_) {
        const bool world=binding.sceneNode==WorldBinding;
        if (!binding.enabled || (!world && (binding.sceneNode>=nodes.size() ||
            !nodes[binding.sceneNode].alive || !nodes[binding.sceneNode].active))) continue;
        if (stepTotalSteps_>=MaxTotalSteps) {
            binding.enabled=false; recordIssue(GraphVmError::TotalStepLimit,binding.graph,0); break;
        }
        dispatchBinding(binding,Dispatch::Tick,dt,tick,input,nodes,-1,-1,stepTotalSteps_);
    }
}

void GraphVm::trigger(bool entering,std::uint32_t sensor,std::uint32_t player,float dt,
                      std::uint64_t tick,const GraphInputFrame& input,std::vector<NodeData>& nodes) {
    if (bindings_.empty() || sensor>=nodes.size() || player>=nodes.size()) return;
    if (triggerEventCount_>=MaxTriggerEvents) {
        if (!triggerLimitReported_) {
            recordIssue(GraphVmError::TriggerLimit,0,0);
            triggerLimitReported_=true;
        }
        return;
    }
    ++triggerEventCount_;
    const auto dispatch=entering?Dispatch::TriggerEnter:Dispatch::TriggerExit;
    for (auto& binding:bindings_) {
        const bool world=binding.sceneNode==WorldBinding;
        if (!binding.enabled || (!world && binding.sceneNode!=sensor)) continue;
        if (!world && (binding.sceneNode>=nodes.size() ||
            !nodes[binding.sceneNode].alive || !nodes[binding.sceneNode].active)) continue;
        if (stepTotalSteps_>=MaxTotalSteps) {
            recordIssue(GraphVmError::TotalStepLimit,binding.graph,0);
            break;
        }
        dispatchBinding(
            binding,dispatch,dt,tick,input,nodes,
            static_cast<std::int32_t>(sensor),static_cast<std::int32_t>(player),stepTotalSteps_
        );
    }
}

bool GraphVm::dispatchBinding(Binding& binding,Dispatch dispatch,float dt,std::uint64_t tick,
                              const GraphInputFrame& input,std::vector<NodeData>& nodes,
                              std::int32_t triggerSensor,std::int32_t triggerPlayer,
                              std::size_t& totalSteps) {
    currentGraphIndex_=binding.graph; currentGraph_=&graphs_[binding.graph]; currentBound_=binding.sceneNode;
    currentTriggerSensor_=triggerSensor; currentTriggerPlayer_=triggerPlayer;
    currentNodes_=&nodes; currentInput_=&input; currentDt_=dt; currentTick_=tick;
    currentSteps_=0; currentLimit_=currentGraph_->maxSteps; currentTotalSteps_=&totalSteps;
    currentError_=GraphVmError::None; currentErrorNode_=0;
    if (++dispatchStamp_==0) { std::fill(executedStamp_.begin(),executedStamp_.end(),0); dispatchStamp_=1; }
    std::size_t head=0,tail=0;
    for (std::uint16_t local=0;local<currentGraph_->nodeCount;++local) {
        const auto opcode=nodes_[currentGraph_->nodeStart+local].opcode;
        const bool root=
            dispatch==Dispatch::Ready?opcode==1:
            dispatch==Dispatch::Tick?(opcode==2 || opcode==3):
            dispatch==Dispatch::TriggerEnter?opcode==19:opcode==20;
        if (!root) continue;
        if (tail>=queue_.size()) { fail(GraphVmError::QueueLimit,local); break; }
        queue_[tail++]=local;
    }
    while (currentError_==GraphVmError::None && head<tail) {
        const auto local=queue_[head++];
        if (++evaluationStamp_==0) { std::fill(dataStamp_.begin(),dataStamp_.end(),0); evaluationStamp_=1; }
        std::uint8_t flowMask=0;
        if (!executeNode(local,true,0,flowMask)) break;
        executedStamp_[local]=dispatchStamp_;
        const auto& node=nodes_[currentGraph_->nodeStart+local];
        auto append=[&](std::uint32_t start,std::uint16_t count) {
            for (std::uint16_t i=0;i<count;++i) {
                if (tail>=queue_.size()) { fail(GraphVmError::QueueLimit,local); return; }
                queue_[tail++]=flows_[start+i];
            }
        };
        if (flowMask&1u) append(node.flowStart,node.flowZero);
        if (currentError_==GraphVmError::None && (flowMask&2u)) append(node.flowStart+node.flowZero,node.flowOne);
    }
    if (currentError_!=GraphVmError::None) {
        binding.enabled=false; recordIssue(currentError_,binding.graph,currentErrorNode_); return false;
    }
    return true;
}

bool GraphVm::consumeStep(std::uint16_t node) {
    if (currentSteps_>=currentLimit_) return fail(GraphVmError::StepLimit,node);
    if (!currentTotalSteps_ || *currentTotalSteps_>=MaxTotalSteps) return fail(GraphVmError::TotalStepLimit,node);
    ++currentSteps_; ++*currentTotalSteps_; return true;
}

bool GraphVm::fail(GraphVmError error,std::uint16_t node) {
    if (currentError_==GraphVmError::None) { currentError_=error; currentErrorNode_=node; }
    return false;
}

void GraphVm::recordIssue(GraphVmError error,std::uint32_t graph,std::uint16_t node) {
    if (issueCount_<issues_.size()) issues_[issueCount_++]={error,graph,node};
}

void GraphVm::resetOutput(std::uint16_t local) {
    outputs_[local]={Value{},Value{},Value{}};
}

bool GraphVm::pureData(std::uint8_t opcode) const { return (opcode>=5 && opcode<=12) || opcode==21 || opcode==22; }

bool GraphVm::resolveInput(std::uint32_t token,std::size_t depth,std::uint16_t owner,Value& result) {
    const auto kind=token>>30;
    const auto payload=static_cast<std::uint16_t>(token&0xffffu);
    const auto output=(token>>16)&0xffu;
    if (kind==0) { result=values_[payload]; return true; }
    if (kind!=1) return fail(GraphVmError::TypeMismatch,owner);
    if (executedStamp_[payload]!=dispatchStamp_) {
        const auto opcode=nodes_[currentGraph_->nodeStart+payload].opcode;
        if (!pureData(opcode)) return fail(GraphVmError::MissingSource,owner);
        if (!evaluateData(payload,depth+1)) return false;
    }
    result=outputs_[payload][output]; return true;
}

bool GraphVm::evaluateData(std::uint16_t local,std::size_t depth) {
    if (depth>MaxDataDepth) return fail(GraphVmError::DataDepth,local);
    if (dataStamp_[local]==evaluationStamp_) return true;
    std::uint8_t ignored=0;
    if (!executeNode(local,false,depth,ignored)) return false;
    dataStamp_[local]=evaluationStamp_; return true;
}

bool GraphVm::stringValue(const Value& value,std::string_view& result) const {
    if (value.tag!=ValueTag::String || value.index>=strings_.size()) return false;
    result=strings_[value.index]; return true;
}

bool GraphVm::numberValue(const Value& value,float& result) const {
    if (value.tag!=ValueTag::Number) return false;
    result=value.number; return true;
}

bool GraphVm::boolValue(const Value& value,bool& result) const {
    if (value.tag!=ValueTag::Boolean) return false;
    result=value.index!=0; return true;
}

std::int32_t GraphVm::entityValue(const Value& value,bool emptyUsesBound) const {
    const auto boundEntity=[&]() -> std::int32_t {
        return currentBound_==WorldBinding?-1:static_cast<std::int32_t>(currentBound_);
    };
    if (value.tag==ValueTag::Null) return emptyUsesBound?boundEntity():-1;
    if (value.tag==ValueTag::Entity) return value.index<currentNodes_->size()?static_cast<std::int32_t>(value.index):-2;
    if (value.tag!=ValueTag::String || value.index>=strings_.size()) return -2;
    const auto& id=strings_[value.index];
    if (id.empty()) return emptyUsesBound?boundEntity():-1;
    for (std::size_t i=0;i<currentNodes_->size();++i) if ((*currentNodes_)[i].id==id) return static_cast<std::int32_t>(i);
    return -2;
}

GraphVm::StateSlot* GraphVm::stateSlot(std::uint32_t key) {
    for (auto& slot:state_) if (slot.key==key) return &slot;
    return nullptr;
}

bool GraphVm::readComponent(std::int32_t entity,std::string_view component,std::string_view field,Value& result) {
    if (entity<0 || static_cast<std::size_t>(entity)>=currentNodes_->size()) return false;
    const auto& node=(*currentNodes_)[static_cast<std::size_t>(entity)];
    auto number=[&](float value) { result={}; result.tag=ValueTag::Number; result.number=value; return true; };
    auto vector3=[&](const Vec3& value) { result={}; result.tag=ValueTag::Vec3; result.vector={value.x,value.y,value.z,0}; return true; };
    if (component=="alive" && field.empty()) { result={}; result.tag=ValueTag::Boolean; result.index=node.alive?1u:0u; return true; }
    if (component=="active" && field.empty()) { result={}; result.tag=ValueTag::Boolean; result.index=node.active?1u:0u; return true; }
    if (component=="velocity" || component=="angular_velocity") {
        const auto& value=component=="velocity"?node.velocity:node.angularVelocity;
        if (field.empty()) return vector3(value);
        int index=0; return fieldIndex3(field,index)?number(vec3At(value,index)):false;
    }
    if (component!="transform") return false;
    if (field=="position" || field=="translation") return vector3(node.translation);
    if (field=="scale") return vector3(node.scale);
    if (field=="rotation") {
        result={}; result.tag=ValueTag::Vec4;
        result.vector={node.rotation.w,node.rotation.x,node.rotation.y,node.rotation.z}; return true;
    }
    const auto dot=field.find('.'); if (dot==std::string_view::npos) return false;
    const auto group=field.substr(0,dot),part=field.substr(dot+1); int index=0;
    if ((group=="position" || group=="translation") && fieldIndex3(part,index)) return number(vec3At(node.translation,index));
    if (group=="scale" && fieldIndex3(part,index)) return number(vec3At(node.scale,index));
    if (group=="rotation" && fieldIndex4(part,index)) return number(quatAt(node.rotation,index));
    return false;
}

bool GraphVm::writeComponent(std::int32_t entity,std::string_view component,std::string_view field,const Value& value) {
    if (entity<0 || static_cast<std::size_t>(entity)>=currentNodes_->size()) return false;
    auto& node=(*currentNodes_)[static_cast<std::size_t>(entity)];
    if ((component=="alive" || component=="active") && field.empty()) {
        bool item=false; if (!boolValue(value,item)) return false;
        if (component=="alive") node.alive=item; else node.active=item; return true;
    }
    if (component=="velocity" || component=="angular_velocity") {
        auto& target=component=="velocity"?node.velocity:node.angularVelocity;
        if (field.empty()) {
            if (value.tag!=ValueTag::Vec3) return false;
            target={value.vector[0],value.vector[1],value.vector[2]}; return true;
        }
        int index=0; float item=0;
        if (!fieldIndex3(field,index) || !numberValue(value,item)) return false;
        setVec3At(target,index,item); return true;
    }
    if (component!="transform") return false;
    auto setVec=[&](Vec3& target) {
        if (value.tag!=ValueTag::Vec3) return false;
        target={value.vector[0],value.vector[1],value.vector[2]}; return true;
    };
    if (field=="position" || field=="translation") return setVec(node.translation);
    if (field=="scale") {
        if (value.tag!=ValueTag::Vec3 || std::abs(value.vector[0])<=1.0e-8f ||
            std::abs(value.vector[1])<=1.0e-8f || std::abs(value.vector[2])<=1.0e-8f) return false;
        node.scale={value.vector[0],value.vector[1],value.vector[2]}; return true;
    }
    if (field=="rotation") {
        if (value.tag!=ValueTag::Vec4) return false;
        const Quat q{value.vector[0],value.vector[1],value.vector[2],value.vector[3]};
        const float magnitude=std::sqrt(q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z);
        if (!std::isfinite(magnitude) || magnitude<1.0e-6f) return false;
        node.rotation=normalize(q); return true;
    }
    const auto dot=field.find('.'); if (dot==std::string_view::npos) return false;
    const auto group=field.substr(0,dot),part=field.substr(dot+1); int index=0; float item=0;
    if (!numberValue(value,item)) return false;
    if ((group=="position" || group=="translation") && fieldIndex3(part,index)) { setVec3At(node.translation,index,item); return true; }
    if (group=="scale" && fieldIndex3(part,index)) {
        if (std::abs(item)<=1.0e-8f) return false;
        setVec3At(node.scale,index,item); return true;
    }
    if (group=="rotation" && fieldIndex4(part,index)) {
        auto q=node.rotation; setQuatAt(q,index,item);
        const float magnitude=std::sqrt(q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z);
        if (!std::isfinite(magnitude) || magnitude<1.0e-6f) return false;
        node.rotation=normalize(q); return true;
    }
    return false;
}

bool GraphVm::equalValues(const Value& a,const Value& b) const {
    if (a.tag==ValueTag::Entity && b.tag==ValueTag::String && a.index<currentNodes_->size() && b.index<strings_.size())
        return (*currentNodes_)[a.index].id==strings_[b.index];
    if (b.tag==ValueTag::Entity && a.tag==ValueTag::String) return equalValues(b,a);
    if (a.tag!=b.tag) return false;
    switch (a.tag) {
        case ValueTag::Null: return true;
        case ValueTag::Boolean: case ValueTag::String: case ValueTag::Entity: return a.index==b.index;
        case ValueTag::Number: return a.number==b.number;
        case ValueTag::Vec2: return a.vector[0]==b.vector[0] && a.vector[1]==b.vector[1];
        case ValueTag::Vec3: return a.vector[0]==b.vector[0] && a.vector[1]==b.vector[1] && a.vector[2]==b.vector[2];
        case ValueTag::Vec4: return a.vector==b.vector;
    }
    return false;
}

bool GraphVm::orderedCompare(const Value& a,const Value& b,int& comparison) const {
    if (a.tag!=b.tag) return false;
    if (a.tag==ValueTag::Number) comparison=a.number<b.number?-1:(a.number>b.number?1:0);
    else if (a.tag==ValueTag::String) comparison=strings_[a.index]<strings_[b.index]?-1:(strings_[a.index]>strings_[b.index]?1:0);
    else if (a.tag==ValueTag::Boolean) comparison=a.index<b.index?-1:(a.index>b.index?1:0);
    else return false;
    return true;
}

float GraphVm::inputValue(std::string_view action,const GraphInputState& input) const {
    if (action=="jump" || action=="accept" || action=="ui_accept") return input.jump?1.0f:0.0f;
    if (action=="dash" || action=="action" || action=="cancel" || action=="ui_cancel") return input.dash?1.0f:0.0f;
    if (action=="move_x") return input.moveX;
    if (action=="move_z") return input.moveZ;
    if (action=="look_x") return input.lookX;
    if (action=="look_y") return input.lookY;
    if (action=="move_left" || action=="left") return std::max(0.0f,-input.moveX);
    if (action=="move_right" || action=="right") return std::max(0.0f,input.moveX);
    if (action=="move_forward" || action=="move_up" || action=="up") return std::max(0.0f,-input.moveZ);
    if (action=="move_back" || action=="move_down" || action=="down") return std::max(0.0f,input.moveZ);
    return 0.0f;
}

bool GraphVm::inputPressed(std::string_view action) const {
    return std::abs(inputValue(action,currentInput_->current))>=0.5f &&
           std::abs(inputValue(action,currentInput_->previous))<0.5f;
}

bool GraphVm::executeNode(std::uint16_t local,bool queued,std::size_t depth,std::uint8_t& flowMask) {
    (void)queued;
    if (depth>MaxDataDepth) return fail(GraphVmError::DataDepth,local);
    if (!consumeStep(local)) return false;
    const auto& node=nodes_[currentGraph_->nodeStart+local];
    std::array<Value,4> input{};
    for (std::uint16_t i=0;i<node.inputCount;++i)
        if (!resolveInput(inputs_[node.inputStart+i],depth,local,input[i])) return false;
    resetOutput(local); flowMask=0;
    auto& output=outputs_[local];
    auto number=[](float value) { Value result; result.tag=ValueTag::Number; result.number=value; return result; };
    auto boolean=[](bool value) { Value result; result.tag=ValueTag::Boolean; result.index=value?1u:0u; return result; };
    auto entity=[&]() {
        Value result;
        if (currentBound_!=WorldBinding) { result.tag=ValueTag::Entity; result.index=currentBound_; }
        return result;
    };
    auto indexedEntity=[](std::int32_t index) {
        Value result;
        if (index>=0) { result.tag=ValueTag::Entity; result.index=static_cast<std::uint32_t>(index); }
        return result;
    };
    switch (node.opcode) {
        case 1: output[0]=entity(); flowMask=1; return true;
        case 2: output[0]=number(currentDt_); output[1]=number(static_cast<float>(currentTick_)); output[2]=entity(); flowMask=1; return true;
        case 3: {
            std::string_view action; if (!stringValue(input[0],action)) return fail(GraphVmError::TypeMismatch,local);
            output[0]=input[0]; output[1]=number(inputValue(action,currentInput_->current)); output[2]=entity();
            flowMask=inputPressed(action)?1u:0u; return true;
        }
        case 4: {
            bool condition=false; if (!boolValue(input[0],condition)) return fail(GraphVmError::TypeMismatch,local);
            flowMask=condition?1u:2u; return true;
        }
        case 5: output[0]=input[0]; return true;
        case 6: {
            if (input[0].tag!=ValueTag::String) return fail(GraphVmError::TypeMismatch,local);
            const auto* slot=stateSlot(input[0].index); if (!slot) return fail(GraphVmError::MissingState,local);
            output[0]=slot->set?slot->value:input[1]; return true;
        }
        case 7: {
            const auto resolved=entityValue(input[0],true); std::string_view component,field;
            if (resolved<0) return fail(GraphVmError::InvalidEntity,local);
            if (!stringValue(input[1],component) || !stringValue(input[2],field)) return fail(GraphVmError::TypeMismatch,local);
            if (!readComponent(resolved,component,field,output[0])) output[0]=input[3];
            return true;
        }
        case 8: case 9: case 10: case 11: {
            float a=0,b=0; if (!numberValue(input[0],a) || !numberValue(input[1],b)) return fail(GraphVmError::TypeMismatch,local);
            float result=0;
            if (node.opcode==8) result=a+b; else if (node.opcode==9) result=a-b;
            else if (node.opcode==10) result=a*b;
            else { if (b==0.0f) return fail(GraphVmError::DivideByZero,local); result=a/b; }
            if (!std::isfinite(result)) return fail(GraphVmError::NonFinite,local);
            output[0]=number(result); return true;
        }
        case 12: {
            std::string_view operation; if (!stringValue(input[2],operation)) return fail(GraphVmError::TypeMismatch,local);
            bool result=false;
            if (operation=="equal") result=equalValues(input[0],input[1]);
            else if (operation=="not_equal") result=!equalValues(input[0],input[1]);
            else {
                int comparison=0; if (!orderedCompare(input[0],input[1],comparison)) return fail(GraphVmError::InvalidCompare,local);
                if (operation=="less") result=comparison<0;
                else if (operation=="less_equal") result=comparison<=0;
                else if (operation=="greater") result=comparison>0;
                else if (operation=="greater_equal") result=comparison>=0;
                else return fail(GraphVmError::InvalidCompare,local);
            }
            output[0]=boolean(result); return true;
        }
        case 13: {
            if (input[0].tag!=ValueTag::String) return fail(GraphVmError::TypeMismatch,local);
            auto* slot=stateSlot(input[0].index); if (!slot) return fail(GraphVmError::MissingState,local);
            slot->value=input[1]; slot->set=true; flowMask=1; return true;
        }
        case 14: {
            const auto resolved=entityValue(input[0],true); std::string_view component,field;
            if (resolved<0) return fail(GraphVmError::InvalidEntity,local);
            if (!stringValue(input[1],component) || !stringValue(input[2],field)) return fail(GraphVmError::TypeMismatch,local);
            if (!writeComponent(resolved,component,field,input[3])) return fail(GraphVmError::InvalidComponent,local);
            flowMask=1; return true;
        }
        case 15: {
            std::string_view kind; if (!stringValue(input[0],kind)) return fail(GraphVmError::TypeMismatch,local);
            const auto source=entityValue(input[1],true),target=entityValue(input[2],false);
            if (source<-1 || target<-1) return fail(GraphVmError::InvalidEntity,local);
            if (eventCount_>=events_.size()) return fail(GraphVmError::EventLimit,local);
            events_[eventCount_++]={kind,source,target}; output[0]=Value{}; flowMask=1; return true;
        }
        case 16: {
            const auto resolved=entityValue(input[0],true); bool active=false;
            if (resolved<0) return fail(GraphVmError::InvalidEntity,local);
            if (!boolValue(input[1],active)) return fail(GraphVmError::TypeMismatch,local);
            (*currentNodes_)[static_cast<std::size_t>(resolved)].active=active; flowMask=1; return true;
        }
        case 17: {
            const auto resolved=entityValue(input[0],true); if (resolved<0) return fail(GraphVmError::InvalidEntity,local);
            auto& target=(*currentNodes_)[static_cast<std::size_t>(resolved)]; target.alive=false; target.active=false;
            flowMask=1; return true;
        }
        case 18: {
            const auto resolved=entityValue(input[0],true); if (resolved<0) return fail(GraphVmError::InvalidEntity,local);
            auto& target=(*currentNodes_)[static_cast<std::size_t>(resolved)];
            if (input[1].tag!=ValueTag::Vec2 && input[1].tag!=ValueTag::Vec3)
                return fail(GraphVmError::TypeMismatch,local);
            if (!target.dynamic || !std::isfinite(target.mass) || target.mass<=0.0f) { flowMask=1; return true; }
            const float inverseMass=1.0f/target.mass;
            const Vec3 force=input[1].tag==ValueTag::Vec2
                ?Vec3{input[1].vector[0],0.0f,input[1].vector[1]}
                :Vec3{input[1].vector[0],input[1].vector[1],input[1].vector[2]};
            target.velocity=target.velocity+force*inverseMass;
            flowMask=1; return true;
        }
        case 19: case 20:
            output[0]=indexedEntity(currentTriggerSensor_);
            output[1]=indexedEntity(currentTriggerPlayer_);
            output[2]=entity();
            flowMask=1;
            return true;
        case 21: {
            float world=0.0f,pick=0.0f,smallest=0.0f,largest=0.0f;
            if (!numberValue(input[0],world) || !numberValue(input[1],pick) ||
                !numberValue(input[2],smallest) || !numberValue(input[3],largest))
                return fail(GraphVmError::TypeMismatch,local);
            const auto validIndex=[](float value) {
                return std::isfinite(value) && value>=0.0f && value<=65535.0f &&
                    std::trunc(value)==value;
            };
            if (!validIndex(world) || !validIndex(pick))
                return fail(GraphVmError::InvalidSeedNumber,local);
            if (smallest>largest) return fail(GraphVmError::InvalidSeedRange,local);
            constexpr std::uint64_t Namespace=0x7f1400acd2ebb3aeull;
            const auto lineage=scatterStableId(
                static_cast<std::uint64_t>(world),Namespace,static_cast<std::uint64_t>(pick)
            );
            const float unit=scatterSeedUnitFloat(lineage);
            const double span=static_cast<double>(largest)-static_cast<double>(smallest);
            volatile const double scaled=static_cast<double>(unit)*span;
            const float result=static_cast<float>(static_cast<double>(smallest)+scaled);
            if (!std::isfinite(result)) return fail(GraphVmError::NonFinite,local);
            output[0]=number(result);
            return true;
        }
        case 22: {
            const auto origin=entityValue(input[0],true);
            if (origin<0) return fail(GraphVmError::InvalidEntity,local);
            std::string_view tag;
            if (!stringValue(input[1],tag)) return fail(GraphVmError::TypeMismatch,local);
            std::uint32_t tagMask=0;
            if (!portableTagMask(tag,tagMask)) return fail(GraphVmError::InvalidSpatialTag,local);
            float radius=0.0f;
            if (!numberValue(input[2],radius)) return fail(GraphVmError::TypeMismatch,local);
            const float radiusSquared=roundedFloat(radius*radius);
            if (!std::isfinite(radius) || radius<0.0f || !std::isfinite(radiusSquared))
                return fail(GraphVmError::InvalidSearchRadius,local);
            const auto originIndex=static_cast<std::size_t>(origin);
            const auto& originNode=(*currentNodes_)[originIndex];
            if (!finiteVec3(originNode.translation)) return fail(GraphVmError::InvalidEntity,local);

            std::uint32_t best=std::numeric_limits<std::uint32_t>::max();
            float bestSquared=0.0f;
            for (std::uint32_t index=0;index<currentNodes_->size();++index) {
                if (index==originIndex) continue;
                const auto& candidate=(*currentNodes_)[index];
                if (!candidate.alive || !candidate.active || !(candidate.tagMask&tagMask)) continue;
                if (!finiteVec3(candidate.translation)) return fail(GraphVmError::NonFinite,local);
                const float dx=roundedFloat(candidate.translation.x-originNode.translation.x);
                const float dy=roundedFloat(candidate.translation.y-originNode.translation.y);
                const float dz=roundedFloat(candidate.translation.z-originNode.translation.z);
                const float xx=roundedFloat(dx*dx);
                const float yy=roundedFloat(dy*dy);
                const float zz=roundedFloat(dz*dz);
                float squared=roundedFloat(xx+yy);
                squared=roundedFloat(squared+zz);
                if (!std::isfinite(squared)) return fail(GraphVmError::NonFinite,local);
                if (squared>radiusSquared) continue;
                if (best==std::numeric_limits<std::uint32_t>::max() || squared<bestSquared ||
                    (squared==bestSquared && utf8Less(candidate.id,(*currentNodes_)[best].id))) {
                    best=index;
                    bestSquared=squared;
                }
            }
            output[0]=boolean(best!=std::numeric_limits<std::uint32_t>::max());
            if (best!=std::numeric_limits<std::uint32_t>::max()) {
                output[1]=indexedEntity(static_cast<std::int32_t>(best));
                const float distance=roundedFloat(std::sqrt(bestSquared));
                if (!std::isfinite(distance)) return fail(GraphVmError::NonFinite,local);
                output[2]=number(distance);
            }
            return true;
        }
        default: return fail(GraphVmError::TypeMismatch,local);
    }
}

} // namespace kc
