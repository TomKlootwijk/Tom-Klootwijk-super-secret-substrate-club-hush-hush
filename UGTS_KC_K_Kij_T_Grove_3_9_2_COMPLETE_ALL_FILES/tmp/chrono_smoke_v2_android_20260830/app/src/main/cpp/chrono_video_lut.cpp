#include "chrono_video_lut.hpp"
#include <bit>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>

namespace kc {
namespace {

constexpr std::size_t HeaderBytes=108u;
constexpr std::size_t RuntimeTexelLimit=4u*1024u*1024u;

class Reader {
public:
    explicit Reader(const std::vector<std::uint8_t>& bytes)
        :data_(bytes.data()),size_(bytes.size()) {}
    const std::uint8_t* raw(std::size_t count) {
        if (count>size_-offset_) throw std::runtime_error("truncated UGCVLUT1 asset");
        const auto* result=data_+offset_;
        offset_+=count;
        return result;
    }
    std::uint16_t u16() {
        const auto* p=raw(2);
        return static_cast<std::uint16_t>(p[0])|
            static_cast<std::uint16_t>(static_cast<std::uint16_t>(p[1])<<8);
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
    double f64() { return std::bit_cast<double>(u64()); }
    std::size_t remaining() const { return size_-offset_; }
private:
    const std::uint8_t* data_=nullptr;
    std::size_t size_=0,offset_=0;
};

constexpr std::uint32_t rotateRight(std::uint32_t value,unsigned shift) {
    return (value>>shift)|(value<<(32u-shift));
}

std::array<std::uint8_t,32> sha256(const std::uint8_t* source,std::size_t size) {
    constexpr std::array<std::uint32_t,64> constants{{
        0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,0x923f82a4u,0xab1c5ed5u,
        0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,
        0xe49b69c1u,0xefbe4786u,0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
        0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,0x06ca6351u,0x14292967u,
        0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,
        0xa2bfe8a1u,0xa81a664bu,0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
        0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,0x5b9cca4fu,0x682e6ff3u,
        0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u,
    }};
    std::vector<std::uint8_t> data(source,source+size);
    const auto bitLength=static_cast<std::uint64_t>(data.size())*8u;
    data.push_back(0x80u);
    while ((data.size()%64u)!=56u) data.push_back(0u);
    for (int shift=56;shift>=0;shift-=8)
        data.push_back(static_cast<std::uint8_t>(bitLength>>shift));
    std::array<std::uint32_t,8> state{{
        0x6a09e667u,0xbb67ae85u,0x3c6ef372u,0xa54ff53au,
        0x510e527fu,0x9b05688cu,0x1f83d9abu,0x5be0cd19u,
    }};
    for (std::size_t offset=0;offset<data.size();offset+=64u) {
        std::array<std::uint32_t,64> words{};
        for (std::size_t index=0;index<16u;++index) {
            const auto* p=data.data()+offset+index*4u;
            words[index]=(static_cast<std::uint32_t>(p[0])<<24)|
                (static_cast<std::uint32_t>(p[1])<<16)|
                (static_cast<std::uint32_t>(p[2])<<8)|p[3];
        }
        for (std::size_t index=16u;index<64u;++index) {
            const auto x=words[index-15u],y=words[index-2u];
            const auto small0=rotateRight(x,7)^rotateRight(x,18)^(x>>3);
            const auto small1=rotateRight(y,17)^rotateRight(y,19)^(y>>10);
            words[index]=words[index-16u]+small0+words[index-7u]+small1;
        }
        auto a=state[0],b=state[1],c=state[2],d=state[3];
        auto e=state[4],f=state[5],g=state[6],h=state[7];
        for (std::size_t index=0;index<64u;++index) {
            const auto big1=rotateRight(e,6)^rotateRight(e,11)^rotateRight(e,25);
            const auto choice=(e&f)^((~e)&g);
            const auto temp1=h+big1+choice+constants[index]+words[index];
            const auto big0=rotateRight(a,2)^rotateRight(a,13)^rotateRight(a,22);
            const auto majority=(a&b)^(a&c)^(b&c);
            const auto temp2=big0+majority;
            h=g; g=f; f=e; e=d+temp1;
            d=c; c=b; b=a; a=temp1+temp2;
        }
        state[0]+=a; state[1]+=b; state[2]+=c; state[3]+=d;
        state[4]+=e; state[5]+=f; state[6]+=g; state[7]+=h;
    }
    std::array<std::uint8_t,32> result{};
    for (std::size_t index=0;index<state.size();++index) {
        result[index*4u]=static_cast<std::uint8_t>(state[index]>>24);
        result[index*4u+1u]=static_cast<std::uint8_t>(state[index]>>16);
        result[index*4u+2u]=static_cast<std::uint8_t>(state[index]>>8);
        result[index*4u+3u]=static_cast<std::uint8_t>(state[index]);
    }
    return result;
}

void require(bool condition,const char* message) {
    if (!condition) throw std::runtime_error(message);
}

} // namespace

void ChronoVideoLut::load(const std::vector<std::uint8_t>& bytes) {
    *this={};
    if (bytes.empty()) return;
    require(bytes.size()>=HeaderBytes,"UGCVLUT1 header is truncated");
    Reader reader(bytes);
    const auto* magic=reader.raw(8);
    require(std::memcmp(magic,"UGCVLUT1",8)==0,"UGCVLUT1 magic mismatch");
    require(reader.u16()==1u && reader.u16()==0u,"unsupported UGCVLUT1 version");
    sourceWidth=reader.u32(); sourceHeight=reader.u32();
    thetaBins=reader.u32(); rhoBins=reader.u32();
    require(sourceWidth>0u && sourceHeight>0u,"UGCVLUT1 source dimensions are zero");
    require(thetaBins>=16u && rhoBins>=16u,"UGCVLUT1 polar dimensions are too small");
    require((thetaBins&1u)==0u && (rhoBins&1u)==0u,"UGCVLUT1 polar dimensions must be even");
    const auto texelCount=static_cast<std::uint64_t>(thetaBins)*rhoBins;
    require(texelCount<=RuntimeTexelLimit,"UGCVLUT1 exceeds the phone runtime texel limit");
    centerX=reader.f64(); centerY=reader.f64(); r0=reader.f64();
    coreRadius=reader.f64(); rhoMin=reader.f64(); rhoMax=reader.f64();
    require(
        std::isfinite(centerX) && std::isfinite(centerY) &&
        std::isfinite(r0) && r0>0.0 &&
        std::isfinite(coreRadius) && coreRadius>0.0 &&
        std::isfinite(rhoMin) && std::isfinite(rhoMax) && rhoMax>rhoMin,
        "UGCVLUT1 chart parameters are invalid"
    );
    std::memcpy(payloadSha256.data(),reader.raw(payloadSha256.size()),payloadSha256.size());
    const auto payloadBytes=static_cast<std::size_t>(texelCount)*8u;
    require(reader.remaining()==payloadBytes,"UGCVLUT1 payload length mismatch");
    const auto* payload=reader.raw(payloadBytes);
    require(sha256(payload,payloadBytes)==payloadSha256,"UGCVLUT1 payload SHA-256 mismatch");
    texels.resize(static_cast<std::size_t>(texelCount)*4u);
    for (std::size_t index=0;index<texels.size();++index)
        texels[index]=static_cast<std::uint16_t>(payload[index*2u])|
            static_cast<std::uint16_t>(static_cast<std::uint16_t>(payload[index*2u+1u])<<8);
    for (std::size_t index=0;index<static_cast<std::size_t>(texelCount);++index) {
        const auto x0=texels[index*4u],y0=texels[index*4u+1u],valid=texels[index*4u+3u];
        require(valid<=1u,"UGCVLUT1 valid lane is not boolean");
        require(x0<sourceWidth && y0<sourceHeight,"UGCVLUT1 source address is out of range");
    }
    present=true;
}

} // namespace kc

