#include "chrono_capture_queue.hpp"

#include <algorithm>
#include <cstring>
#include <limits>
#include <stdexcept>

namespace kc {
namespace {

void putU16(std::span<std::uint8_t> output,std::size_t offset,std::uint16_t value) {
    output[offset]=static_cast<std::uint8_t>(value);
    output[offset+1u]=static_cast<std::uint8_t>(value>>8u);
}
void putU32(std::span<std::uint8_t> output,std::size_t offset,std::uint32_t value) {
    for (std::size_t index=0;index<4u;++index)
        output[offset+index]=static_cast<std::uint8_t>(value>>(index*8u));
}
void putU64(std::span<std::uint8_t> output,std::size_t offset,std::uint64_t value) {
    for (std::size_t index=0;index<8u;++index)
        output[offset+index]=static_cast<std::uint8_t>(value>>(index*8u));
}
void putI32(std::span<std::uint8_t> output,std::size_t offset,std::int32_t value) {
    putU32(output,offset,static_cast<std::uint32_t>(value));
}
void putI64(std::span<std::uint8_t> output,std::size_t offset,std::int64_t value) {
    putU64(output,offset,static_cast<std::uint64_t>(value));
}
void putF32(std::span<std::uint8_t> output,std::size_t offset,float value) {
    std::uint32_t bits=0;
    static_assert(sizeof(bits)==sizeof(value));
    std::memcpy(&bits,&value,sizeof(bits));
    putU32(output,offset,bits);
}

} // namespace

std::array<std::uint8_t,ChronoCameraMetadataBytes> serializeChronoCameraMetadata(
    const ChronoCameraMetadata& metadata
) {
    std::array<std::uint8_t,ChronoCameraMetadataBytes> result{};
    const std::span<std::uint8_t> output(result);
    std::memcpy(output.data(),"UGCAMD1\0",8u);
    putU32(output,8u,0x01020304u);
    putU16(output,12u,1u);
    putU16(output,14u,static_cast<std::uint16_t>(ChronoCameraMetadataBytes));
    putU64(output,16u,metadata.presence);
    putI64(output,24u,metadata.sensorTimestampNs);
    putI64(output,32u,metadata.frameNumber);
    putU64(output,40u,metadata.captureOrdinal);
    putI64(output,48u,metadata.exposureTimeNs);
    putI64(output,56u,metadata.frameDurationNs);
    putI64(output,64u,metadata.rollingShutterSkewNs);
    putI32(output,72u,metadata.sensitivityIso);
    putF32(output,76u,metadata.focalLengthMm);
    putF32(output,80u,metadata.focusDistanceDiopters);
    putF32(output,84u,metadata.aperture);
    for (std::size_t index=0;index<metadata.cropRegion.size();++index)
        putI32(output,88u+index*4u,metadata.cropRegion[index]);
    output[104u]=metadata.aeState;
    output[105u]=metadata.afState;
    output[106u]=metadata.awbState;
    output[107u]=metadata.lensState;
    putI32(output,108u,metadata.aeCompensation);
    putI32(output,112u,metadata.postRawSensitivityBoost);
    // Bytes 116..127 are reserved zero for forward-compatible fixed-width v1.
    return result;
}

const char* chronoCaptureErrorName(ChronoCaptureError error) {
    switch (error) {
        case ChronoCaptureError::None: return "none";
        case ChronoCaptureError::QueuePressure: return "queue_pressure";
        case ChronoCaptureError::MetadataPressure: return "metadata_pressure";
        case ChronoCaptureError::NonMonotonicTimestamp: return "non_monotonic_timestamp";
        case ChronoCaptureError::InvalidImage: return "invalid_image";
        case ChronoCaptureError::CaptureFailure: return "capture_failure";
        case ChronoCaptureError::BufferLost: return "buffer_lost";
        case ChronoCaptureError::CameraDisconnected: return "camera_disconnected";
        case ChronoCaptureError::CameraDevice: return "camera_device";
        case ChronoCaptureError::WriterFailure: return "writer_failure";
    }
    return "unknown";
}

bool ChronoCaptureFrameQueue::configure(
    std::uint32_t width,std::uint32_t height,std::uint16_t capacity
) {
    if (width==0u || height==0u || (width&1u)!=0u || (height&1u)!=0u ||
        capacity<3u || capacity>16u) return false;
    const auto y64=static_cast<std::uint64_t>(width)*height;
    const auto chroma64=static_cast<std::uint64_t>(width/2u)*(height/2u);
    if (y64+2u*chroma64>std::numeric_limits<std::size_t>::max()) return false;
    std::scoped_lock lock(mutex_);
    width_=width;
    height_=height;
    yBytes_=static_cast<std::size_t>(y64);
    chromaBytes_=static_cast<std::size_t>(chroma64);
    slots_.clear();
    slots_.resize(capacity);
    for (auto& slot:slots_) slot.dense.resize(yBytes_+2u*chromaBytes_);
    pendingMetadata_.clear();
    pendingMetadata_.resize(static_cast<std::size_t>(capacity)*2u);
    nextOrdinal_=0u;
    nextPrepareOrdinal_=0u;
    nextReadOrdinal_=0u;
    lastReservedTimestamp_=0;
    stats_={};
    return true;
}

std::span<std::uint8_t> ChronoCaptureFrameQueue::plane(Slot& slot,std::size_t index) {
    if (index==0u) return {slot.dense.data(),yBytes_};
    if (index==1u) return {slot.dense.data()+yBytes_,chromaBytes_};
    return {slot.dense.data()+yBytes_+chromaBytes_,chromaBytes_};
}

std::span<const std::uint8_t> ChronoCaptureFrameQueue::plane(
    const Slot& slot,std::size_t index
) const {
    if (index==0u) return {slot.dense.data(),yBytes_};
    if (index==1u) return {slot.dense.data()+yBytes_,chromaBytes_};
    return {slot.dense.data()+yBytes_+chromaBytes_,chromaBytes_};
}

std::size_t ChronoCaptureFrameQueue::occupiedLocked() const {
    return static_cast<std::size_t>(std::count_if(
        slots_.begin(),slots_.end(),
        [](const Slot& slot){ return slot.state!=SlotState::Empty; }
    ));
}

void ChronoCaptureFrameQueue::failLocked(ChronoCaptureError error,const char* detail) {
    if (stats_.error!=ChronoCaptureError::None) return;
    stats_.error=error;
    stats_.errorDetail=detail?detail:"";
    if (error==ChronoCaptureError::QueuePressure) ++stats_.pressureStops;
}

void ChronoCaptureFrameQueue::fail(ChronoCaptureError error,const char* detail) {
    std::scoped_lock lock(mutex_);
    failLocked(error,detail);
}

bool ChronoCaptureFrameQueue::beginWrite(
    std::int64_t sensorTimestampNs,ChronoDenseYuvWriteView& view
) {
    std::scoped_lock lock(mutex_);
    if (stats_.error!=ChronoCaptureError::None) return false;
    if (sensorTimestampNs<=0 ||
        (lastReservedTimestamp_!=0 && sensorTimestampNs<=lastReservedTimestamp_)) {
        failLocked(ChronoCaptureError::NonMonotonicTimestamp,
            "AImage sensor timestamp is not strictly increasing");
        return false;
    }
    const auto iterator=std::find_if(
        slots_.begin(),slots_.end(),[](const Slot& slot){ return slot.state==SlotState::Empty; }
    );
    if (iterator==slots_.end()) {
        failLocked(ChronoCaptureError::QueuePressure,
            "all preallocated lossless capture slots are occupied");
        return false;
    }
    auto& slot=*iterator;
    slot.state=SlotState::Writing;
    slot.ordinal=nextOrdinal_++;
    slot.sensorTimestampNs=sensorTimestampNs;
    slot.frameNumber=-1;
    slot.metadataPresent=false;
    lastReservedTimestamp_=sensorTimestampNs;
    ++stats_.reservedFrames;
    stats_.highWater=std::max(stats_.highWater,occupiedLocked());
    const auto slotIndex=static_cast<std::size_t>(iterator-slots_.begin());
    view={slotIndex,slot.ordinal,sensorTimestampNs,plane(slot,0u),plane(slot,1u),plane(slot,2u)};
    return true;
}

bool ChronoCaptureFrameQueue::completeWrite(std::size_t slotIndex) {
    if (slotIndex>=slots_.size()) return false;
    auto& slot=slots_[slotIndex];
    std::scoped_lock lock(mutex_);
    if (slot.state!=SlotState::Writing) return false;
    for (auto& pending:pendingMetadata_) {
        if (!pending.used || pending.metadata.sensorTimestampNs!=slot.sensorTimestampNs) continue;
        applyMetadataLocked(slot,pending.metadata);
        pending.used=false;
        break;
    }
    slot.state=slot.metadataPresent?SlotState::Captured:SlotState::AwaitingMetadata;
    return true;
}

void ChronoCaptureFrameQueue::abortWrite(
    std::size_t slotIndex,ChronoCaptureError error,const char* detail
) {
    std::scoped_lock lock(mutex_);
    if (slotIndex<slots_.size() && slots_[slotIndex].state==SlotState::Writing)
        slots_[slotIndex].state=SlotState::Empty;
    failLocked(error,detail);
}

bool ChronoCaptureFrameQueue::applyMetadataLocked(
    Slot& slot,const ChronoCameraMetadata& source
) {
    auto metadata=source;
    metadata.captureOrdinal=slot.ordinal;
    slot.metadataBytes=serializeChronoCameraMetadata(metadata);
    slot.metadataSha256=chronoCaptureSha256(slot.metadataBytes);
    slot.frameNumber=metadata.frameNumber;
    slot.metadataPresent=true;
    if (slot.state==SlotState::AwaitingMetadata) slot.state=SlotState::Captured;
    return true;
}

bool ChronoCaptureFrameQueue::attachMetadata(const ChronoCameraMetadata& metadata) {
    std::scoped_lock lock(mutex_);
    if (stats_.error!=ChronoCaptureError::None) return false;
    if (metadata.sensorTimestampNs<=0) {
        failLocked(ChronoCaptureError::InvalidImage,"capture result lacks sensor timestamp");
        return false;
    }
    for (auto& slot:slots_) {
        if (slot.state==SlotState::Empty || slot.state==SlotState::Reading ||
            slot.state==SlotState::Hashing || slot.state==SlotState::Ready ||
            slot.sensorTimestampNs!=metadata.sensorTimestampNs) continue;
        if (slot.metadataPresent) {
            failLocked(ChronoCaptureError::InvalidImage,"duplicate Camera2 metadata timestamp");
            return false;
        }
        return applyMetadataLocked(slot,metadata);
    }
    const auto pending=std::find_if(
        pendingMetadata_.begin(),pendingMetadata_.end(),
        [](const PendingMetadata& item){ return !item.used; }
    );
    if (pending==pendingMetadata_.end()) {
        failLocked(ChronoCaptureError::MetadataPressure,
            "capture metadata outran the bounded image correlation table");
        return false;
    }
    pending->used=true;
    pending->metadata=metadata;
    return true;
}

bool ChronoCaptureFrameQueue::prepareNextCaptured() {
    std::size_t slotIndex=0;
    {
        std::scoped_lock lock(mutex_);
        const auto iterator=std::find_if(slots_.begin(),slots_.end(),[this](const Slot& slot){
            return slot.ordinal==nextPrepareOrdinal_ && slot.state==SlotState::Captured;
        });
        if (iterator==slots_.end()) return false;
        iterator->state=SlotState::Hashing;
        slotIndex=static_cast<std::size_t>(iterator-slots_.begin());
    }
    auto& slot=slots_[slotIndex];
    slot.ySha256=chronoCaptureSha256(plane(slot,0u));
    slot.uSha256=chronoCaptureSha256(plane(slot,1u));
    slot.vSha256=chronoCaptureSha256(plane(slot,2u));
    std::array<std::uint8_t,16> framePrefix{};
    putU64(framePrefix,0u,static_cast<std::uint64_t>(slot.sensorTimestampNs));
    putU32(framePrefix,8u,width_);
    putU32(framePrefix,12u,height_);
    ChronoSha256 preSubstrateHasher;
    preSubstrateHasher.update(framePrefix);
    preSubstrateHasher.update(slot.dense);
    slot.preSubstrateSha256=preSubstrateHasher.finish();
    {
        std::scoped_lock lock(mutex_);
        if (slot.state!=SlotState::Hashing) return false;
        slot.state=SlotState::Ready;
        ++nextPrepareOrdinal_;
        ++stats_.readyFrames;
    }
    return true;
}

bool ChronoCaptureFrameQueue::acquireReady(ChronoDenseYuvReadView& view) {
    std::scoped_lock lock(mutex_);
    const auto iterator=std::find_if(slots_.begin(),slots_.end(),[this](const Slot& slot){
        return slot.ordinal==nextReadOrdinal_ && slot.state==SlotState::Ready;
    });
    if (iterator==slots_.end()) return false;
    auto& slot=*iterator;
    slot.state=SlotState::Reading;
    const auto slotIndex=static_cast<std::size_t>(iterator-slots_.begin());
    view.slot=slotIndex;
    view.ordinal=slot.ordinal;
    view.sensorTimestampNs=slot.sensorTimestampNs;
    view.frameNumber=slot.frameNumber;
    view.y=plane(slot,0u);
    view.u=plane(slot,1u);
    view.v=plane(slot,2u);
    view.ySha256=slot.ySha256;
    view.uSha256=slot.uSha256;
    view.vSha256=slot.vSha256;
    view.preSubstrateSha256=slot.preSubstrateSha256;
    view.canonicalMetadata=slot.metadataBytes;
    view.metadataSha256=slot.metadataSha256;
    return true;
}

void ChronoCaptureFrameQueue::releaseRead(std::size_t slotIndex) {
    std::scoped_lock lock(mutex_);
    if (slotIndex>=slots_.size() || slots_[slotIndex].state!=SlotState::Reading)
        throw std::logic_error("releaseRead called without an acquired chrono capture slot");
    auto& slot=slots_[slotIndex];
    if (slot.ordinal!=nextReadOrdinal_)
        throw std::logic_error("chrono capture slots must be released in ordinal order");
    slot.state=SlotState::Empty;
    slot.metadataPresent=false;
    ++nextReadOrdinal_;
    ++stats_.releasedFrames;
}

ChronoCaptureQueueStats ChronoCaptureFrameQueue::stats() const {
    std::scoped_lock lock(mutex_);
    return stats_;
}

bool ChronoCaptureFrameQueue::failed() const {
    std::scoped_lock lock(mutex_);
    return stats_.error!=ChronoCaptureError::None;
}

} // namespace kc
