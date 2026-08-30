#include "chrono_video_timeline.hpp"

#include <algorithm>
#include <cstring>
#include <limits>
#include <numeric>
#include <stdexcept>

namespace kc {
namespace {

constexpr std::size_t HeaderBytes=208u;
constexpr std::size_t EntryBytes=32u;
constexpr std::uint32_t MaximumEntries=1'000'000u;
constexpr std::uint32_t MaximumSourceFrames=10'000'000u;
constexpr std::uint32_t KnownFlags=
    ChronoMediaOriginalSource|ChronoMediaDerivedPolarPreview|
    ChronoApplyUgcvLutQ8|ChronoAlreadyLogPolar|ChronoLoop;

void require(bool condition,const char* message) {
    if (!condition) throw std::runtime_error(message);
}

class Reader {
public:
    explicit Reader(std::span<const std::uint8_t> bytes):bytes_(bytes) {}
    std::span<const std::uint8_t> raw(std::size_t count) {
        if (count>bytes_.size()-offset_) throw std::runtime_error("truncated UGCVPTS1 asset");
        const auto result=bytes_.subspan(offset_,count);
        offset_+=count;
        return result;
    }
    std::uint16_t u16() {
        const auto p=raw(2u);
        return static_cast<std::uint16_t>(p[0])|
            static_cast<std::uint16_t>(static_cast<std::uint16_t>(p[1])<<8u);
    }
    std::uint32_t u32() {
        const auto p=raw(4u);
        return static_cast<std::uint32_t>(p[0])|
            (static_cast<std::uint32_t>(p[1])<<8u)|
            (static_cast<std::uint32_t>(p[2])<<16u)|
            (static_cast<std::uint32_t>(p[3])<<24u);
    }
    std::uint64_t u64() {
        const auto low=static_cast<std::uint64_t>(u32());
        return low|(static_cast<std::uint64_t>(u32())<<32u);
    }
    std::int64_t i64() { return static_cast<std::int64_t>(u64()); }
    std::size_t remaining() const { return bytes_.size()-offset_; }
private:
    std::span<const std::uint8_t> bytes_;
    std::size_t offset_=0;
};

constexpr std::uint32_t rotateRight(std::uint32_t value,unsigned shift) {
    return (value>>shift)|(value<<(32u-shift));
}

} // namespace

std::array<std::uint8_t,32> chronoSha256(std::span<const std::uint8_t> source) {
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
    std::vector<std::uint8_t> data(source.begin(),source.end());
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
            words[index]=(static_cast<std::uint32_t>(p[0])<<24u)|
                (static_cast<std::uint32_t>(p[1])<<16u)|
                (static_cast<std::uint32_t>(p[2])<<8u)|p[3];
        }
        for (std::size_t index=16u;index<64u;++index) {
            const auto x=words[index-15u],y=words[index-2u];
            const auto small0=rotateRight(x,7u)^rotateRight(x,18u)^(x>>3u);
            const auto small1=rotateRight(y,17u)^rotateRight(y,19u)^(y>>10u);
            words[index]=words[index-16u]+small0+words[index-7u]+small1;
        }
        auto a=state[0],b=state[1],c=state[2],d=state[3];
        auto e=state[4],f=state[5],g=state[6],h=state[7];
        for (std::size_t index=0;index<64u;++index) {
            const auto big1=rotateRight(e,6u)^rotateRight(e,11u)^rotateRight(e,25u);
            const auto choice=(e&f)^((~e)&g);
            const auto temp1=h+big1+choice+constants[index]+words[index];
            const auto big0=rotateRight(a,2u)^rotateRight(a,13u)^rotateRight(a,22u);
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
        result[index*4u]=static_cast<std::uint8_t>(state[index]>>24u);
        result[index*4u+1u]=static_cast<std::uint8_t>(state[index]>>16u);
        result[index*4u+2u]=static_cast<std::uint8_t>(state[index]>>8u);
        result[index*4u+3u]=static_cast<std::uint8_t>(state[index]);
    }
    return result;
}

