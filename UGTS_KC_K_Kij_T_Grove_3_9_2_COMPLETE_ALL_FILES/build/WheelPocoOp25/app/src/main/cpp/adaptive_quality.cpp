#include "adaptive_quality.hpp"
#include <algorithm>

namespace kc {

std::size_t AdaptiveQuality::update(const ScenePack& scene,float fps,float target,int thermal,float dt) {
    if (scene.qualities.empty()) { index_=0; return index_; }
    index_=std::min(index_,scene.qualities.size()-1);
    const bool stressed=thermal>=3 || fps<target*0.82f;
    const bool comfortable=thermal<=1 && fps>=target*0.96f;
    stressedSeconds_=stressed ? stressedSeconds_+std::max(0.0f,dt) : std::max(0.0f,stressedSeconds_-dt*0.5f);
    recoverySeconds_=comfortable ? recoverySeconds_+std::max(0.0f,dt) : 0.0f;
    if (stressedSeconds_>=1.5f && index_+1<scene.qualities.size()) {
        ++index_; stressedSeconds_=0; recoverySeconds_=0;
    } else if (recoverySeconds_>=8.0f && index_>0) {
        --index_; recoverySeconds_=0;
    }
    return index_;
}

} // namespace kc
