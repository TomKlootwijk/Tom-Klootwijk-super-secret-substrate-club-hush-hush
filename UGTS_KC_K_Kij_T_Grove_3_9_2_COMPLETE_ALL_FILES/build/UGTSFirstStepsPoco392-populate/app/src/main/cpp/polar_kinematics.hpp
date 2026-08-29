#pragma once
#include "scene_pack.hpp"
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace kc {

// Sparse optional ECS storage for the two-u64 log-polar component.  Scene
// nodes without a packed component remain plain NodeData records.
class PackedPolarKinematics {
public:
    void clear();
    void load(const std::vector<std::uint8_t>& bytes,const std::vector<NodeData>& nodes);
    void compose(std::vector<NodeData>& nodes) const;
    void tick(float dt,std::vector<NodeData>& nodes);
    std::size_t profileCount() const { return profiles_.size(); }
    std::size_t componentCount() const { return components_.size(); }
    // Public only so the dependency-free decoder helpers can remain ordinary
    // translation-unit functions; engine code should treat these as opaque.
    struct Profile {
        std::string id;
        double r0=1.0,rhoMin=-12.0,rhoMax=12.0,coreRadius=1.0e-6;
        double rhoVelocity=16.0,thetaVelocity=32.0;
        double rhoAcceleration=64.0,thetaAcceleration=128.0;
        std::vector<float> sine,cosine,radii;
    };
    struct Component {
        std::uint32_t sceneNode=0;
        std::uint16_t profile=0;
        std::uint64_t pose=0,motion=0;
    };
private:
    void compose(Component const& component,std::vector<NodeData>& nodes) const;
    std::vector<Profile> profiles_;
    std::vector<Component> components_;
};

} // namespace kc
