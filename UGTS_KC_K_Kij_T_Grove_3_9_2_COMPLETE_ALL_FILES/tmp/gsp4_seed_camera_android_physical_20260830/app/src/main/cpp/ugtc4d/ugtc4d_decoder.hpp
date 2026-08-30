#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace ugts::chrono {

using Sha256Digest = std::array<std::uint8_t, 32>;

struct ContainerHeader {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::uint32_t frameCount = 0;
    std::uint32_t checkpointInterval = 0;
    std::int64_t firstSourcePts = 0;
    std::int64_t endSourcePtsExclusive = 0;
    std::uint64_t timeBaseNumerator = 0;
    std::uint64_t timeBaseDenominator = 0;
    double centerX = 0.0;
    double centerY = 0.0;
    double r0 = 0.0;
    double coreRadius = 0.0;
    double rhoMin = 0.0;
    double rhoMax = 0.0;
    std::uint32_t lutResolution = 0;
    Sha256Digest sourceSha256{};
    Sha256Digest decodedStreamSha256{};
};

struct FullVerification {
    std::size_t frames = 0;
    std::uint64_t decodedRgbBytes = 0;
    std::size_t predictor13Frames = 0;
    std::size_t predictor14Frames = 0;
    std::size_t predictor11Frames = 0;
};

struct DecodedFrame {
    std::uint32_t ordinal = 0;
    std::int64_t sourcePts = 0;
    std::int64_t sourceEndPtsExclusive = 0;
    std::uint32_t predictor = 0;
    std::uint32_t previousOrdinal = 0xffffffffu;
    std::vector<std::uint8_t> polarRgb;
    std::vector<std::uint8_t> cartesianRgb;
};

// Portable C++17 oracle for the exact UGTC4D 1.0 / UGFRM2 2.0 /
// UGRICE1 1.0 substrate profile. It intentionally has no MediaCodec, H.26x,
// AV1, ZIP, or other conventional media/container dependency.
class Ugtc4dDecoder final {
public:
    explicit Ugtc4dDecoder(std::vector<std::uint8_t> bytes);

    static Ugtc4dDecoder fromFile(const std::string& path);

    const ContainerHeader& header() const noexcept { return header_; }
    const std::vector<std::uint32_t>& traversal() const noexcept { return traversal_; }
    std::size_t frameCount() const noexcept { return frameSections_.size(); }
    std::uint32_t framePredictor(std::size_t frameIndex) const;
    FullVerification verifyAllFrames() const;

    // Predictor 11 requires the immediately named previous polar frame.
    // Independent predictor 13 must receive nullptr.
    DecodedFrame decodeFrame(
        std::size_t frameIndex,
        const DecodedFrame* previous = nullptr
    ) const;

private:
    struct SectionView {
        std::string kind;
        std::uint32_t version = 0;
        std::uint32_t flags = 0;
        std::uint64_t storedOffset = 0;
        std::uint64_t storedBytes = 0;
        std::uint64_t logicalBytes = 0;
        std::uint64_t recordStart = 0;
        std::uint64_t recordCount = 0;
    };

    struct PredictionPlan {
        std::vector<std::int32_t> parent;
        std::vector<std::int32_t> a;
        std::vector<std::int32_t> b;
        std::vector<std::int32_t> c;
        std::vector<std::uint8_t> useMedian;
    };

    std::vector<std::uint8_t> logicalSection(const SectionView& section) const;
    void parseContainer();
    void parseSubstrate();
    void buildPredictionPlan();

    std::vector<std::uint8_t> bytes_;
    ContainerHeader header_{};
    std::vector<SectionView> sections_;
    std::vector<SectionView> frameSections_;
    std::vector<std::uint8_t> uglut2_;
    std::vector<std::uint8_t> traversalRecipe_;
    Sha256Digest uglut2Digest_{};
    Sha256Digest traversalRecipeDigest_{};
    std::vector<std::uint32_t> traversal_;
    PredictionPlan predictionPlan_{};
};

Sha256Digest sha256(const std::uint8_t* data, std::size_t size);
std::string sha256Hex(const Sha256Digest& digest);

} // namespace ugts::chrono
