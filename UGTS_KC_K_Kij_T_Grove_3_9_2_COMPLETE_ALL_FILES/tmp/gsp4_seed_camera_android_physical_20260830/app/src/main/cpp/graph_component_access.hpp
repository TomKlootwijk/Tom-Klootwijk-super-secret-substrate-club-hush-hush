#pragma once
#include <cstdint>
#include <string_view>
#include <vector>

namespace kc {

struct NodeData;

// Optional bridge for compact or virtual numeric ECS components. GraphVm owns
// neither the implementation nor its storage, keeping ordinary host VM builds
// independent from every specialized runtime component.
class GraphNumberComponentAccess {
public:
    virtual ~GraphNumberComponentAccess() = default;
    virtual bool readGraphNumber(
        std::uint32_t sceneNode,std::string_view component,std::string_view field,
        float& value
    ) const = 0;
    virtual bool writeGraphNumber(
        std::uint32_t sceneNode,std::string_view component,std::string_view field,
        float value,std::vector<NodeData>& nodes
    ) = 0;
    // Specialized storage may own ordinary fields whose generic writes would
    // otherwise create two conflicting authorities. Default keeps existing
    // dependency-free GraphVm hosts unchanged.
    virtual bool rejectsGraphWrite(
        std::uint32_t,std::string_view,std::string_view
    ) const { return false; }
};

} // namespace kc
