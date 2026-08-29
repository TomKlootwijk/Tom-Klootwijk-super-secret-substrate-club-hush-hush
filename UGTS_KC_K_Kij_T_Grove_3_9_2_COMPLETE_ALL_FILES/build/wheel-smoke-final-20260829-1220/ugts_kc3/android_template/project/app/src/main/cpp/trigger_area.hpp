#pragma once
#include "scene_pack.hpp"
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace kc {

enum class TriggerTransition : std::uint8_t {
    Enter,
    Exit,
};

struct TriggerAreaEvent {
    TriggerTransition transition=TriggerTransition::Enter;
    std::uint32_t sensor=0;
    std::uint32_t player=0;
};

// Trigger volumes deliberately remain translation/scale aligned. This keeps
// the beginner runtime dependency-free while using the authored sphere radius
// and box half-extents instead of a single loose bounding sphere.
bool triggerAreaOverlap(const NodeData& sensor,const NodeData& player);

class TriggerAreaTracker {
public:
    static constexpr std::size_t MaxSensors=4096;
    static constexpr std::size_t MaxEvents=MaxSensors*2;

    std::span<const TriggerAreaEvent> update(const std::vector<NodeData>& nodes);
    void clear();
    bool sensorLimitReached() const { return sensorLimitReached_; }

private:
    struct Contact {
        std::uint32_t sensor=0;
        std::uint32_t player=0;

        friend bool operator==(const Contact&,const Contact&)=default;
    };

    std::vector<Contact> active_;
    std::vector<Contact> current_;
    std::vector<TriggerAreaEvent> events_;
    bool sensorLimitReached_=false;
};

} // namespace kc
