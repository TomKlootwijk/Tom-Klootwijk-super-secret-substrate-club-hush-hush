#pragma once

#include "chrono_capture_sha256.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <span>
#include <string>
#include <vector>

namespace kc {

constexpr std::size_t ChronoCameraMetadataBytes=128u;

enum ChronoCameraMetadataPresence : std::uint64_t {
    ChronoMetadataFrameNumber=1ull<<0u,
    ChronoMetadataExposureTime=1ull<<1u,
    ChronoMetadataFrameDuration=1ull<<2u,
    ChronoMetadataRollingShutterSkew=1ull<<3u,
    ChronoMetadataSensitivity=1ull<<4u,
    ChronoMetadataFocalLength=1ull<<5u,
    ChronoMetadataFocusDistance=1ull<<6u,
    ChronoMetadataAperture=1ull<<7u,
    ChronoMetadataCropRegion=1ull<<8u,
    ChronoMetadataAeState=1ull<<9u,
    ChronoMetadataAfState=1ull<<10u,
    ChronoMetadataAwbState=1ull<<11u,
    ChronoMetadataLensState=1ull<<12u,
    ChronoMetadataAeCompensation=1ull<<13u,
    ChronoMetadataPostRawSensitivityBoost=1ull<<14u,
};

struct ChronoCameraMetadata {
    std::uint64_t presence=0;
    std::int64_t sensorTimestampNs=0;
    std::int64_t frameNumber=-1;
    std::uint64_t captureOrdinal=0;
    std::int64_t exposureTimeNs=0;
    std::int64_t frameDurationNs=0;
    std::int64_t rollingShutterSkewNs=0;
    std::int32_t sensitivityIso=0;
    float focalLengthMm=0.0f;
    float focusDistanceDiopters=0.0f;
    float aperture=0.0f;
    std::array<std::int32_t,4> cropRegion{};
    std::uint8_t aeState=0;
    std::uint8_t afState=0;
    std::uint8_t awbState=0;
    std::uint8_t lensState=0;
    std::int32_t aeCompensation=0;
    std::int32_t postRawSensitivityBoost=0;
};

std::array<std::uint8_t,ChronoCameraMetadataBytes> serializeChronoCameraMetadata(
    const ChronoCameraMetadata& metadata
);

enum class ChronoCaptureError : std::uint8_t {
    None=0,
    QueuePressure,
    MetadataPressure,
    NonMonotonicTimestamp,
    InvalidImage,
    CaptureFailure,
    BufferLost,
    CameraDisconnected,
    CameraDevice,
    WriterFailure,
};

const char* chronoCaptureErrorName(ChronoCaptureError error);

struct ChronoDenseYuvWriteView {
    std::size_t slot=0;
    std::uint64_t ordinal=0;
    std::int64_t sensorTimestampNs=0;
    std::span<std::uint8_t> y;
    std::span<std::uint8_t> u;
    std::span<std::uint8_t> v;
};

struct ChronoDenseYuvReadView {
    std::size_t slot=0;
    std::uint64_t ordinal=0;
    std::int64_t sensorTimestampNs=0;
    std::int64_t frameNumber=-1;
    std::span<const std::uint8_t> y;
    std::span<const std::uint8_t> u;
    std::span<const std::uint8_t> v;
    ChronoSha256Digest ySha256{};
    ChronoSha256Digest uSha256{};
    ChronoSha256Digest vSha256{};
    ChronoSha256Digest preSubstrateSha256{};
    std::span<const std::uint8_t> canonicalMetadata;
    ChronoSha256Digest metadataSha256{};
};

struct ChronoCaptureQueueStats {
    std::uint64_t reservedFrames=0;
    std::uint64_t readyFrames=0;
    std::uint64_t releasedFrames=0;
    std::uint64_t pressureStops=0;
    std::size_t highWater=0;
    ChronoCaptureError error=ChronoCaptureError::None;
    std::string errorDetail;
};

class ChronoCaptureFrameQueue final {
public:
    bool configure(std::uint32_t width,std::uint32_t height,std::uint16_t capacity);
    bool beginWrite(std::int64_t sensorTimestampNs,ChronoDenseYuvWriteView& view);
    bool completeWrite(std::size_t slot);
    void abortWrite(std::size_t slot,ChronoCaptureError error,const char* detail);
    bool attachMetadata(const ChronoCameraMetadata& metadata);
    // Run on an encoder/worker thread, never in the AImageReader callback.
    bool prepareNextCaptured();
    bool acquireReady(ChronoDenseYuvReadView& view);
    void releaseRead(std::size_t slot);
    void fail(ChronoCaptureError error,const char* detail);
    ChronoCaptureQueueStats stats() const;
    bool failed() const;
    std::uint32_t width() const { return width_; }
    std::uint32_t height() const { return height_; }

private:
    enum class SlotState : std::uint8_t {
        Empty,Writing,AwaitingMetadata,Captured,Hashing,Ready,Reading
    };
    struct Slot {
        SlotState state=SlotState::Empty;
        std::uint64_t ordinal=0;
        std::int64_t sensorTimestampNs=0;
        std::vector<std::uint8_t> dense;
        ChronoSha256Digest ySha256{};
        ChronoSha256Digest uSha256{};
        ChronoSha256Digest vSha256{};
        ChronoSha256Digest preSubstrateSha256{};
        std::array<std::uint8_t,ChronoCameraMetadataBytes> metadataBytes{};
        ChronoSha256Digest metadataSha256{};
        std::int64_t frameNumber=-1;
        bool metadataPresent=false;
    };
    struct PendingMetadata {
        bool used=false;
        ChronoCameraMetadata metadata{};
    };

    void failLocked(ChronoCaptureError error,const char* detail);
    std::size_t occupiedLocked() const;
    std::span<std::uint8_t> plane(Slot& slot,std::size_t index);
    std::span<const std::uint8_t> plane(const Slot& slot,std::size_t index) const;
    bool applyMetadataLocked(Slot& slot,const ChronoCameraMetadata& metadata);

    mutable std::mutex mutex_;
    std::uint32_t width_=0,height_=0;
    std::size_t yBytes_=0,chromaBytes_=0;
    std::vector<Slot> slots_;
    std::vector<PendingMetadata> pendingMetadata_;
    std::uint64_t nextOrdinal_=0,nextPrepareOrdinal_=0,nextReadOrdinal_=0;
    std::int64_t lastReservedTimestamp_=0;
    ChronoCaptureQueueStats stats_{};
};

} // namespace kc
