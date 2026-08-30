#pragma once
#include "polar_kinematics.hpp"
#include "scene_pack.hpp"
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace kc {

// Bounded KCPR392 render recipes. Generated members deliberately remain
// render data: they never become NodeData rows in the authoritative ECS.
class PolarPopulations {
public:
    struct Recipe {
        std::uint32_t prototypeSceneNode=0;
        std::uint16_t profile=0,preset=0,operatorMask=0;
        std::uint32_t instanceCount=0,firstGenerated=0,generatedCount=0;
        std::uint64_t seed=0;
        std::uint64_t sessionSeed=0,lineageNamespaceId=0;
        float seededPhase=0.0f,logSpan=0.0f;
        std::array<std::uint8_t,16> contentAddress{};
        std::array<std::uint8_t,16> lineageNamespace{};
        std::array<std::uint8_t,16> profileAddress{};
        std::array<std::uint8_t,16> prototypeAddress{};
        std::array<float,8> parameters{};
    };

    struct RenderCopy {
        std::uint32_t generatedIndex=0,recipeIndex=0;
        std::uint32_t prototypeSceneNode=0,instanceIndex=0;
        std::uint16_t profile=0;
        std::uint64_t lineage=0,previousPose=0,pose=0,motion=0;
        NodeData node{};
    };

    void clear();
    void load(
        const std::vector<std::uint8_t>& bytes,std::uint64_t expectedRootSeed,
        const ScenePack& scene,const PackedPolarKinematics& polar
    );
    void beginFrame() const;
    RenderCopy materialize(
        std::size_t generatedIndex,const PackedPolarKinematics& polar,
        const std::vector<NodeData>& nodes,bool composeCartesian
    ) const;
    void composeCartesian(
        RenderCopy& copy,const PackedPolarKinematics& polar
    ) const;

    std::size_t recipeCount() const { return recipes_.size(); }
    std::size_t generatedCount() const {
        return totalInstances_>=recipes_.size()
            ?static_cast<std::size_t>(totalInstances_)-recipes_.size():0u;
    }
    std::uint32_t totalInstanceCount() const { return totalInstances_; }
    std::uint64_t rootSeed() const { return rootSeed_; }
    const std::vector<Recipe>& recipes() const { return recipes_; }
    std::uint32_t recipeIndex(std::size_t generatedIndex) const;
    std::uint32_t prototypeSceneNode(std::size_t generatedIndex) const;
    std::uint16_t profile(std::size_t generatedIndex) const;
    std::size_t lastMaterializedCount() const { return lastMaterializedCount_; }
    std::size_t lastCartesianComposeCount() const {
        return lastCartesianComposeCount_;
    }

private:
    std::uint64_t rootSeed_=0;
    std::uint32_t totalInstances_=0;
    std::vector<Recipe> recipes_;
    mutable std::size_t lastMaterializedCount_=0;
    mutable std::size_t lastCartesianComposeCount_=0;
};

} // namespace kc
