#pragma once

#include "scene_pack.hpp"
#include <cstddef>
#include <cstdint>
#include <vector>

namespace kc {

// KCHI keeps parent-local transforms outside NodeData.  NodeData remains the
// flat renderer/gameplay ABI and receives composed world transforms only.
class TransformHierarchy {
public:
    void load(
        const std::vector<std::uint8_t>& bytes,
        const std::vector<NodeData>& nodes
    );
    void compose(std::vector<NodeData>& nodes) const;
    std::size_t linkCount() const { return links_.size(); }
    std::uint32_t maxDepth() const { return maxDepth_; }
    bool isLinked(std::uint32_t sceneNode) const {
        return sceneNode<linkedNodes_.size() && linkedNodes_[sceneNode]!=0;
    }
    bool isChild(std::uint32_t sceneNode) const {
        return sceneNode<childNodes_.size() && childNodes_[sceneNode]!=0;
    }

private:
    struct Link {
        std::uint32_t childIndex=0;
        std::uint32_t parentIndex=0;
        std::uint32_t depth=0;
        Vec3 localTranslation{};
        Quat localRotation{};
        Vec3 localScale{1.0f,1.0f,1.0f};
    };

    std::vector<Link> links_;
    std::vector<std::uint8_t> linkedNodes_;
    std::vector<std::uint8_t> childNodes_;
    std::uint32_t maxDepth_=0;
};

} // namespace kc
