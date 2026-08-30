#pragma once
#include "scene_pack.hpp"
#include <cstddef>
#include <cstdint>
#include <string_view>
#include <vector>

namespace kc {

// Stable cross-pack identifier used by KCAN v2 and Play Animation graph nodes.
std::uint64_t animationClipHash(std::string_view clipId);

enum class AnimationControlResult : std::uint8_t {
    Ok,
    MissingController,
    MissingClip,
};

// Sparse optional transform-timeline storage. KCAN v1 contributes one
// autoplaying "main" clip per animated node. KCAN v2 keeps immutable clips and
// one small mutable controller per animated scene node.
class TransformAnimations {
public:
    void clear();
    void load(const std::vector<std::uint8_t>& bytes,const std::vector<NodeData>& nodes);
    void compose(std::vector<NodeData>& nodes) const;
    void tick(float dt,std::vector<NodeData>& nodes);
    AnimationControlResult play(
        std::uint32_t sceneNode,std::uint64_t clipHash,bool restart,
        std::vector<NodeData>& nodes
    );
    AnimationControlResult stop(
        std::uint32_t sceneNode,bool reset,std::vector<NodeData>& nodes
    );
    bool owns(std::uint32_t sceneNode) const;
    std::size_t bindingCount() const { return controllers_.size(); }
    std::size_t clipCount() const { return clips_.size(); }
    std::size_t keyCount() const { return keys_.size(); }

    struct Pose {
        Vec3 translation{};
        Quat rotation{};
        Vec3 scale{1.0f,1.0f,1.0f};
    };
    struct Key {
        std::uint16_t timeCode=0;
        std::uint8_t easing=0;
        Pose relative{};
    };
    struct Clip {
        std::uint32_t sceneNode=0;
        std::uint64_t hash=0;
        float duration=1.0f;
        std::uint32_t firstKey=0;
        std::uint16_t keyCount=0;
        std::uint8_t loop=0;
        bool autoplay=false;
    };
    struct Controller {
        static constexpr std::uint16_t NoClip=0xffffu;
        std::uint32_t sceneNode=0;
        std::uint16_t firstClip=0;
        std::uint16_t clipCount=0;
        std::uint16_t activeClip=NoClip;
        double elapsed=0.0;
        bool playing=false;
        Pose base{};
    };

private:
    const Clip* activeClip(const Controller& controller) const;
    Controller* controller(std::uint32_t sceneNode);
    const Controller* controller(std::uint32_t sceneNode) const;
    Pose sample(const Clip& clip,double elapsed) const;
    void compose(const Controller& controller,std::vector<NodeData>& nodes) const;
    void restore(const Controller& controller,std::vector<NodeData>& nodes) const;
    std::vector<Clip> clips_;
    std::vector<Controller> controllers_;
    std::vector<Key> keys_;
};

} // namespace kc
