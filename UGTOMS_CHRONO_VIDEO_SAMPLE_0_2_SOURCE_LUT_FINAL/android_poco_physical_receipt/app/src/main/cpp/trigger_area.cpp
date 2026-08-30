#include "trigger_area.hpp"
#include <algorithm>
#include <cmath>

namespace kc {
namespace {

bool finite(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

float sphereRadius(const NodeData& node) {
    const float scale=std::max({std::abs(node.scale.x),std::abs(node.scale.y),std::abs(node.scale.z)});
    return node.collider.radius*scale;
}

Vec3 boxExtents(const NodeData& node) {
    return {
        node.collider.halfExtents.x*std::abs(node.scale.x),
        node.collider.halfExtents.y*std::abs(node.scale.y),
        node.collider.halfExtents.z*std::abs(node.scale.z),
    };
}

bool sphereSphere(const NodeData& a,const NodeData& b) {
    const float radius=sphereRadius(a)+sphereRadius(b);
    const Vec3 delta=a.translation-b.translation;
    return radius>0.0f && dot(delta,delta)<=radius*radius;
}

bool boxBox(const NodeData& a,const NodeData& b) {
    const Vec3 first=boxExtents(a),second=boxExtents(b),delta=a.translation-b.translation;
    return first.x>0.0f && first.y>0.0f && first.z>0.0f &&
           second.x>0.0f && second.y>0.0f && second.z>0.0f &&
           std::abs(delta.x)<=first.x+second.x &&
           std::abs(delta.y)<=first.y+second.y &&
           std::abs(delta.z)<=first.z+second.z;
}

bool sphereBox(const NodeData& sphere,const NodeData& box) {
    const float radius=sphereRadius(sphere);
    const Vec3 extent=boxExtents(box);
    if (radius<=0.0f || extent.x<=0.0f || extent.y<=0.0f || extent.z<=0.0f) return false;
    const Vec3 delta=sphere.translation-box.translation;
    const Vec3 nearest{
        clamp(delta.x,-extent.x,extent.x),
        clamp(delta.y,-extent.y,extent.y),
        clamp(delta.z,-extent.z,extent.z),
    };
    const Vec3 remainder=delta-nearest;
    return dot(remainder,remainder)<=radius*radius;
}

} // namespace

bool triggerAreaOverlap(const NodeData& sensor,const NodeData& player) {
    if (!sensor.alive || !sensor.active || !sensor.collider.sensor ||
        !player.alive || !player.active || !(player.tagMask&TagPlayer) ||
        sensor.collider.type==0 || player.collider.type==0 ||
        sensor.collider.type>2 || player.collider.type>2 ||
        !finite(sensor.translation) || !finite(sensor.scale) ||
        !finite(player.translation) || !finite(player.scale)) return false;
    if (sensor.collider.type==1 && player.collider.type==1) return sphereSphere(sensor,player);
    if (sensor.collider.type==2 && player.collider.type==2) return boxBox(sensor,player);
    return sensor.collider.type==1?sphereBox(sensor,player):sphereBox(player,sensor);
}

std::span<const TriggerAreaEvent> TriggerAreaTracker::update(const std::vector<NodeData>& nodes) {
    current_.clear();
    events_.clear();
    sensorLimitReached_=false;

    std::size_t playerIndex=nodes.size();
    for (std::size_t index=0;index<nodes.size();++index) {
        const auto& node=nodes[index];
        if (node.alive && node.active && (node.tagMask&TagPlayer)) {
            playerIndex=index;
            break;
        }
    }

    if (playerIndex<nodes.size()) {
        std::size_t sensors=0;
        current_.reserve(std::min(MaxSensors,nodes.size()));
        for (std::size_t index=0;index<nodes.size();++index) {
            const auto& node=nodes[index];
            if (index==playerIndex || !node.alive || !node.active ||
                !node.collider.sensor || node.collider.type==0) continue;
            if (sensors>=MaxSensors) {
                sensorLimitReached_=true;
                break;
            }
            ++sensors;
            if (triggerAreaOverlap(node,nodes[playerIndex])) {
                current_.push_back({static_cast<std::uint32_t>(index),static_cast<std::uint32_t>(playerIndex)});
            }
        }
    }

    events_.reserve(std::min(MaxEvents,active_.size()+current_.size()));
    const auto less=[](const Contact& first,const Contact& second) {
        return first.sensor<second.sensor ||
               (first.sensor==second.sensor && first.player<second.player);
    };
    for (const auto& contact:active_) {
        if (!std::binary_search(current_.begin(),current_.end(),contact,less) && events_.size()<MaxEvents) {
            events_.push_back({TriggerTransition::Exit,contact.sensor,contact.player});
        }
    }
    for (const auto& contact:current_) {
        if (!std::binary_search(active_.begin(),active_.end(),contact,less) && events_.size()<MaxEvents) {
            events_.push_back({TriggerTransition::Enter,contact.sensor,contact.player});
        }
    }
    active_.swap(current_);
    return events_;
}

void TriggerAreaTracker::clear() {
    active_.clear();
    current_.clear();
    events_.clear();
    sensorLimitReached_=false;
}

} // namespace kc
