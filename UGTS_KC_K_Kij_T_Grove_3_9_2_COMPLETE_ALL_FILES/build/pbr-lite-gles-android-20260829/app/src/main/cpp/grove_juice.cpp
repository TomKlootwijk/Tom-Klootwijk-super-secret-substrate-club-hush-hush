#include "grove_juice.hpp"
#include <algorithm>
#include <cmath>

namespace kc {

void GroveJuice::configure(float masterIntensity, float maxFrameEffect, float bloomScale) {
    master_=std::max(0.0f,masterIntensity);
    maxEffect_=std::max(0.0f,maxFrameEffect);
    bloomScale_=clamp(bloomScale,0.25f,2.0f);
}

void GroveJuice::event(std::uint32_t kind, float intensity) {
    const float i=clamp(intensity*master_,0.0f,maxEffect_);
    switch(kind) {
        case Jump:  pulse_=std::max(pulse_,0.22f*i); shake_=std::max(shake_,0.06f*i); break;
        case Land:  pulse_=std::max(pulse_,0.36f*i); shake_=std::max(shake_,0.16f*i); bloom_=std::max(bloom_,0.18f*i); break;
        case Dash:  pulse_=std::max(pulse_,0.48f*i); shake_=std::max(shake_,0.10f*i); bloom_=std::max(bloom_,0.32f*i); break;
        case Pickup: pulse_=std::max(pulse_,0.30f*i); flash_=std::max(flash_,0.22f*i); bloom_=std::max(bloom_,0.48f*i); shock_=std::max(shock_,0.72f*i); shockAge_=0.0f; break;
        case Hazard: pulse_=std::max(pulse_,0.55f*i); flash_=std::max(flash_,0.32f*i); bloom_=std::max(bloom_,0.10f*i); shake_=std::max(shake_,0.22f*i); break;
        case Goal: pulse_=std::max(pulse_,0.9f*i); flash_=std::max(flash_,0.55f*i); bloom_=std::max(bloom_,0.9f*i); shock_=std::max(shock_,1.0f*i); shockAge_=0.0f; break;
        default: break;
    }
}

void GroveJuice::update(float dt, float timeSeconds) {
    const float d=clamp(dt,0.0f,0.1f);
    pulse_=std::max(0.0f,pulse_-d*1.45f);
    flash_=std::max(0.0f,flash_-d*1.8f);
    bloom_=std::max(0.0f,bloom_-d*0.9f);
    shake_=std::max(0.0f,shake_-d*1.35f);
    shockAge_+=d;
    const float shockEnvelope=shockAge_<1.0f ? std::exp(-shockAge_*3.5f) : 0.0f;
    shock_=std::max(0.0f,shock_-d*0.6f);
    const float wobble=0.5f+0.5f*std::sin(timeSeconds*8.0f);
    const float dynamicPulse=pulse_*(0.74f+0.26f*wobble);
    frame_.pulse=dynamicPulse;
    frame_.flash=flash_;
    frame_.bloom=clamp((bloom_+dynamicPulse*0.22f)*bloomScale_,0.0f,1.0f);
    frame_.aberration=(flash_*0.010f+bloom_*0.004f)*master_;
    frame_.vignette=clamp(0.10f+dynamicPulse*0.18f,0.0f,0.45f);
    frame_.saturation=1.0f+dynamicPulse*0.28f;
    frame_.contrast=1.0f+dynamicPulse*0.12f;
    frame_.shock=std::max(shock_*0.85f,shockEnvelope*shock_);
    frame_.shockX=shockX_; frame_.shockY=shockY_;
    frame_.cameraShake=shake_;
}

} // namespace kc
