#include "chrono_seed_capture_session.hpp"
#include "chrono_vulkan_residual.hpp"

#include <android/log.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cstring>
#include <exception>
#include <limits>
#include <span>
#include <stdexcept>
#include <unistd.h>

#define KC_SEED_LOGI(...) __android_log_print(ANDROID_LOG_INFO,"UGTS-KC392-SEED",__VA_ARGS__)
#define KC_SEED_LOGE(...) __android_log_print(ANDROID_LOG_ERROR,"UGTS-KC392-SEED",__VA_ARGS__)

namespace kc {
namespace {

constexpr std::size_t RawSpoolHeaderBytes=128u;
constexpr std::size_t RawSpoolFrameHeaderBytes=208u;

void putU32(std::span<std::uint8_t> output,std::size_t offset,std::uint32_t value) {
    for (std::size_t index=0;index<4u;++index)
        output[offset+index]=static_cast<std::uint8_t>(value>>(index*8u));
}
void putU64(std::span<std::uint8_t> output,std::size_t offset,std::uint64_t value) {
    for (std::size_t index=0;index<8u;++index)
        output[offset+index]=static_cast<std::uint8_t>(value>>(index*8u));
}
void putI64(std::span<std::uint8_t> output,std::size_t offset,std::int64_t value) {
    putU64(output,offset,static_cast<std::uint64_t>(value));
}
std::uint32_t getU32(std::span<const std::uint8_t> input,std::size_t offset) {
    std::uint32_t value=0;
    for (std::size_t index=0;index<4u;++index)
        value|=static_cast<std::uint32_t>(input[offset+index])<<(index*8u);
    return value;
}
std::uint64_t getU64(std::span<const std::uint8_t> input,std::size_t offset) {
    std::uint64_t value=0;
    for (std::size_t index=0;index<8u;++index)
        value|=static_cast<std::uint64_t>(input[offset+index])<<(index*8u);
    return value;
}
std::int64_t getI64(std::span<const std::uint8_t> input,std::size_t offset) {
    return static_cast<std::int64_t>(getU64(input,offset));
}
bool writeExact(std::FILE* file,std::span<const std::uint8_t> bytes) {
    return bytes.empty() || std::fwrite(bytes.data(),1u,bytes.size(),file)==bytes.size();
}
bool readExact(std::FILE* file,std::span<std::uint8_t> bytes) {
    return bytes.empty() || std::fread(bytes.data(),1u,bytes.size(),file)==bytes.size();
}
ChronoSha256Digest readDigest(std::span<const std::uint8_t> input,std::size_t offset) {
    ChronoSha256Digest result{};
    std::copy_n(input.begin()+static_cast<std::ptrdiff_t>(offset),result.size(),result.begin());
    return result;
}

} // namespace

ChronoSeedCaptureSession::~ChronoSeedCaptureSession() { abort(); }

bool ChronoSeedCaptureSession::configure(
    ANativeActivity* activity,
    const ChronoSceneBinding& binding,
    std::vector<std::uint8_t> literalUglut2
) {
    abort();
    if (!activity || !activity->internalDataPath ||
        binding.mode!=ChronoSceneMode::Recorder || literalUglut2.empty() ||
        chronoCaptureSha256(literalUglut2)!=binding.uglut2Sha256 ||
        !camera_.configure(activity,binding)) return false;
    activity_=activity;
    binding_=binding;
    literalUglut2_=std::move(literalUglut2);
    finalPath_=std::string(activity->internalDataPath)+"/"+binding.outputBasename;
    partialPath_=finalPath_+".partial";
    rawSpoolPath_=finalPath_+".camera-exact.spool.partial";
    startRequested_.store(false,std::memory_order_release);
    writerStopRequested_.store(false,std::memory_order_release);
    writerFailed_.store(false,std::memory_order_release);
    state_.store(ChronoSeedCaptureState::Configured,std::memory_order_release);
    KC_SEED_LOGI(
        "scene-owned seed capture configured node=%u final=%s autostart=%s "
        "profile=UGCAMNODE_FX1_FULL_SUBSTRATE authority=CAMERA2_DENSE_YUV420",
        binding.nodeIndex,finalPath_.c_str(),binding.autostart?"true":"false"
    );
    return true;
}

bool ChronoSeedCaptureSession::requestStart() {
    const auto current=state();
    if (current==ChronoSeedCaptureState::Capturing ||
        current==ChronoSeedCaptureState::AwaitingPermission) return true;
    // A completed capture owns a finalized immutable stream and this queue's
    // ordinals have already advanced. A second take must be an explicit scene
    // reconfiguration, never an accidental overwrite of the same basename.
    if (current!=ChronoSeedCaptureState::Configured) return false;
    startRequested_.store(true,std::memory_order_release);
    if (!camera_.hasPermission()) {
        camera_.requestPermission();
        state_.store(ChronoSeedCaptureState::AwaitingPermission,std::memory_order_release);
        return true;
    }
    return startAuthorized();
}

bool ChronoSeedCaptureSession::startAuthorized() {
    try {
        if (!openRawSpool()) throw std::runtime_error(
            "could not create the exact Camera2 raw spool");
        writerStopRequested_.store(false,std::memory_order_release);
        writerFailed_.store(false,std::memory_order_release);
        writerThread_=std::thread(&ChronoSeedCaptureSession::runSpoolWriter,this);
        if (!camera_.start()) {
            writerStopRequested_.store(true,std::memory_order_release);
            camera_.frames().wake();
            joinWriter();
            closeRawSpool();
            fail("Camera2 failed after the seed writer was prepared");
            return false;
        }
        state_.store(ChronoSeedCaptureState::Capturing,std::memory_order_release);
        KC_SEED_LOGI(
            "exact Camera2 raw spool started path=%s; UGYUVS1 transcode is post-capture",
            rawSpoolPath_.c_str());
        return true;
    } catch (const std::exception& error) {
        closeRawSpool();
        writer_.reset();
        fail(error.what());
        return false;
    }
}

bool ChronoSeedCaptureSession::openRawSpool() {
    rawSpool_=std::fopen(rawSpoolPath_.c_str(),"wb+");
    if (!rawSpool_) return false;
    static_cast<void>(std::setvbuf(rawSpool_,nullptr,_IOFBF,1u<<20u));
    std::array<std::uint8_t,RawSpoolHeaderBytes> header{};
    std::memcpy(header.data(),"UGRAWS1\0",8u);
    putU32(header,8u,0x01020304u);
    putU32(header,12u,1u);
    putU32(header,16u,RawSpoolHeaderBytes);
    putU32(header,20u,binding_.width);
    putU32(header,24u,binding_.height);
    putU32(header,28u,ChronoCameraMetadataBytes);
    putU64(header,32u,binding_.rootSeed);
    putU64(header,40u,binding_.recipeSeed);
    std::copy(binding_.uglut2Sha256.begin(),binding_.uglut2Sha256.end(),header.begin()+48u);
    putU64(header,80u,0u); // Rewritten and fsync'd only after every slot is drained.
    putU32(header,88u,RawSpoolFrameHeaderBytes);
    spooledFrames_=0u;
    if (writeExact(rawSpool_,header)) return true;
    std::fclose(rawSpool_);
    rawSpool_=nullptr;
    return false;
}

bool ChronoSeedCaptureSession::closeRawSpool() {
    if (!rawSpool_) return true;
    std::array<std::uint8_t,8> count{};
    putU64(count,0u,spooledFrames_);
    bool okay=std::fflush(rawSpool_)==0 && std::fseek(rawSpool_,80,SEEK_SET)==0 &&
        writeExact(rawSpool_,count) && std::fflush(rawSpool_)==0;
    if (okay) okay=::fsync(::fileno(rawSpool_))==0;
    if (std::fclose(rawSpool_)!=0) okay=false;
    rawSpool_=nullptr;
    return okay;
}

void ChronoSeedCaptureSession::runSpoolWriter() {
    try {
        auto& queue=camera_.frames();
        for (;;) {
            bool progressed=false;
            while (queue.prepareNextCaptured()) progressed=true;
            ChronoDenseYuvReadView frame;
            while (queue.acquireReady(frame)) {
                std::array<std::uint8_t,RawSpoolFrameHeaderBytes> header{};
                std::memcpy(header.data(),"UGRFRM1\0",8u);
                putU64(header,8u,frame.ordinal);
                putI64(header,16u,frame.sensorTimestampNs);
                putI64(header,24u,frame.frameNumber);
                // Bytes 32..159 are reserved zero: the time-critical spool
                // performs no full-plane hashing. Exact hashes are computed
                // during read-back and bound into UGYUVS1 before replay.
                std::copy(frame.metadataSha256.begin(),frame.metadataSha256.end(),
                    header.begin()+160u);
                putU32(header,192u,static_cast<std::uint32_t>(frame.canonicalMetadata.size()));
                putU32(header,196u,static_cast<std::uint32_t>(frame.y.size()));
                putU32(header,200u,static_cast<std::uint32_t>(frame.u.size()));
                putU32(header,204u,static_cast<std::uint32_t>(frame.v.size()));
                if (!rawSpool_ || !writeExact(rawSpool_,header) ||
                    !writeExact(rawSpool_,frame.y) || !writeExact(rawSpool_,frame.u) ||
                    !writeExact(rawSpool_,frame.v) ||
                    !writeExact(rawSpool_,frame.canonicalMetadata))
                    throw std::runtime_error("sequential raw Camera2 spool write failed");
                ++spooledFrames_;
                queue.releaseRead(frame.slot);
                progressed=true;
                if (frame.ordinal==0u || ((frame.ordinal+1u)%30u)==0u) {
                    KC_SEED_LOGI(
                        "exact raw spool committed ordinal=%llu bytes_per_frame=%u",
                        static_cast<unsigned long long>(frame.ordinal),
                        binding_.width*binding_.height*3u/2u+
                            static_cast<std::uint32_t>(ChronoCameraMetadataBytes));
                }
            }
            if (writerStopRequested_.load(std::memory_order_acquire) && !progressed) break;
            if (!progressed) queue.waitForCaptured(std::chrono::milliseconds(20));
        }
    } catch (const std::exception& error) {
        writerFailed_.store(true,std::memory_order_release);
        camera_.frames().fail(ChronoCaptureError::WriterFailure,error.what());
        KC_SEED_LOGE("exact raw Camera2 spool failed: %s",error.what());
    }
}

void ChronoSeedCaptureSession::joinWriter() {
    if (writerThread_.joinable()) writerThread_.join();
}

bool ChronoSeedCaptureSession::transcodeAndReplay() {
    std::FILE* spool=nullptr;
    try {
        spool=std::fopen(rawSpoolPath_.c_str(),"rb");
        if (!spool) throw std::runtime_error("cannot reopen exact Camera2 raw spool");
        const auto closeSpool=[&spool] { if (spool) { std::fclose(spool); spool=nullptr; } };
        std::array<std::uint8_t,RawSpoolHeaderBytes> spoolHeader{};
        if (!readExact(spool,spoolHeader) ||
            std::memcmp(spoolHeader.data(),"UGRAWS1\0",8u)!=0 ||
            getU32(spoolHeader,8u)!=0x01020304u || getU32(spoolHeader,12u)!=1u ||
            getU32(spoolHeader,16u)!=RawSpoolHeaderBytes ||
            getU32(spoolHeader,20u)!=binding_.width ||
            getU32(spoolHeader,24u)!=binding_.height ||
            getU32(spoolHeader,28u)!=ChronoCameraMetadataBytes ||
            getU64(spoolHeader,32u)!=binding_.rootSeed ||
            getU64(spoolHeader,40u)!=binding_.recipeSeed ||
            readDigest(spoolHeader,48u)!=binding_.uglut2Sha256 ||
            getU64(spoolHeader,80u)!=spooledFrames_ ||
            getU32(spoolHeader,88u)!=RawSpoolFrameHeaderBytes) {
            closeSpool();
            throw std::runtime_error("exact Camera2 raw spool header/profile mismatch");
        }
        ugts::chrono::YuvSeedCaptureProfile profile;
        profile.logicalProfile=ugts::chrono::FullSubstrateCameraProfile;
        profile.width=binding_.width;
        profile.height=binding_.height;
        profile.rootSeed=binding_.rootSeed;
        profile.traversalRecipeSeed=binding_.recipeSeed;
        profile.literalUglut2=literalUglut2_;
        profile.noveltyWorkerCount=std::clamp<std::uint32_t>(
            std::thread::hardware_concurrency()>2u?
                std::thread::hardware_concurrency()-2u:1u,1u,8u);
        profile.noveltyMaxInFlightBlocks=std::min<std::uint32_t>(
            16u,profile.noveltyWorkerCount*2u);
        writer_=ugts::chrono::YuvSeedCaptureWriter::createPartial(partialPath_,profile);
        ChronoVulkanResidual vulkanResidual;
        const auto vulkanActive=vulkanResidual.configure(
            binding_.width,binding_.height,binding_.rootSeed,binding_.recipeSeed,
            literalUglut2_,ugts::chrono::FullSubstrateCameraProfile,
            profile.noveltyBlockLumaAddresses);
        if (!vulkanActive) throw std::runtime_error(
            "dedicated POCO seed flavor requires Vulkan 1.2 8-bit residual compute");
        std::vector<std::uint8_t> preparedResidual;
        std::vector<std::uint8_t> y(
            static_cast<std::size_t>(binding_.width)*binding_.height);
        std::vector<std::uint8_t> u(y.size()/4u),v(y.size()/4u);
        std::vector<std::uint8_t> metadata(ChronoCameraMetadataBytes);
        for (std::uint64_t ordinal=0;ordinal<spooledFrames_;++ordinal) {
            if (ordinal>std::numeric_limits<std::uint32_t>::max())
                throw std::runtime_error("profile-2 frame ordinal exceeds uint32 ABI");
            std::array<std::uint8_t,RawSpoolFrameHeaderBytes> header{};
            if (!readExact(spool,header) || std::memcmp(header.data(),"UGRFRM1\0",8u)!=0 ||
                getU64(header,8u)!=ordinal || getU32(header,192u)!=metadata.size() ||
                getU32(header,196u)!=y.size() || getU32(header,200u)!=u.size() ||
                getU32(header,204u)!=v.size() || !readExact(spool,y) ||
                !readExact(spool,u) || !readExact(spool,v) || !readExact(spool,metadata)) {
                closeSpool();
                throw std::runtime_error("exact Camera2 raw spool frame is truncated/invalid");
            }
            const auto pts=getI64(header,16u);
            if (chronoCaptureSha256(metadata)!=readDigest(header,160u)) {
                closeSpool();
                throw std::runtime_error("exact Camera2 raw spool metadata SHA mismatch");
            }
            std::array<std::uint8_t,16> prefix{};
            putI64(prefix,0u,pts);
            putU32(prefix,8u,binding_.width);
            putU32(prefix,12u,binding_.height);
            ChronoSha256 preHasher;
            preHasher.update(prefix); preHasher.update(y); preHasher.update(u); preHasher.update(v);
            const auto expectedPre=preHasher.finish();
            const ugts::chrono::Yuv420p8FrameView source{
                pts,getI64(header,24u),
                {y.data(),y.size(),binding_.width,1u},
                {u.data(),u.size(),binding_.width/2u,1u},
                {v.data(),v.size(),binding_.width/2u,1u},
                {metadata.data(),metadata.size()},
            };
            ChronoVulkanResidualReceipt gpuReceipt;
            ugts::chrono::YuvSeedCaptureAppendStats append;
            if (!vulkanResidual.compute(
                    y,u,v,(ordinal%profile.checkpointInterval)==0u,
                    static_cast<std::uint32_t>(ordinal),
                    preparedResidual,gpuReceipt))
                throw std::runtime_error(
                    "mandatory POCO Vulkan residual dispatch/parity failed");
            append=writer_->appendPreparedFullSubstrateResidual(
                source,{preparedResidual.data(),preparedResidual.size()});
            if (append.ordinal!=ordinal || append.preSubstrateSha256!=expectedPre ||
                append.operatorStateSha256!=gpuReceipt.operatorStateSha256 ||
                gpuReceipt.logicalProfile!=ugts::chrono::FullSubstrateCameraProfile ||
                !gpuReceipt.fullOperatorStateParity) {
                closeSpool();
                throw std::runtime_error(
                    "profile-2 UGYUVS1 ingress disagrees with GPU/raw-spool receipt");
            }
            if (ordinal==0u || ((ordinal+1u)%30u)==0u)
                KC_SEED_LOGI(
                    "UGYUVS1 post-capture transcode ordinal=%llu novelty_bytes=%llu record_bytes=%llu",
                    static_cast<unsigned long long>(ordinal),
                    static_cast<unsigned long long>(append.noveltyPayloadBytes),
                    static_cast<unsigned long long>(append.frameRecordBytes));
        }
        if (std::fgetc(spool)!=EOF || std::ferror(spool)) {
            closeSpool();
            throw std::runtime_error("exact Camera2 raw spool has trailing/read-error bytes");
        }
        closeSpool();
        if (vulkanResidual.dispatchCount()!=spooledFrames_)
            throw std::runtime_error(
                "mandatory POCO Vulkan dispatch count does not equal captured frames");
        KC_SEED_LOGI(
            "UGYUVS1 residual authoring receipt vulkan_gpu=%s dispatches=%llu "
            "frames=%llu cpu_fallback=%s prepared_bytes_consumed=%s workers=%u inflight=%u",
            vulkanResidual.deviceName().empty()?"unavailable":vulkanResidual.deviceName().c_str(),
            static_cast<unsigned long long>(vulkanResidual.dispatchCount()),
            static_cast<unsigned long long>(spooledFrames_),
            "false",
            vulkanResidual.dispatchCount()>0u?"true":"false",
            profile.noveltyWorkerCount,profile.noveltyMaxInFlightBlocks);
        const auto expectedFrames=writer_->frameCount();
        writer_->finalize(finalPath_);
        writer_.reset();
        ugts::chrono::YuvSeedCaptureReader reader(finalPath_);
        std::uint64_t replayed=0;
        std::int64_t previousPts=-1;
        reader.replay([&replayed,&previousPts](const ugts::chrono::DenseYuv420p8Frame& frame){
            if (frame.canonicalMetadata.size()!=ChronoCameraMetadataBytes ||
                std::memcmp(frame.canonicalMetadata.data(),"UGCAMD1\0",8u)!=0)
                throw std::runtime_error("replayed Camera2 metadata record is not UGCAMD1");
            const auto readLe64=[](const std::uint8_t* bytes) {
                std::uint64_t value=0;
                for (std::size_t index=0;index<8u;++index)
                    value|=static_cast<std::uint64_t>(bytes[index])<<(index*8u);
                return value;
            };
            const auto metadataPts=static_cast<std::int64_t>(
                readLe64(frame.canonicalMetadata.data()+24u));
            const auto metadataOrdinal=readLe64(frame.canonicalMetadata.data()+40u);
            if (frame.sensorTimestampNs<=previousPts ||
                metadataPts!=frame.sensorTimestampNs || metadataOrdinal!=replayed)
                throw std::runtime_error(
                    "replayed Camera2 PTS/ordinal disagrees with canonical metadata");
            previousPts=frame.sensorTimestampNs;
            ++replayed;
        });
        if (replayed!=expectedFrames || reader.inspection().committedFrames!=expectedFrames ||
            !reader.inspection().finalized)
            throw std::runtime_error("on-device UGYUVS1 replay count/final state mismatch");
        KC_SEED_LOGI(
            "UGYUVS1 native substrate replay PASS frames=%llu bytes=%llu path=%s "
            "planes_metadata_and_sensor_pts_verified=true",
            static_cast<unsigned long long>(replayed),
            static_cast<unsigned long long>(reader.inspection().committedBytes),
            finalPath_.c_str()
        );
        if (std::remove(rawSpoolPath_.c_str())==0)
            KC_SEED_LOGI("verified temporary raw spool removed");
        else KC_SEED_LOGE("verified raw spool could not be removed: %s",rawSpoolPath_.c_str());
        return true;
    } catch (const std::exception& error) {
        if (spool) std::fclose(spool);
        KC_SEED_LOGE("UGYUVS1 finalize/replay failed: %s",error.what());
        return false;
    }
}

void ChronoSeedCaptureSession::stopAndFinalize() {
    startRequested_.store(false,std::memory_order_release);
    const auto current=state();
    if (current==ChronoSeedCaptureState::Absent || current==ChronoSeedCaptureState::Configured ||
        current==ChronoSeedCaptureState::Finalizing ||
        current==ChronoSeedCaptureState::Complete) return;
    if (current==ChronoSeedCaptureState::AwaitingPermission) {
        camera_.stop();
        state_.store(ChronoSeedCaptureState::Configured,std::memory_order_release);
        return;
    }
    state_.store(ChronoSeedCaptureState::Finalizing,std::memory_order_release);
    camera_.stop();
    writerStopRequested_.store(true,std::memory_order_release);
    camera_.frames().wake();
    joinWriter();
    const auto spoolClosed=closeRawSpool();
    const auto queueStats=camera_.frames().stats();
    if (!spoolClosed || writerFailed_.load(std::memory_order_acquire) ||
        camera_.frames().failed() || queueStats.reservedFrames==0u ||
        queueStats.releasedFrames!=queueStats.reservedFrames ||
        spooledFrames_!=queueStats.reservedFrames) {
        writer_.reset();
        state_.store(ChronoSeedCaptureState::Failed,std::memory_order_release);
        KC_SEED_LOGE(
            "raw spool cannot transcode: closed=%s reserved=%llu released=%llu spooled=%llu error=%s",
            spoolClosed?"true":"false",
            static_cast<unsigned long long>(queueStats.reservedFrames),
            static_cast<unsigned long long>(queueStats.releasedFrames),
            static_cast<unsigned long long>(spooledFrames_),
            chronoCaptureErrorName(queueStats.error));
        return;
    }
    KC_SEED_LOGI(
        "raw spool finalized frames=%llu; asynchronous UGYUVS1 transcode starting",
        static_cast<unsigned long long>(spooledFrames_));
    writerThread_=std::thread([this] {
        const auto complete=transcodeAndReplay();
        if (!complete) writer_.reset(); // Preserve both partial evidence files.
        state_.store(complete?ChronoSeedCaptureState::Complete:ChronoSeedCaptureState::Failed,
            std::memory_order_release);
    });
}

void ChronoSeedCaptureSession::abort() {
    startRequested_.store(false,std::memory_order_release);
    camera_.stop();
    writerStopRequested_.store(true,std::memory_order_release);
    camera_.frames().wake();
    joinWriter();
    closeRawSpool();
    writer_.reset();
    if (state()!=ChronoSeedCaptureState::Absent)
        state_.store(ChronoSeedCaptureState::Configured,std::memory_order_release);
}

void ChronoSeedCaptureSession::pump() {
    camera_.pumpPermissionAndErrors();
    if (state()==ChronoSeedCaptureState::AwaitingPermission &&
        startRequested_.load(std::memory_order_acquire) && camera_.hasPermission()) {
        startAuthorized();
        return;
    }
    if (state()==ChronoSeedCaptureState::Capturing &&
        (camera_.state()==ChronoCameraState::Failed || camera_.frames().failed())) {
        stopAndFinalize();
    }
}

void ChronoSeedCaptureSession::fail(const char* detail) {
    state_.store(ChronoSeedCaptureState::Failed,std::memory_order_release);
    KC_SEED_LOGE("scene-owned capture failed: %s",detail?detail:"");
}

} // namespace kc
