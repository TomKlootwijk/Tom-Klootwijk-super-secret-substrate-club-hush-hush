#pragma once

#include <cstdint>
#include <vector>

namespace kc {

enum class PolarRenderMode : std::uint8_t {
    Auto=0,
    Lut=1,
    Direct=2,
    Cpu=3,
};

enum class BayerRenderMode : std::uint8_t {
    Off=0,
    Subtle=1,
    Retro=2,
    Custom=3,
};

struct RenderSubstrateConfig {
    bool present=false;
    PolarRenderMode polarMode=PolarRenderMode::Cpu;
    BayerRenderMode bayerMode=BayerRenderMode::Off;
    std::uint16_t levels=2;
    float strength=0.0f;
    std::uint64_t seed=0;

    bool bayerEnabled() const {
        return present && bayerMode!=BayerRenderMode::Off && strength>0.0f;
    }
};

RenderSubstrateConfig parseRenderSubstrate(const std::vector<std::uint8_t>& bytes);
const char* polarRenderModeName(PolarRenderMode mode);
const char* bayerRenderModeName(BayerRenderMode mode);

} // namespace kc
