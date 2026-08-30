#include "chrono_capture_sha256.hpp"

#include <algorithm>
#include <stdexcept>

namespace kc {
namespace {

constexpr std::array<std::uint32_t,64> Constants{{
    0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,0x923f82a4u,0xab1c5ed5u,
    0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,
    0xe49b69c1u,0xefbe4786u,0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
    0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,0x06ca6351u,0x14292967u,
    0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,
    0xa2bfe8a1u,0xa81a664bu,0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
    0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,0x5b9cca4fu,0x682e6ff3u,
    0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u,
}};

constexpr std::uint32_t rotateRight(std::uint32_t value,unsigned shift) {
    return (value>>shift)|(value<<(32u-shift));
}

} // namespace

ChronoSha256::ChronoSha256():state_{{
    0x6a09e667u,0xbb67ae85u,0x3c6ef372u,0xa54ff53au,
    0x510e527fu,0x9b05688cu,0x1f83d9abu,0x5be0cd19u,
}} {}

void ChronoSha256::transform(const std::uint8_t* block) {
    std::array<std::uint32_t,64> words{};
    for (std::size_t index=0;index<16u;++index) {
        const auto* p=block+index*4u;
        words[index]=(static_cast<std::uint32_t>(p[0])<<24u)|
            (static_cast<std::uint32_t>(p[1])<<16u)|
            (static_cast<std::uint32_t>(p[2])<<8u)|
            static_cast<std::uint32_t>(p[3]);
    }
    for (std::size_t index=16u;index<64u;++index) {
        const auto x=words[index-15u],y=words[index-2u];
        const auto small0=rotateRight(x,7u)^rotateRight(x,18u)^(x>>3u);
        const auto small1=rotateRight(y,17u)^rotateRight(y,19u)^(y>>10u);
        words[index]=words[index-16u]+small0+words[index-7u]+small1;
    }
    auto a=state_[0],b=state_[1],c=state_[2],d=state_[3];
    auto e=state_[4],f=state_[5],g=state_[6],h=state_[7];
    for (std::size_t index=0;index<64u;++index) {
        const auto big1=rotateRight(e,6u)^rotateRight(e,11u)^rotateRight(e,25u);
        const auto choice=(e&f)^((~e)&g);
        const auto temp1=h+big1+choice+Constants[index]+words[index];
        const auto big0=rotateRight(a,2u)^rotateRight(a,13u)^rotateRight(a,22u);
        const auto majority=(a&b)^(a&c)^(b&c);
        const auto temp2=big0+majority;
        h=g; g=f; f=e; e=d+temp1;
        d=c; c=b; b=a; a=temp1+temp2;
    }
    state_[0]+=a; state_[1]+=b; state_[2]+=c; state_[3]+=d;
    state_[4]+=e; state_[5]+=f; state_[6]+=g; state_[7]+=h;
}

void ChronoSha256::update(std::span<const std::uint8_t> bytes) {
    if (finished_) throw std::logic_error("SHA-256 update after finish");
    if (bytes.size()>static_cast<std::uint64_t>(-1)-byteCount_)
        throw std::overflow_error("SHA-256 byte count overflow");
    byteCount_+=static_cast<std::uint64_t>(bytes.size());
    while (!bytes.empty()) {
        const auto count=std::min(bytes.size(),buffered_.size()-bufferedBytes_);
        std::copy_n(bytes.data(),count,buffered_.data()+bufferedBytes_);
        bufferedBytes_+=count;
        bytes=bytes.subspan(count);
        if (bufferedBytes_==buffered_.size()) {
            transform(buffered_.data());
            bufferedBytes_=0;
        }
    }
}

ChronoSha256Digest ChronoSha256::finish() {
    if (finished_) throw std::logic_error("SHA-256 finish called twice");
    const auto bitCount=byteCount_*8u;
    buffered_[bufferedBytes_++]=0x80u;
    if (bufferedBytes_>56u) {
        std::fill(buffered_.begin()+static_cast<std::ptrdiff_t>(bufferedBytes_),buffered_.end(),0u);
        transform(buffered_.data());
        bufferedBytes_=0;
    }
    std::fill(
        buffered_.begin()+static_cast<std::ptrdiff_t>(bufferedBytes_),
        buffered_.begin()+56,0u
    );
    for (std::size_t index=0;index<8u;++index)
        buffered_[56u+index]=static_cast<std::uint8_t>(bitCount>>(56u-index*8u));
    transform(buffered_.data());
    finished_=true;
    ChronoSha256Digest result{};
    for (std::size_t index=0;index<state_.size();++index) {
        result[index*4u]=static_cast<std::uint8_t>(state_[index]>>24u);
        result[index*4u+1u]=static_cast<std::uint8_t>(state_[index]>>16u);
        result[index*4u+2u]=static_cast<std::uint8_t>(state_[index]>>8u);
        result[index*4u+3u]=static_cast<std::uint8_t>(state_[index]);
    }
    return result;
}

ChronoSha256Digest chronoCaptureSha256(std::span<const std::uint8_t> bytes) {
    ChronoSha256 hasher;
    hasher.update(bytes);
    return hasher.finish();
}

} // namespace kc