void ChronoVideoTimeline::load(const std::vector<std::uint8_t>& bytes) {
    *this={};
    require(bytes.size()>=HeaderBytes,"UGCVPTS1 header is truncated");
    Reader reader(bytes);
    const auto magic=reader.raw(8u);
    require(std::memcmp(magic.data(),"UGCVPTS1",8u)==0,"UGCVPTS1 magic mismatch");
    require(reader.u16()==1u && reader.u16()==0u,"unsupported UGCVPTS1 version");
    require(reader.u32()==HeaderBytes && reader.u32()==EntryBytes,"UGCVPTS1 ABI mismatch");
    flags=reader.u32();
    require((flags&~KnownFlags)==0u,"UGCVPTS1 has unknown flags");
    const bool original=(flags&ChronoMediaOriginalSource)!=0u;
    const bool preview=(flags&ChronoMediaDerivedPolarPreview)!=0u;
    const bool lut=(flags&ChronoApplyUgcvLutQ8)!=0u;
    const bool polar=(flags&ChronoAlreadyLogPolar)!=0u;
    require(original!=preview && lut!=polar,"UGCVPTS1 role flags are contradictory");
    require(original==lut && preview==polar,"UGCVPTS1 role and raster flags disagree");
    const auto entryCount=reader.u32();
    require(entryCount>=1u && entryCount<=MaximumEntries,"UGCVPTS1 entry count is outside its profile");
    mediaWidth=reader.u32(); mediaHeight=reader.u32();
    sourceFrameCount=reader.u32();
    require(mediaWidth>=1u && mediaWidth<=65'535u && mediaHeight>=1u && mediaHeight<=65'535u,
        "UGCVPTS1 media dimensions are outside its profile");
    require(sourceFrameCount>=1u && sourceFrameCount<=MaximumSourceFrames,
        "UGCVPTS1 source frame count is outside its profile");
    require(reader.u32()==0u,"UGCVPTS1 reserved header field is nonzero");
    firstSourcePts=reader.i64(); endSourcePtsExclusive=reader.i64();
    timeBaseNumerator=reader.u64(); timeBaseDenominator=reader.u64();
    require(timeBaseNumerator>=1u && timeBaseNumerator<=static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()),
        "UGCVPTS1 time-base numerator is invalid");
    require(timeBaseDenominator>=1u && timeBaseDenominator<=static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()),
        "UGCVPTS1 time-base denominator is invalid");
    const auto copyDigest=[&reader](auto& target) {
        const auto value=reader.raw(target.size());
        std::copy(value.begin(),value.end(),target.begin());
    };
    copyDigest(sourceSha256); copyDigest(profileSha256); copyDigest(mediaSha256); copyDigest(contentSha256);
    require(reader.u32()==0u,"UGCVPTS1 trailing reserved header field is nonzero");
    const auto expectedSize=HeaderBytes+static_cast<std::size_t>(entryCount)*EntryBytes;
    require(bytes.size()==expectedSize,"UGCVPTS1 length mismatch");
    auto unsignedBytes=bytes;
    std::fill(unsignedBytes.begin()+172,unsignedBytes.begin()+204,0u);
    require(chronoSha256(unsignedBytes)==contentSha256,"UGCVPTS1 content SHA-256 mismatch");

    entries.reserve(entryCount);
    for (std::uint32_t index=0;index<entryCount;++index) {
        ChronoVideoPtsEntry entry;
        entry.mediaIndex=reader.u32();
        entry.sourceFrameIndex=reader.u32();
        entry.sourcePts=reader.i64();
        entry.displayUntilSourcePts=reader.i64();
        const auto entryFlags=reader.u32();
        const auto reserved=reader.u32();
        require(entry.mediaIndex==index,"UGCVPTS1 media indices are not dense");
        require(entry.sourceFrameIndex<sourceFrameCount,"UGCVPTS1 source frame index is out of range");
        require(entry.displayUntilSourcePts>entry.sourcePts,"UGCVPTS1 interval is not positive");
        require(entryFlags==0u && reserved==0u,"UGCVPTS1 entry reserved fields are nonzero");
        if (!entries.empty()) {
            const auto& previous=entries.back();
            require(entry.sourceFrameIndex>previous.sourceFrameIndex,
                "UGCVPTS1 source frame indices are not strictly increasing");
            require(entry.sourcePts>previous.sourcePts,
                "UGCVPTS1 source PTS values are not strictly increasing");
            require(entry.sourcePts==previous.displayUntilSourcePts,
                "UGCVPTS1 half-open intervals are not contiguous");
        }
        entries.push_back(entry);
    }
    require(reader.remaining()==0u,"UGCVPTS1 has trailing bytes");
    require(entries.front().sourceFrameIndex==0u,"UGCVPTS1 does not begin at source frame zero");
    require(entries.back().sourceFrameIndex==sourceFrameCount-1u,
        "UGCVPTS1 does not bind the final source frame");
    require(firstSourcePts==entries.front().sourcePts,"UGCVPTS1 first PTS header mismatch");
    require(endSourcePtsExclusive==entries.back().displayUntilSourcePts,
        "UGCVPTS1 exclusive-end header mismatch");
    require(endSourcePtsExclusive>firstSourcePts,"UGCVPTS1 duration is not positive");
}

