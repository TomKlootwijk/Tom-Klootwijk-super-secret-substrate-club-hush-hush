#pragma once
#include "graph_render_recipe_access.hpp"
#include "polar_kinematics.hpp"
#include "scene_pack.hpp"
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace kc {

// Bounded KCPR392 render recipes. Generated members deliberately remain
// render data: they never become NodeData rows in the authoritative ECS.
class PolarPopulations final : public GraphRenderRecipeAccess {
public:
    enum class GlowDirectionMode : std::uint8_t { Direct=0, Lut=1 };

    struct GlowSample {
        std::uint16_t phase12=0;
        float pulse=0.0f,direction=0.0f,field=0.0f;
        float displayScaleMultiplier=1.0f;
    };

    struct MaterialCoordinate {
        float normalizedRho=0.0f;
        float directionX=1.0f,directionY=0.0f;
        // Negative means this ordinary draw has no KCPR material coordinate.
        float phase=-1.0f;
        bool valid() const { return phase>=0.0f; }
    };

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
        float glowCenterRho=0.0f,glowInvHalfWidth=0.0f,glowStrength=0.0f;
        bool glow=false,growCopies=false;
    };

    struct RenderCopy {
        std::uint32_t generatedIndex=0,recipeIndex=0;
        std::uint32_t prototypeSceneNode=0,instanceIndex=0;
        std::uint16_t profile=0;
        std::uint16_t glowPhase12=0;
        std::uint64_t lineage=0,previousPose=0,pose=0,motion=0;
        float burstEnvelope=1.0f,burstHeightFactor=0.0f;
        float burstScaleScalar=1.0f;
        float glowField=0.0f,displayScaleMultiplier=1.0f;
        MaterialCoordinate materialCoordinate{};
        bool burst=false;
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
    RenderCopy materialize(
        std::size_t generatedIndex,const PackedPolarKinematics& polar,
        const std::vector<NodeData>& nodes,std::uint64_t fixedTick,
        bool composeCartesian
    ) const;
    void composeCartesian(
        RenderCopy& copy,const PackedPolarKinematics& polar
    ) const;
    std::uint64_t instanceLineage(
        std::size_t recipeIndex,std::uint32_t instanceIndex
    ) const;
    std::uint16_t glowPhase12(
        std::size_t recipeIndex,std::uint32_t instanceIndex
    ) const;
    std::uint16_t materialPhase12(
        std::size_t recipeIndex,std::uint32_t instanceIndex
    ) const;
    MaterialCoordinate materialCoordinate(
        std::size_t recipeIndex,std::uint32_t instanceIndex,
        const PackedPolarKinematics::PolarChartSample& chart
    ) const;
    static float polarBandMultiplier(
        const MaterialCoordinate& coordinate,std::uint8_t bands,float strength
    );
    GlowSample evaluateGlowSample(
        std::size_t recipeIndex,std::uint32_t instanceIndex,float rho,
        std::uint32_t theta18,const PackedPolarKinematics& polar,
        GlowDirectionMode directionMode
    ) const;
    float evaluateGlow(
        std::size_t recipeIndex,std::uint32_t instanceIndex,
        std::uint64_t previousPose,std::uint64_t currentPose,float alpha,
        const PackedPolarKinematics& polar,GlowDirectionMode directionMode
    ) const;
    bool setCopiesVisible(
        std::uint32_t prototypeSceneNode,bool visible
    ) override;
    bool copiesVisible(std::size_t recipeIndex) const {
        return renderRecipeCopiesVisible(
            copiesVisibleMask_,recipes_.size(),recipeIndex
        );
    }

    std::size_t recipeCount() const { return recipes_.size(); }
    std::size_t generatedCount() const {
        return totalInstances_>=recipes_.size()
            ?static_cast<std::size_t>(totalInstances_)-recipes_.size():0u;
    }
    std::uint32_t totalInstanceCount() const { return totalInstances_; }
    std::uint32_t formatVersion() const { return formatVersion_; }
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
    std::uint32_t formatVersion_=0;
    std::uint64_t rootSeed_=0;
    std::uint32_t totalInstances_=0;
    std::vector<Recipe> recipes_;
    std::uint64_t copiesVisibleMask_=0;
    mutable std::size_t lastMaterializedCount_=0;
    mutable std::size_t lastCartesianComposeCount_=0;
};

} // namespace kc
