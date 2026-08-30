#pragma once
#include "scene_pack.hpp"
#include <cstddef>
#include <cstdint>
#include <vector>

namespace kc {

// Sparse optional transform-timeline storage.  The KC3D NodeData layout stays
// unchanged: only authored nodes with a compiled timeline own one binding.
class TransformAnimations {
public:
    void clear();
    void load(const std::vector<std::uint8_t>& bytes,const std::vector<NodeData>& nodes);
    void compose(std::vector<NodeData>& nodes) const;
    void tick(float dt,std::vector<NodeData>& nodes);
    std::size_t bindingCount() const { return bindings_.size(); }
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
    struct Binding {
        std::uint32_t sceneNode=0;
        float duration=1.0f;
        std::uint32_t firstKey=0;
        std::uint16_t keyCount=0;
        std::uint8_t loop=0;
        double elapsed=0.0;
        Pose base{};
    };

private:
    Pose sample(const Binding& binding) const;
    void compose(const Binding& binding,std::vector<NodeData>& nodes) const;
    std::vector<Binding> bindings_;
    std::vector<Key> keys_;
};

} // namespace kc