std::int64_t ChronoVideoTimeline::exactMediaTimeUs(std::int64_t sourcePts) const {
    require(sourcePts>=0,"UGCVPTS1 MediaCodec PTS is negative");
    std::uint64_t source=static_cast<std::uint64_t>(sourcePts);
    std::uint64_t base=timeBaseNumerator;
    std::uint64_t micros=1'000'000u;
    std::uint64_t denominator=timeBaseDenominator;
    const auto cancel=[&denominator](std::uint64_t& factor) {
        const auto common=std::gcd(factor,denominator);
        factor/=common;
        denominator/=common;
    };
    cancel(source); cancel(base); cancel(micros);
    require(denominator==1u,
        "UGCVPTS1 PTS is not exactly representable in MediaCodec microseconds");
    std::uint64_t value=1u;
    constexpr auto limit=static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max());
    for (const auto factor:{source,base,micros}) {
        if (factor==0u) { value=0u; break; }
        require(value<=limit/factor,"UGCVPTS1 MediaCodec PTS is out of range");
        value*=factor;
    }
    return static_cast<std::int64_t>(value);
}

std::size_t ChronoVideoTimeline::selectForElapsedNanoseconds(
    std::uint64_t elapsedNanoseconds
) const {
    require(!entries.empty(),"UGCVPTS1 has no entries");
    const __int128 numerator=static_cast<__int128>(elapsedNanoseconds)*
        static_cast<__int128>(timeBaseDenominator);
    const __int128 denominator=static_cast<__int128>(1'000'000'000ull)*
        static_cast<__int128>(timeBaseNumerator);
    __int128 offset=numerator/denominator;
    const auto duration=static_cast<__int128>(endSourcePtsExclusive)-firstSourcePts;
    if (loop()) offset%=duration;
    else if (offset>=duration) return entries.size()-1u;
    const auto target=static_cast<__int128>(firstSourcePts)+offset;
    const auto it=std::upper_bound(
        entries.begin(),entries.end(),target,
        [](const __int128 value,const ChronoVideoPtsEntry& entry) {
            return value<static_cast<__int128>(entry.displayUntilSourcePts);
        }
    );
    return static_cast<std::size_t>(
        std::distance(entries.begin(),it==entries.end()?std::prev(entries.end()):it)
    );
}

std::uint64_t ChronoVideoTimeline::completedCyclesForElapsedNanoseconds(
    std::uint64_t elapsedNanoseconds
) const {
    if (!loop()) return 0u;
    const __int128 numerator=static_cast<__int128>(elapsedNanoseconds)*
        static_cast<__int128>(timeBaseDenominator);
    const __int128 denominator=static_cast<__int128>(1'000'000'000ull)*
        static_cast<__int128>(timeBaseNumerator);
    const __int128 offset=numerator/denominator;
    const __int128 duration=static_cast<__int128>(endSourcePtsExclusive)-firstSourcePts;
    const __int128 cycles=offset/duration;
    constexpr auto maximum=std::numeric_limits<std::uint64_t>::max();
    return cycles>static_cast<__int128>(maximum)
        ?maximum:static_cast<std::uint64_t>(cycles);
}

} // namespace kc
