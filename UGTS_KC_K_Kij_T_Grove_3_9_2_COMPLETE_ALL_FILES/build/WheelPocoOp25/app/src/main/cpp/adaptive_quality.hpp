#pragma once
#include "scene_pack.hpp"
#include <cstddef>

namespace kc {

class AdaptiveQuality {
public:
    explicit AdaptiveQuality(std::size_t initialIndex=0): index_(initialIndex) {}
    std::size_t update(const ScenePack& scene,float measuredFps,float targetFps,int thermalStatus,float dt);
    std::size_t index() const { return index_; }
private:
    std::size_t index_=0;
    float stressedSeconds_=0;
    float recoverySeconds_=0;
};

} // namespace kc
