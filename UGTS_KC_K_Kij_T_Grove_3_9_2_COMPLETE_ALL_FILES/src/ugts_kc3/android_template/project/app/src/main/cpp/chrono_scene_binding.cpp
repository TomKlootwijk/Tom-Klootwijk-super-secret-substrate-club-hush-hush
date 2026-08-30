#include "chrono_scene_binding.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <span>
#include <stdexcept>

namespace kc {
namespace {

constexpr std::size_t HeaderBytes=64u;
constexpr std::size_t RecordBytes=176u;
constexpr std::size_t DigestOffset=32u;
constexpr std::uint32_t MaximumRecords=4096u;
constexpr std::uint32_t MaximumStringBytes=1u<<20u;

void require(bool condition,const char* message) {
    if (!condition) throw std::runtime_error(message);
}

class Reader final {
public:
    explicit Reader(std::span<const std::uint8_t> bytes):bytes_(bytes) {}
    std::span<const std::uint8_t> raw(std::size_t count) {
        if (count>bytes_.size()-offset_) throw std::runtime_error("truncated KCCH392 binding pack");
        const auto result=bytes_.subspan(offset_,count);
        offset_+=count;
        return result;
    }
    std::uint8_t u8() { return raw(1u)[0]; }
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
    double f64() {
        const auto bits=u64();
        double result=0.0;
        std::memcpy(&result,&bits,sizeof(result));
        return result;
    }
    std::size_t remaining() const { return bytes_.size()-offset_; }
private:
    std::span<const std::uint8_t> bytes_;
    std::size_t offset_=0;
};

ChronoSha256Digest contentDigest(std::span<const std::uint8_t> bytes) {
    require(bytes.size()>=HeaderBytes,"KCCH392 header truncated");
    ChronoSha256 hasher;
    hasher.update(bytes.first(DigestOffset));
    constexpr std::array<std::uint8_t,32> ZeroDigest{};
    hasher.update(ZeroDigest);
    hasher.update(bytes.subspan(DigestOffset+ZeroDigest.size()));
    return hasher.finish();
}

std::string readString(
    std::span<const std::uint8_t> table,std::uint32_t offset,std::uint16_t length
) {
    require(offset<=table.size() && length<=table.size()-offset,"KCCH392 string reference out of range");
    const auto bytes=table.subspan(offset,length);
    require(std::find(bytes.begin(),bytes.end(),0u)==bytes.end(),"KCCH392 string contains NUL");
    return {reinterpret_cast<const char*>(bytes.data()),bytes.size()};
}

bool digestIsZero(const ChronoSha256Digest& digest) {
    return std::all_of(digest.begin(),digest.end(),[](std::uint8_t value){ return value==0u; });
}

void validateOutputBasename(const std::string& value) {
    require(!value.empty(),"KCCH392 recorder output basename is empty");
    require(value!="." && value!="..","KCCH392 recorder output basename is unsafe");
    require(
        value.find('/')==std::string::npos && value.find('\\')==std::string::npos,
        "KCCH392 recorder output basename must not contain a path separator"
    );
}

} // namespace

void ChronoSceneBindings::load(
    const std::vector<std::uint8_t>& bytes,std::size_t sceneNodeCount
) {
    records_.clear();
    if (bytes.empty()) return;
    Reader reader(bytes);
    const auto magic=reader.raw(8u);
    require(std::memcmp(magic.data(),"KCCH392\0",8u)==0,"KCCH392 magic mismatch");
    require(reader.u32()==0x01020304u,"KCCH392 endian marker mismatch");
    require(reader.u16()==1u,"unsupported KCCH392 version");
    require(reader.u16()==HeaderBytes,"KCCH392 header size mismatch");
    const auto recordCount=reader.u32();
    require(recordCount<=MaximumRecords,"KCCH392 record limit exceeded");
    require(reader.u32()==RecordBytes,"KCCH392 record size mismatch");
    const auto stringBytes=reader.u32();
    require(stringBytes<=MaximumStringBytes,"KCCH392 string table limit exceeded");
    require(reader.u32()==0u,"KCCH392 flags must be zero");
    ChronoSha256Digest expectedDigest{};
    const auto digestBytes=reader.raw(expectedDigest.size());
    std::copy(digestBytes.begin(),digestBytes.end(),expectedDigest.begin());
    require(contentDigest(bytes)==expectedDigest,"KCCH392 content SHA-256 mismatch");
    require(
        recordCount<=(std::numeric_limits<std::size_t>::max()-HeaderBytes)/RecordBytes,
        "KCCH392 record byte count overflow"
    );
    const auto recordsBytes=static_cast<std::size_t>(recordCount)*RecordBytes;
    require(
        HeaderBytes+recordsBytes<=bytes.size() &&
        stringBytes==bytes.size()-(HeaderBytes+recordsBytes),
        "KCCH392 total size mismatch"
    );

    struct StringReferences {
        std::uint32_t cameraOffset=0,outputOffset=0,assetOffset=0;
        std::uint16_t cameraLength=0,outputLength=0,assetLength=0;
    };
    std::vector<StringReferences> references;
    records_.reserve(recordCount);
    references.reserve(recordCount);
    std::uint32_t previousNode=0;
    bool havePrevious=false;
    std::size_t recorderCount=0;
    for (std::uint32_t index=0;index<recordCount;++index) {
        ChronoSceneBinding binding;
        binding.nodeIndex=reader.u32();
        require(binding.nodeIndex<sceneNodeCount,"KCCH392 node index out of range");
        require(!havePrevious || binding.nodeIndex>previousNode,"KCCH392 records are not strictly node-sorted");
        previousNode=binding.nodeIndex;
        havePrevious=true;
        const auto mode=reader.u8();
        require(mode==1u || mode==2u,"KCCH392 mode is invalid");
        binding.mode=static_cast<ChronoSceneMode>(mode);
        require(reader.u8()==1u,"KCCH392 pixel profile must be UGCODE24_420_CAMERA_EXACT");
        const auto storage=reader.u8();
        require(storage==1u || storage==2u,"KCCH392 storage mode is invalid");
        require(reader.u8()==1u,"KCCH392 capture authority must be Camera2 dense YUV420");
        require(reader.u8()==1u,"KCCH392 novelty policy must require exact residuals");
        require(reader.u8()==1u,"KCCH392 geometry authority must remain UNKNOWN");
        require(reader.u8()==0u,"KCCH392 v1 autostart must be zero");
        require(reader.u8()==0u,"KCCH392 reserved byte must be zero");
        binding.width=reader.u32();
        binding.height=reader.u32();
        const auto fpsMin=reader.u16();
        const auto fpsMax=reader.u16();
        require(fpsMin==fpsMax && fpsMin>0u,"KCCH392 v1 requires a fixed positive frame rate");
        binding.fps=fpsMin;
        binding.queueSlots=reader.u16();
        binding.uglutResolution=reader.u16();
        binding.rootSeed=reader.u64();
        binding.recipeSeed=reader.u64();
        binding.r0=reader.f64();
        binding.rhoMin=reader.f64();
        binding.rhoMax=reader.f64();
        binding.coreRadius=reader.f64();
        const auto lutDigest=reader.raw(binding.uglut2Sha256.size());
        std::copy(lutDigest.begin(),lutDigest.end(),binding.uglut2Sha256.begin());
        binding.sourceAssetBytes=reader.u64();
        const auto sourceDigest=reader.raw(binding.sourceAssetSha256.size());
        std::copy(sourceDigest.begin(),sourceDigest.end(),binding.sourceAssetSha256.begin());
        StringReferences refs;
        refs.cameraOffset=reader.u32(); refs.cameraLength=reader.u16();
        require(reader.u16()==0u,"KCCH392 camera string reserved value is nonzero");
        refs.outputOffset=reader.u32(); refs.outputLength=reader.u16();
        require(reader.u16()==0u,"KCCH392 output string reserved value is nonzero");
        refs.assetOffset=reader.u32(); refs.assetLength=reader.u16();
        require(reader.u16()==0u,"KCCH392 asset string reserved value is nonzero");
        require(reader.u32()==0u,"KCCH392 record trailing reserved value is nonzero");

        require(
            binding.width>=2u && binding.width<=65'534u &&
            binding.height>=2u && binding.height<=65'534u &&
            (binding.width&1u)==0u && (binding.height&1u)==0u,
            "KCCH392 YUV420 dimensions must be positive and even"
        );
        require(binding.queueSlots>=3u && binding.queueSlots<=16u,"KCCH392 queue slot count must be in [3,16]");
        require(binding.uglutResolution>=2u,"KCCH392 UGLUT2 resolution is invalid");
        require(binding.recipeSeed==1u,"KCCH392 v1 recipe seed must be one");
        require(
            std::isfinite(binding.r0) && binding.r0>0.0 &&
            std::isfinite(binding.rhoMin) && std::isfinite(binding.rhoMax) &&
            binding.rhoMin<=binding.rhoMax &&
            std::isfinite(binding.coreRadius) && binding.coreRadius>=0.0,
            "KCCH392 log-polar parameters are invalid"
        );
        require(!digestIsZero(binding.uglut2Sha256),"KCCH392 UGLUT2 digest must be present");
        if (binding.mode==ChronoSceneMode::Recorder) {
            ++recorderCount;
            require(storage==1u,"KCCH392 recorder must use app-private storage");
            require(binding.sourceAssetBytes==0u && digestIsZero(binding.sourceAssetSha256),
                "KCCH392 recorder must not claim a packaged source asset");
            require(refs.cameraLength>0u && refs.outputLength>0u && refs.assetLength==0u,
                "KCCH392 recorder string fields are invalid");
        } else {
            require(storage==2u,"KCCH392 player must use packaged storage in v1");
            require(binding.sourceAssetBytes>0u && !digestIsZero(binding.sourceAssetSha256),
                "KCCH392 player source receipt is absent");
            require(refs.cameraLength==0u && refs.outputLength==0u && refs.assetLength>0u,
                "KCCH392 player string fields are invalid");
        }
        records_.push_back(std::move(binding));
        references.push_back(refs);
    }
    require(recorderCount<=1u,"KCCH392 v1 permits only one Camera2 capture authority");
    const auto stringTable=reader.raw(stringBytes);
    require(reader.remaining()==0u,"KCCH392 trailing bytes");
    for (std::size_t index=0;index<records_.size();++index) {
        auto& binding=records_[index];
        const auto& refs=references[index];
        binding.cameraId=readString(stringTable,refs.cameraOffset,refs.cameraLength);
        binding.outputBasename=readString(stringTable,refs.outputOffset,refs.outputLength);
        binding.packagedAssetPath=readString(stringTable,refs.assetOffset,refs.assetLength);
        if (binding.mode==ChronoSceneMode::Recorder) validateOutputBasename(binding.outputBasename);
        else require(
            binding.packagedAssetPath.starts_with("chrono/") &&
            binding.packagedAssetPath.find("..") == std::string::npos,
            "KCCH392 packaged asset path is unsafe"
        );
    }
}

const ChronoSceneBinding* ChronoSceneBindings::recorder() const {
    for (const auto& binding:records_)
        if (binding.mode==ChronoSceneMode::Recorder) return &binding;
    return nullptr;
}

} // namespace kc
