#include "chrono_mp4_transport.hpp"

#include <algorithm>
#include <stdexcept>

namespace kc {
namespace {

constexpr std::size_t FtypBytes=20u;
constexpr std::size_t MajorBrandOffset=8u;
constexpr std::size_t CompatibleBrandOffset=16u;
constexpr std::array<std::uint8_t,4> Ftyp{'f','t','y','p'};
constexpr std::array<std::uint8_t,4> Iso4{'i','s','o','4'};
constexpr std::array<std::uint8_t,4> Isom{'i','s','o','m'};

bool equalsAt(
    std::span<const std::uint8_t> bytes,std::size_t offset,
    const std::array<std::uint8_t,4>& expected
) {
    return offset<=bytes.size() && expected.size()<=bytes.size()-offset &&
        std::equal(expected.begin(),expected.end(),bytes.begin()+offset);
}

std::uint32_t readBigEndian32(std::span<const std::uint8_t> bytes) {
    return (static_cast<std::uint32_t>(bytes[0])<<24u) |
        (static_cast<std::uint32_t>(bytes[1])<<16u) |
        (static_cast<std::uint32_t>(bytes[2])<<8u) |
        static_cast<std::uint32_t>(bytes[3]);
}

} // namespace

ChronoMp4TransportDerivation deriveIso4IsomTransport(
    std::span<const std::uint8_t> sourceBytes
) {
    if (sourceBytes.size()<=FtypBytes)
        throw std::runtime_error("chrono MP4 is too short for the exact iso4 transport layout");
    if (readBigEndian32(sourceBytes)!=FtypBytes)
        throw std::runtime_error("chrono MP4 leading atom is not exactly 20 bytes");
    if (!equalsAt(sourceBytes,4u,Ftyp))
        throw std::runtime_error("chrono MP4 leading atom is not ftyp");
    if (!equalsAt(sourceBytes,MajorBrandOffset,Iso4))
        throw std::runtime_error("chrono MP4 major brand is not the expected iso4 source brand");
    // A 20-byte ftyp has exactly one compatible-brand lane. Requiring that
    // sole lane to be iso4 proves this exact source advertises no AOSP-listed
    // compatible brand before the bounded derivation.
    if (!equalsAt(sourceBytes,CompatibleBrandOffset,Iso4))
        throw std::runtime_error(
            "chrono MP4 sole compatible brand is not the expected unsupported iso4 brand");

    ChronoMp4TransportDerivation result;
    result.bytes.assign(sourceBytes.begin(),sourceBytes.end());
    result.originalCompatibleBrand=Iso4;
    result.replacementCompatibleBrand=Isom;
    result.ftypOffset=0u;
    result.ftypBytes=FtypBytes;
    result.compatibleBrandOffset=CompatibleBrandOffset;
    std::copy(Isom.begin(),Isom.end(),result.bytes.begin()+CompatibleBrandOffset);

    for (std::size_t offset=0u;offset<sourceBytes.size();++offset) {
        if (sourceBytes[offset]==result.bytes[offset]) continue;
        result.changedByteOffset=offset;
        ++result.changedByteCount;
    }
    if (result.bytes.size()!=sourceBytes.size() || result.changedByteCount!=1u ||
            result.changedByteOffset!=CompatibleBrandOffset+3u ||
            !std::equal(
                sourceBytes.begin()+FtypBytes,sourceBytes.end(),
                result.bytes.begin()+FtypBytes)) {
        throw std::runtime_error("chrono MP4 transport derivation exceeded the ftyp brand byte");
    }
    return result;
}

} // namespace kc
