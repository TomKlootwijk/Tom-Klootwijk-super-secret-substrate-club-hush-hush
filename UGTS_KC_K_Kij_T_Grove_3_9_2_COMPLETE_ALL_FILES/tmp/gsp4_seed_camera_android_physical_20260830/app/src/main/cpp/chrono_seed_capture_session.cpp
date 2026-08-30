#include "chrono_seed_capture_session.hpp"

#include <android/log.h>

#include <chrono>
#include <cstring>
#include <exception>
#include <stdexcept>

#define KC_SEED_LOGI(...) __android_log_print(ANDROID_LOG_INFO,"UGTS-KC392-SEED",__VA_ARGS__)
#define KC_SEED_LOGE(...) __android_log_print(ANDROID_LOG_ERROR,"UGTS-KC392-SEED",__VA_ARGS__)

namespace kc {

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
    startRequested_.store(false,std::memory_order_release);
    writerStopRequested_.store(false,std::memory_order_release);
    writerFailed_.store(false,std::memory_order_release);
    state_.store(ChronoSeedCaptureState::Configured,std::memory_order_release);
    KC_SEED_LOGI(
        "scene-owned seed capture configured node=%u final=%s autostart=%s "
        "profile=UGCODE24_420_CAMERA_EXACT authority=CAMERA2_DENSE_YUV420",
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
        ugts::chrono::YuvSeedCaptureProfile profile;
        profile.width=binding_.width;
        profile.height=binding_.height;
        profile.rootSeed=binding_.rootSeed;
        profile.traversalRecipeSeed=binding_.recipeSeed;
        profile.literalUglut2=literalUglut2_;
        writer_=ugts::chrono::YuvSeedCaptureWriter::createPartial(partialPath_,profile);
        writerStopRequested_.store(false,std::memory_order_release);
        writerFailed_.store(false,std::memory_order_release);
        writerThread_=std::thread(&ChronoSeedCaptureSession::runWriter,this);
        if (!camera_.start()) {
            writerStopRequested_.store(true,std::memory_order_release);
            camera_.frames().wake();
            joinWriter();
            writer_.reset();
            fail("Camera2 failed after the seed writer was prepared");
            return false;
        }
        state_.store(ChronoSeedCaptureState::Capturing,std::memory_order_release);
        KC_SEED_LOGI("UGYUVS1 append-only capture started partial=%s",partialPath_.c_str());
        return true;
    } catch (const std::exception& error) {
        writer_.reset();
        fail(error.what());
        return false;
    }
}

void ChronoSeedCaptureSession::runWriter() {
    try {
        auto& queue=camera_.frames();
        for (;;) {
            bool progressed=false;
            while (queue.prepareNextCaptured()) progressed=true;
            ChronoDenseYuvReadView frame;
            while (queue.acquireReady(frame)) {
                const ugts::chrono::Yuv420p8FrameView source{
                    frame.sensorTimestampNs,
                    frame.frameNumber,
                    {frame.y.data(),frame.y.size(),binding_.width,1u},
                    {frame.u.data(),frame.u.size(),binding_.width/2u,1u},
                    {frame.v.data(),frame.v.size(),binding_.width/2u,1u},
                    {frame.canonicalMetadata.data(),frame.canonicalMetadata.size()},
                };
                const auto append=writer_->append(source);
                if (append.ordinal!=frame.ordinal ||
                    append.preSubstrateSha256!=frame.preSubstrateSha256)
                    throw std::runtime_error(
                        "portable UGYUVS1 writer disagrees with Camera2 pre-substrate digest"
                    );
                queue.releaseRead(frame.slot);
                progressed=true;
                if (append.ordinal==0u || ((append.ordinal+1u)%30u)==0u) {
                    KC_SEED_LOGI(
                        "UGYUVS1 committed ordinal=%llu novelty_events=%llu "
                        "novelty_bytes=%llu record_bytes=%llu",
                        static_cast<unsigned long long>(append.ordinal),
                        static_cast<unsigned long long>(append.noveltyEventCount),
                        static_cast<unsigned long long>(append.noveltyPayloadBytes),
                        static_cast<unsigned long long>(append.frameRecordBytes)
                    );
                }
            }
            if (writerStopRequested_.load(std::memory_order_acquire) && !progressed) break;
            if (!progressed) queue.waitForCaptured(std::chrono::milliseconds(20));
        }
    } catch (const std::exception& error) {
        writerFailed_.store(true,std::memory_order_release);
        camera_.frames().fail(ChronoCaptureError::WriterFailure,error.what());
        KC_SEED_LOGE("UGYUVS1 writer failed: %s",error.what());
    }
}

void ChronoSeedCaptureSession::joinWriter() {
    if (writerThread_.joinable()) writerThread_.join();
}

bool ChronoSeedCaptureSession::finalizeAndReplay() {
    if (!writer_ || writerFailed_.load(std::memory_order_acquire) || camera_.frames().failed())
        return false;
    const auto queueStats=camera_.frames().stats();
    if (queueStats.reservedFrames==0u || queueStats.releasedFrames!=queueStats.reservedFrames) {
        camera_.frames().fail(ChronoCaptureError::WriterFailure,
            "not every accepted Camera2 frame reached the ordered writer");
        return false;
    }
    try {
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
            "UGYUVS1 native substrate replay PASS frames=%llu path=%s "
            "planes_and_sensor_pts_verified=true",
            static_cast<unsigned long long>(replayed),finalPath_.c_str()
        );
        return true;
    } catch (const std::exception& error) {
        KC_SEED_LOGE("UGYUVS1 finalize/replay failed: %s",error.what());
        return false;
    }
}

void ChronoSeedCaptureSession::stopAndFinalize() {
    startRequested_.store(false,std::memory_order_release);
    const auto current=state();
    if (current==ChronoSeedCaptureState::Absent || current==ChronoSeedCaptureState::Configured ||
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
    const auto complete=finalizeAndReplay();
    if (!complete) writer_.reset(); // Leave .ugsp4c.partial as explicit incomplete evidence.
    state_.store(complete?ChronoSeedCaptureState::Complete:ChronoSeedCaptureState::Failed,
        std::memory_order_release);
}

void ChronoSeedCaptureSession::abort() {
    startRequested_.store(false,std::memory_order_release);
    camera_.stop();
    writerStopRequested_.store(true,std::memory_order_release);
    camera_.frames().wake();
    joinWriter();
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
