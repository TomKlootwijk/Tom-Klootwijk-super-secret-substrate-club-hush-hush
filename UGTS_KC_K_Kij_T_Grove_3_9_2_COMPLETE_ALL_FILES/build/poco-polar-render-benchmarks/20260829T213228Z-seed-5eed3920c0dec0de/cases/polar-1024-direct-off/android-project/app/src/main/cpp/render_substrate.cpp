#include "render_substrate.hpp"

#include <cmath>
#include <cstring>
#include <stdexcept>

namespace kc {
namespace {

constexpr std::size_t RenderSubstrateBytes=32;

class Reader {
public:
    explicit Reader(const std::vector<std::uint8_t>& bytes):bytes_(bytes) {}

    const std::uint8_t* raw(std::size_t count) {
        if (count>bytes_.size()-offset_)
            throw std::runtime_error("truncated KCRP render-substrate asset");
        const auto* result=bytes_.data()+offset_;
        offset_+=count;
        return result;
    }

    std::uint8_t u8() { return *raw(1); }

    std::uint16_t u16() {
        const auto* p=raw(2);
        return static_cast<std::uint16_t>(
            static_cast<std::uint16_t>(p[0])|
            (static_cast<std::uint16_t>(p[1])<<8)
        );
    }

    std::uint32_t u32() {
        const auto* p=raw(4);
        return static_cast<std::uint32_t>(p[0])|
            (static_cast<std::uint32_t>(p[1])<<8)|
            (static_cast<std::uint32_t>(p[2])<<16)|
            (static_cast<std::uint32_t>(p[3])<<24);
    }

    std::uint64_t u64() {
        const auto low=static_cast<std::uint64_t>(u32());
        return low|(static_cast<std::uint64_t>(u32())<<32);
    }

    float f32() {
        const auto bits=u32();
        float value=0.0f;
        std::memcpy(&value,&bits,sizeof(value));
        return value;
    }

private:
    const std::vector<std::uint8_t>& bytes_;
    std::size_t offset_=0;
};

void require(bool condition,const char* message) {
    if (!condition) throw std::runtime_error(message);
}

} // namespace

RenderSubstrateConfig parseRenderSubstrate(const std::vector<std::uint8_t>& bytes) {
    if (bytes.empty()) return {};
    require(bytes.size()>=RenderSubstrateBytes,"KCRP render-substrate asset is truncated");
    require(bytes.size()<=RenderSubstrateBytes,"KCRP render-substrate asset has trailing bytes");

    Reader reader(bytes);
    require(
        std::memcmp(reader.raw(8),"KCRP392\0",8)==0,
        "KCRP render-substrate magic mismatch"
    );
    require(reader.u32()==0x01020304u,"KCRP render-substrate endian marker mismatch");
    require(reader.u32()==1u,"unsupported KCRP render-substrate version");

    const auto polarCode=reader.u8();
    const auto bayerCode=reader.u8();
    const auto levels=reader.u16();
    const auto strength=reader.f32();
    const auto seed=reader.u64();
    require(polarCode<=3u,"KCRP polar render mode is invalid");
    require(bayerCode<=3u,"KCRP Bayer render mode is invalid");
    require(levels>=2u&&levels<=256u,"KCRP Bayer levels are invalid");
    require(
        std::isfinite(strength)&&strength>=0.0f&&strength<=1.0f,
        "KCRP Bayer strength is invalid"
    );
    require(
        bayerCode!=static_cast<std::uint8_t>(BayerRenderMode::Off)||strength==0.0f,
        "KCRP Bayer off mode has nonzero strength"
    );

    RenderSubstrateConfig result;
    result.present=true;
    result.polarMode=static_cast<PolarRenderMode>(polarCode);
    result.bayerMode=static_cast<BayerRenderMode>(bayerCode);
    result.levels=levels;
    result.strength=strength;
    result.seed=seed;
    return result;
}

const char* polarRenderModeName(PolarRenderMode mode) {
    switch (mode) {
        case PolarRenderMode::Auto: return "auto";
        case PolarRenderMode::Lut: return "lut";
        case PolarRenderMode::Direct: return "direct";
        case PolarRenderMode::Cpu: return "cpu";
    }
    return "unknown";
}

const char* bayerRenderModeName(BayerRenderMode mode) {
    switch (mode) {
        case BayerRenderMode::Off: return "off";
        case BayerRenderMode::Subtle: return "subtle";
        case BayerRenderMode::Retro: return "retro";
        case BayerRenderMode::Custom: return "custom";
    }
    return "unknown";
}

} // namespace kc
