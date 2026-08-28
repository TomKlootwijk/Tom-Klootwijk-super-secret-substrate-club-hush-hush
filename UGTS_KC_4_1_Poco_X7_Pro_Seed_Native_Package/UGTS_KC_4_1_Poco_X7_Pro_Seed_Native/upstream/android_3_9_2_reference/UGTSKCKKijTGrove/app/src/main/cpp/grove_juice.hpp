#pragma once
#include "kc_math.hpp"
#include <array>
#include <cstdint>

namespace kc {

struct GroveJuiceFrame {
    float bloom = 0.0f;
    float flash = 0.0f;
    float aberration = 0.0f;
    float vignette = 0.0f;
    float saturation = 1.0f;
    float contrast = 1.0f;
    float shock = 0.0f;
    float shockX = 0.5f;
    float shockY = 0.5f;
    float pulse = 0.0f;
    float cameraShake = 0.0f;
};

class GroveJuice {
public:
    void configure(float masterIntensity, float maxFrameEffect, float bloomScale=1.0f);
    void event(std::uint32_t kind, float intensity=1.0f);
    void update(float dt, float timeSeconds);
    GroveJuiceFrame frame() const { return frame_; }

    enum Event : std::uint32_t {
        Jump=1, Land=2, Dash=3, Pickup=4, Hazard=5, Goal=6
    };
private:
    float master_=1.0f;
    float maxEffect_=1.0f;
    float bloomScale_=1.0f;
    float pulse_=0.0f;
    float flash_=0.0f;
    float bloom_=0.0f;
    float shock_=0.0f;
    float shake_=0.0f;
    float shockAge_=10.0f;
    float shockX_=0.5f, shockY_=0.5f;
    GroveJuiceFrame frame_{};
};

} // namespace kc
