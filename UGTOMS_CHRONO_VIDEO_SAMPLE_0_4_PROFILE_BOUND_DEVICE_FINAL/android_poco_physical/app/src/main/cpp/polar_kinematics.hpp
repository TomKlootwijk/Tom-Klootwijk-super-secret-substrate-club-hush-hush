#pragma once
#include "graph_component_access.hpp"
#include "scene_pack.hpp"
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace kc {

// Sparse optional ECS storage for the two-u64 log-polar component.  Scene
// nodes without a packed component remain plain NodeData records.
class PackedPolarKinematics final : public GraphNumberComponentAccess {
public:
    struct Component;
    struct PolarChartSample {
        float normalizedRho=0.0f;
        float directionX=1.0f,directionY=0.0f;
    };
    void clear();
    void load(const std::vector<std::uint8_t>& bytes,const std::vector<NodeData>& nodes);
    void compose(std::vector<NodeData>& nodes) const;
    bool composeSceneNode(std::uint32_t sceneNode,std::vector<NodeData>& nodes) const;
    void tick(float dt,std::vector<NodeData>& nodes);
    void snapPreviousToCurrent();
    const Component* componentForSceneNode(std::uint32_t sceneNode) const;
    std::uint64_t offsetPoseCodes(
        std::uint16_t profile,std::uint64_t pose,
        float rhoOffset,std::uint32_t thetaOffsetCode,
        std::uint16_t headingOffsetCode
    ) const;
    std::uint64_t makeDisplayPose(
        std::uint16_t profile,float rho,std::uint32_t thetaCode,
        std::uint16_t headingCode,std::uint16_t tickCode
    ) const;
    PolarChartSample samplePoseChart(
        std::uint16_t profile,std::uint64_t pose
    ) const;
    void composePose(
        std::uint16_t profile,std::uint64_t pose,std::uint64_t motion,
        NodeData& node,PolarChartSample* chartSample=nullptr
    ) const;
    void composeLocalPose(
        std::uint16_t profile,std::uint64_t anchorPose,
        std::uint64_t localPose,NodeData& node,
        PolarChartSample* chartSample=nullptr
    ) const;
    std::size_t profileCount() const { return profiles_.size(); }
    std::size_t componentCount() const { return components_.size(); }
    bool readGraphNumber(
        std::uint32_t sceneNode,std::string_view component,std::string_view field,
        float& value
    ) const override;
    bool writeGraphNumber(
        std::uint32_t sceneNode,std::string_view component,std::string_view field,
        float value,std::vector<NodeData>& nodes
    ) override;
    bool rejectsGraphWrite(
        std::uint32_t sceneNode,std::string_view component,std::string_view field
    ) const override;
    // Public only so the dependency-free decoder helpers can remain ordinary
    // translation-unit functions; engine code should treat these as opaque.
    struct Profile {
        std::string id;
        double r0=1.0,rhoMin=-12.0,rhoMax=12.0,coreRadius=1.0e-6;
        double rhoVelocity=16.0,thetaVelocity=32.0;
        double rhoAcceleration=64.0,thetaAcceleration=128.0;
        double authoredRadiusScale=1.0;
        float radiusScale=1.0f;
        std::vector<float> sine,cosine,radii,normalizedRadii;
        // Exact authored UGLUT2 binary16 lanes. GPU upload consumes these
        // directly so no float round-trip can change an authored sample.
        std::vector<std::uint16_t> sineHalf,cosineHalf,normalizedRadiusHalf;
    };
    struct Component {
        std::uint32_t sceneNode=0;
        std::uint16_t profile=0;
        std::uint64_t pose=0,previousPose=0,motion=0;
    };
    const std::vector<Profile>& profiles() const { return profiles_; }
    const std::vector<Component>& components() const { return components_; }
private:
    Component* find(std::uint32_t sceneNode);
    const Component* find(std::uint32_t sceneNode) const;
    void compose(Component const& component,std::vector<NodeData>& nodes) const;
    std::vector<Profile> profiles_;
    std::vector<Component> components_;
};

} // namespace kc
