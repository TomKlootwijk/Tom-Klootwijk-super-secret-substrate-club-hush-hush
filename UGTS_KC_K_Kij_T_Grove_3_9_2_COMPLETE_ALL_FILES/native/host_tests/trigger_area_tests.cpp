#include "trigger_area.hpp"

#include <iostream>
#include <string_view>
#include <vector>

namespace {

int fail(std::string_view message) {
    std::cerr << "FAIL trigger areas: " << message << '\n';
    return 1;
}

kc::NodeData player() {
    kc::NodeData node;
    node.id="player";
    node.tagMask=kc::TagPlayer;
    node.collider.type=1;
    node.collider.radius=0.5f;
    node.dynamic=true;
    node.translation={0.0f,0.0f,0.0f};
    node.velocity={2.0f,3.0f,4.0f};
    return node;
}

kc::NodeData sensor(std::string_view id,kc::Vec3 position) {
    kc::NodeData node;
    node.id=id;
    node.translation=position;
    node.collider.type=2;
    node.collider.sensor=true;
    node.collider.halfExtents={0.6f,0.6f,0.6f};
    return node;
}

} // namespace

int main() {
    std::vector<kc::NodeData> nodes{player(),sensor("near",{0.9f,0.0f,0.0f}),sensor("far",{5.0f,0.0f,0.0f})};
    const auto originalVelocity=nodes[0].velocity;
    kc::TriggerAreaTracker tracker;

    auto events=tracker.update(nodes);
    if (events.size()!=1 || events[0].transition!=kc::TriggerTransition::Enter ||
        events[0].sensor!=1 || events[0].player!=0) return fail("missing first enter");
    if (nodes[0].velocity.x!=originalVelocity.x || nodes[0].velocity.y!=originalVelocity.y ||
        nodes[0].velocity.z!=originalVelocity.z) return fail("sensor changed player velocity");
    if (!tracker.update(nodes).empty()) return fail("held contact emitted twice");

    nodes[0].translation={5.0f,0.0f,0.0f};
    events=tracker.update(nodes);
    if (events.size()!=2 || events[0].transition!=kc::TriggerTransition::Exit ||
        events[0].sensor!=1 || events[1].transition!=kc::TriggerTransition::Enter ||
        events[1].sensor!=2) return fail("exit-before-enter order changed");

    nodes[2].active=false;
    events=tracker.update(nodes);
    if (events.size()!=1 || events[0].transition!=kc::TriggerTransition::Exit || events[0].sensor!=2)
        return fail("deactivation did not clean up contact");

    std::vector<kc::NodeData> crowded;
    crowded.push_back(player());
    for (std::size_t i=0;i<kc::TriggerAreaTracker::MaxSensors+1;++i)
        crowded.push_back(sensor("many",{100.0f,0.0f,0.0f}));
    tracker.clear();
    tracker.update(crowded);
    if (!tracker.sensorLimitReached()) return fail("sensor cap was not reported");

    std::cout << "PASS trigger areas\n";
    return 0;
}
