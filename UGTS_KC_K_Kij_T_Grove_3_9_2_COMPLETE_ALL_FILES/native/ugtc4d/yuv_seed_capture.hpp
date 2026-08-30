#pragma once

#include "seeded_uglut2_traversal.hpp"

#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace ugts::chrono {

constexpr std::uint32_t Ugcode24_420Profile = 1u;
constexpr std::uint64_t Gsp4CameraLineageNamespace = 0x7f0b2a27a8c27f83ull;

enum class YuvPredictorProgram : std::uint32_t {
    GeneratedAddressSpatialMed = 1u,
    PreviousSameAddress = 2u,
    TemporalPlusSpatialMedDifference = 3u,
    RawExactLane = 4u,
};

struct Gsp4CodewordLineage {
    std::uint32_t lineageSeed = 0;
    std::uint32_t routedHash = 0;
};

struct ByteView {
    const std::uint8_t* data = nullptr;
    std::size_t size = 0;
};

struct Plane8View {
    const std::uint8_t* data = nullptr;
    std::size_t size = 0;
    std::uint32_t rowStride = 0;
    std::uint32_t pixelStride = 0;
};

struct Yuv420p8FrameView {
    std::int64_t sensorTimestampNs = 0;
    std::int64_t frameNumber = -1;
    Plane8View y;
    Plane8View u;
    Plane8View v;
    // Versioned canonical camera metadata authored by the platform adapter.
    // The core stores and hashes these bytes verbatim; an empty view is valid.
    ByteView canonicalMetadata;
};

struct DenseYuv420p8Frame {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::int64_t sensorTimestampNs = 0;
    std::int64_t frameNumber = -1;
    std::vector<std::uint8_t> y;
    std::vector<std::uint8_t> u;
    std::vector<std::uint8_t> v;
    std::vector<std::uint8_t> canonicalMetadata;
};

struct YuvSeedCaptureAppendStats {
    std::uint64_t ordinal = 0;
    std::uint64_t logicalLaneCount = 0;
    std::uint64_t noveltyEventCount = 0;
    std::uint64_t noveltyPayloadBytes = 0;
    std::uint64_t frameRecordBytes = 0;
    std::uint32_t zeroBlockCount = 0;
    std::uint32_t denseBlockCount = 0;
    std::uint32_t sparseBitmaskBlockCount = 0;
    std::uint32_t sparseGapBlockCount = 0;
    // Execution tuning is deliberately not serialized into UGYUVS1. These
    // fields expose the bounded authoring configuration used for this append.
    std::uint32_t noveltyWorkerCount = 1;
    std::uint32_t noveltyMaxInFlightBlocks = 1;
    Sha256Digest preSubstrateSha256{};
};

struct YuvSeedCaptureProfile {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::uint32_t checkpointInterval = 30;
    std::uint32_t noveltyBlockLumaAddresses = 65536;
    // Fixed execution-only bounds. They never enter the seed recipe or file
    // ABI, so every valid worker/window choice must emit identical bytes.
    std::uint32_t noveltyWorkerCount = 1;
    std::uint32_t noveltyMaxInFlightBlocks = 1;
    std::uint64_t rootSeed = 0;
    std::uint64_t traversalRecipeSeed = 1;
    std::vector<std::uint8_t> literalUglut2;
};

struct YuvSeedCaptureInspection {
    std::uint32_t profile = Ugcode24_420Profile;
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::uint64_t committedFrames = 0;
    std::uint64_t committedBytes = 0;
    std::uint64_t generation = 0;
    bool finalized = false;
    bool recoveredIncomplete = false;
    std::uint64_t uncommittedTailBytes = 0;
    Sha256Digest uglut2Sha256{};
    Sha256Digest traversalSha256{};
    Sha256Digest terminalRecordSha256{};
};

class YuvSeedCaptureWriter final {
public:
    static std::unique_ptr<YuvSeedCaptureWriter> createPartial(
        const std::string& partialPath,
        const YuvSeedCaptureProfile& profile
    );

    ~YuvSeedCaptureWriter();
    YuvSeedCaptureWriter(const YuvSeedCaptureWriter&) = delete;
    YuvSeedCaptureWriter& operator=(const YuvSeedCaptureWriter&) = delete;

    YuvSeedCaptureAppendStats append(const Yuv420p8FrameView& frame);
    // GPU/accelerator ingress for the same lossless writer. Residual bytes
    // must follow seeded traversal order: Y for every luma address, then U,V
    // immediately after each even-x/even-y chroma-owner address. Each lane is
    // modular uint8(current - zero/previous), with no padding or headers.
    YuvSeedCaptureAppendStats appendPreparedResidual(
        const Yuv420p8FrameView& frame,
        ByteView canonicalOwnerResidual
    );
    std::uint64_t frameCount() const noexcept;

    // Durably commits FINAL before an atomic same-filesystem rename.
    void finalize(const std::string& finalPath);

private:
    struct Impl;
    explicit YuvSeedCaptureWriter(std::unique_ptr<Impl> impl);
    YuvSeedCaptureAppendStats appendImpl(
        const Yuv420p8FrameView& frame,
        const ByteView* preparedResidual
    );
    std::unique_ptr<Impl> impl_;
};

class YuvSeedCaptureReader final {
public:
    explicit YuvSeedCaptureReader(const std::string& path);

    const YuvSeedCaptureInspection& inspection() const noexcept { return inspection_; }
    void replay(const std::function<void(const DenseYuv420p8Frame&)>& consume) const;
    std::vector<DenseYuv420p8Frame> decodeAll() const;

private:
    struct Impl;
    std::shared_ptr<Impl> impl_;
    YuvSeedCaptureInspection inspection_{};
};

// Expand the logical luma-addressed codeword view exactly as:
// [Y(x,y), U(floor(x/2),floor(y/2)), V(floor(x/2),floor(y/2))].
std::vector<std::uint8_t> expandUgcode24_420(const DenseYuv420p8Frame& frame);

// SHA256(LE64(sensor PTS) || LE32(width) || LE32(height) || Y || U || V).
Sha256Digest preSubstrateFrameSha256(const DenseYuv420p8Frame& frame);

// Exact UGTS-GN 1.1 route mixer and seed/address-derived camera lineage.
std::uint32_t gsp4Mix32(std::uint32_t value) noexcept;
Gsp4CodewordLineage gsp4CodewordLineage(
    std::uint64_t rootSeed,
    std::uint64_t recipeSeed,
    std::uint64_t cartesianAddress,
    std::uint32_t frameOrdinal
) noexcept;

} // namespace ugts::chrono
