#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace kc {

constexpr std::uint32_t ChronoMediaOriginalSource=1u<<0u;
constexpr std::uint32_t ChronoMediaDerivedPolarPreview=1u<<1u;
constexpr std::uint32_t ChronoApplyUgcvLutQ8=1u<<2u;
constexpr std::uint32_t ChronoAlreadyLogPolar=1u<<3u;
constexpr std::uint32_t ChronoLoop=1u<<4u;

struct ChronoVideoPtsEntry {
    std::uint32_t mediaIndex=0;
    std::uint32_t sourceFrameIndex=0;
    std::int64_t sourcePts=0;
    std::int64_t displayUntilSourcePts=0;
};

struct ChronoVideoTimeline {
    std::uint32_t flags=0;
    std::uint32_t mediaWidth=0;
    std::uint32_t mediaHeight=0;
    std::uint32_t sourceFrameCount=0;
    std::int64_t firstSourcePts=0;
    std::int64_t endSourcePtsExclusive=0;
    std::uint64_t timeBaseNumerator=0;
    std::uint64_t timeBaseDenominator=0;
    std::array<std::uint8_t,32> sourceSha256{};
    std::array<std::uint8_t,32> profileSha256{};
    std::array<std::uint8_t,32> mediaSha256{};
    std::array<std::uint8_t,32> contentSha256{};
    std::vector<ChronoVideoPtsEntry> entries;

    void load(const std::vector<std::uint8_t>& bytes);
    bool originalSource() const { return (flags&ChronoMediaOriginalSource)!=0u; }
    bool derivedPreview() const { return (flags&ChronoMediaDerivedPolarPreview)!=0u; }
    bool applyLut() const { return (flags&ChronoApplyUgcvLutQ8)!=0u; }
    bool alreadyLogPolar() const { return (flags&ChronoAlreadyLogPolar)!=0u; }
    bool loop() const { return (flags&ChronoLoop)!=0u; }

    // Convert exact source-clock PTS to MediaCodec's microsecond clock. Version
    // 1 intentionally rejects a value that is not exactly representable.
    std::int64_t exactMediaTimeUs(std::int64_t sourcePts) const;
    std::size_t selectForElapsedNanoseconds(std::uint64_t elapsedNanoseconds) const;
};

std::array<std::uint8_t,32> chronoSha256(std::span<const std::uint8_t> bytes);

} // namespace kc
