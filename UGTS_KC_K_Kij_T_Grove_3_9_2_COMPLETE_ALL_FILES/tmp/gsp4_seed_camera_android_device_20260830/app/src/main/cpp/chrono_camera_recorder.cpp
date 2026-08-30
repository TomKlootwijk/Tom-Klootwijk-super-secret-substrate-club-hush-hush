#include "chrono_camera_recorder.hpp"

#include <android/api-level.h>
#include <android/log.h>
#include <camera/NdkCameraMetadata.h>
#include <camera/NdkCameraMetadataTags.h>
#include <camera/NdkCaptureRequest.h>
#include <dlfcn.h>
#include <media/NdkImage.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cstring>
#include <limits>
#include <span>
#include <type_traits>
#include <utility>
#include <vector>

#if defined(__aarch64__)
#include <arm_neon.h>
#endif

#define KC_CAMERA_LOGI(...) __android_log_print(ANDROID_LOG_INFO,"UGTS-KC392-CAMERA",__VA_ARGS__)
#define KC_CAMERA_LOGE(...) __android_log_print(ANDROID_LOG_ERROR,"UGTS-KC392-CAMERA",__VA_ARGS__)

namespace kc {
namespace {

constexpr std::uint32_t ProfileActiveArray=1u<<0u;
constexpr std::uint32_t ProfilePhysicalSize=1u<<1u;
constexpr std::uint32_t ProfileIntrinsics=1u<<2u;
constexpr std::uint32_t ProfileDistortion=1u<<3u;

struct ScopedMetadata {
    ACameraMetadata* value=nullptr;
    ~ScopedMetadata() { if (value) ACameraMetadata_free(value); }
};
struct ScopedIdList {
    ACameraManager* manager=nullptr;
    ACameraIdList* value=nullptr;
    ~ScopedIdList() { if (manager && value) ACameraManager_deleteCameraIdList(value); }
};
struct ScopedImage {
    AImage* value=nullptr;
    ~ScopedImage() { if (value) AImage_delete(value); }
};

class ScopedJni final {
public:
    explicit ScopedJni(ANativeActivity* activity):activity_(activity) {
        if (!activity_ || !activity_->vm) return;
        if (activity_->vm->GetEnv(reinterpret_cast<void**>(&env_),JNI_VERSION_1_6)==JNI_OK) return;
        if (activity_->vm->AttachCurrentThread(&env_,nullptr)==JNI_OK) detach_=true;
        else env_=nullptr;
    }
    ~ScopedJni() {
        if (detach_ && activity_ && activity_->vm) activity_->vm->DetachCurrentThread();
    }
    JNIEnv* env() const { return env_; }
private:
    ANativeActivity* activity_=nullptr;
    JNIEnv* env_=nullptr;
    bool detach_=false;
};

bool callActivityBoolean(ANativeActivity* activity,const char* name) {
    ScopedJni scope(activity);
    auto* env=scope.env();
    if (!env || !activity || !activity->clazz) return false;
    const auto activityClass=env->GetObjectClass(activity->clazz);
    if (!activityClass) return false;
    const auto method=env->GetMethodID(activityClass,name,"()Z");
    bool result=false;
    if (method) result=env->CallBooleanMethod(activity->clazz,method)==JNI_TRUE;
    env->DeleteLocalRef(activityClass);
    if (env->ExceptionCheck()) {
        env->ExceptionClear();
        return false;
    }
    return result;
}

void callActivityVoid(ANativeActivity* activity,const char* name) {
    ScopedJni scope(activity);
    auto* env=scope.env();
    if (!env || !activity || !activity->clazz) return;
    const auto activityClass=env->GetObjectClass(activity->clazz);
    if (!activityClass) return;
    const auto method=env->GetMethodID(activityClass,name,"()V");
    if (method) env->CallVoidMethod(activity->clazz,method);
    env->DeleteLocalRef(activityClass);
    if (env->ExceptionCheck()) env->ExceptionClear();
}

bool metadataEntry(const ACameraMetadata* metadata,std::uint32_t tag,ACameraMetadata_const_entry& entry) {
    return metadata && ACameraMetadata_getConstEntry(metadata,tag,&entry)==ACAMERA_OK && entry.count>0u;
}

bool supportsStream(
    const ACameraMetadata* metadata,std::uint32_t width,std::uint32_t height
) {
    ACameraMetadata_const_entry entry{};
    if (!metadataEntry(metadata,ACAMERA_SCALER_AVAILABLE_STREAM_CONFIGURATIONS,entry) ||
        (entry.count%4u)!=0u) return false;
    for (std::uint32_t index=0;index<entry.count;index+=4u) {
        if (entry.data.i32[index]==AIMAGE_FORMAT_YUV_420_888 &&
            entry.data.i32[index+1u]==static_cast<std::int32_t>(width) &&
            entry.data.i32[index+2u]==static_cast<std::int32_t>(height) &&
            entry.data.i32[index+3u]==ACAMERA_SCALER_AVAILABLE_STREAM_CONFIGURATIONS_OUTPUT)
            return true;
    }
    return false;
}

bool supportsFixedFps(const ACameraMetadata* metadata,std::uint16_t fps) {
    ACameraMetadata_const_entry entry{};
    if (!metadataEntry(metadata,ACAMERA_CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES,entry) ||
        (entry.count%2u)!=0u) return false;
    for (std::uint32_t index=0;index<entry.count;index+=2u)
        if (entry.data.i32[index]==fps && entry.data.i32[index+1u]==fps) return true;
    return false;
}

std::int64_t minimumFrameDuration(
    const ACameraMetadata* metadata,std::uint32_t width,std::uint32_t height
) {
    ACameraMetadata_const_entry entry{};
    if (!metadataEntry(metadata,ACAMERA_SCALER_AVAILABLE_MIN_FRAME_DURATIONS,entry) ||
        (entry.count%4u)!=0u) return 0;
    for (std::uint32_t index=0;index<entry.count;index+=4u) {
        if (entry.data.i64[index]==AIMAGE_FORMAT_YUV_420_888 &&
            entry.data.i64[index+1u]==width && entry.data.i64[index+2u]==height)
            return entry.data.i64[index+3u];
    }
    return 0;
}

template<std::size_t Size>
bool copyI32Entry(const ACameraMetadata* metadata,std::uint32_t tag,std::array<std::int32_t,Size>& output) {
    ACameraMetadata_const_entry entry{};
    if (!metadataEntry(metadata,tag,entry) || entry.count<Size) return false;
    std::copy_n(entry.data.i32,Size,output.begin());
    return true;
}

template<std::size_t Size>
bool copyFloatEntry(const ACameraMetadata* metadata,std::uint32_t tag,std::array<float,Size>& output) {
    ACameraMetadata_const_entry entry{};
    if (!metadataEntry(metadata,tag,entry) || entry.count<Size) return false;
    std::copy_n(entry.data.f,Size,output.begin());
    return true;
}

template<typename Value>
void updateInteger(ChronoSha256& hasher,Value value) {
    std::array<std::uint8_t,sizeof(Value)> bytes{};
    using Unsigned=std::make_unsigned_t<Value>;
    const auto bits=static_cast<Unsigned>(value);
    for (std::size_t index=0;index<bytes.size();++index)
        bytes[index]=static_cast<std::uint8_t>(bits>>(index*8u));
    hasher.update(bytes);
}

void updateFloat(ChronoSha256& hasher,float value) {
    std::uint32_t bits=0;
    std::memcpy(&bits,&value,sizeof(bits));
    updateInteger(hasher,bits);
}

ChronoSha256Digest profileDigest(const ChronoCameraProfile& profile) {
    ChronoSha256 hasher;
    hasher.update(std::span<const std::uint8_t>(
        reinterpret_cast<const std::uint8_t*>(profile.cameraId.data()),profile.cameraId.size()
    ));
    updateInteger(hasher,profile.width); updateInteger(hasher,profile.height);
    updateInteger(hasher,profile.fpsMin); updateInteger(hasher,profile.fpsMax);
    updateInteger(hasher,profile.minimumFrameDurationNs);
    updateInteger(hasher,profile.lensFacing); updateInteger(hasher,profile.hardwareLevel);
    updateInteger(hasher,profile.timestampSource); updateInteger(hasher,profile.sensorOrientation);
    updateInteger(hasher,profile.presence);
    for (const auto value:profile.activeArray) updateInteger(hasher,value);
    for (const auto value:profile.physicalSizeMm) updateFloat(hasher,value);
    for (const auto value:profile.intrinsicCalibration) updateFloat(hasher,value);
    for (const auto value:profile.distortion) updateFloat(hasher,value);
    return hasher.finish();
}

bool copyStridedPlane(
    const std::uint8_t* source,std::size_t sourceBytes,
    std::int32_t rowStride,std::int32_t pixelStride,
    std::uint32_t originX,std::uint32_t originY,
    std::uint32_t width,std::uint32_t height,
    std::span<std::uint8_t> target
) {
    if (!source || rowStride<=0 || pixelStride<=0 ||
        target.size()!=static_cast<std::size_t>(width)*height ||
        width==0u || height==0u) return false;
    const auto last=
        (static_cast<std::uint64_t>(originY)+height-1u)*static_cast<std::uint32_t>(rowStride)+
        (static_cast<std::uint64_t>(originX)+width-1u)*static_cast<std::uint32_t>(pixelStride);
    if (last>=sourceBytes) return false;
    for (std::uint32_t row=0;row<height;++row) {
        const auto sourceOffset=
            (static_cast<std::uint64_t>(originY)+row)*static_cast<std::uint32_t>(rowStride)+
            static_cast<std::uint64_t>(originX)*static_cast<std::uint32_t>(pixelStride);
        const auto* input=source+sourceOffset;
        auto* output=target.data()+static_cast<std::size_t>(row)*width;
        if (pixelStride==1) {
            std::memcpy(output,input,width);
            continue;
        }
        std::uint32_t column=0;
#if defined(__aarch64__)
        if (pixelStride==2) {
            for (;column+16u<=width;++column) {
                const auto vectorLast=sourceOffset+static_cast<std::uint64_t>(column)*2u+31u;
                if (vectorLast>=sourceBytes) break;
                const auto values=vld2q_u8(input+static_cast<std::size_t>(column)*2u);
                vst1q_u8(output+column,values.val[0]);
                column+=15u;
            }
        }
#endif
        for (;column<width;++column)
            output[column]=input[static_cast<std::size_t>(column)*pixelStride];
    }
    return true;
}

bool getI64(const ACameraMetadata* metadata,std::uint32_t tag,std::int64_t& value) {
    ACameraMetadata_const_entry entry{};
    if (!metadataEntry(metadata,tag,entry)) return false;
    value=entry.data.i64[0];
    return true;
}
bool getI32(const ACameraMetadata* metadata,std::uint32_t tag,std::int32_t& value) {
    ACameraMetadata_const_entry entry{};
    if (!metadataEntry(metadata,tag,entry)) return false;
    value=entry.data.i32[0];
    return true;
}
bool getFloat(const ACameraMetadata* metadata,std::uint32_t tag,float& value) {
    ACameraMetadata_const_entry entry{};
    if (!metadataEntry(metadata,tag,entry)) return false;
    value=entry.data.f[0];
    return true;
}
bool getByte(const ACameraMetadata* metadata,std::uint32_t tag,std::uint8_t& value) {
    ACameraMetadata_const_entry entry{};
    if (!metadataEntry(metadata,tag,entry)) return false;
    value=entry.data.u8[0];
    return true;
}

} // namespace

ChronoCameraRecorder::~ChronoCameraRecorder() { stop(); }

bool ChronoCameraRecorder::configure(
    ANativeActivity* activity,const ChronoSceneBinding& binding
) {
    stop();
    if (!activity || binding.mode!=ChronoSceneMode::Recorder ||
        !frames_.configure(binding.width,binding.height,binding.queueSlots)) return false;
    activity_=activity;
    config_=binding;
    selectedProfile_={};
    stopRequested_.store(false,std::memory_order_release);
    state_.store(ChronoCameraState::Stopped,std::memory_order_release);
    return true;
}

bool ChronoCameraRecorder::hasPermission() const {
    return callActivityBoolean(activity_,"hasCameraPermission");
}

void ChronoCameraRecorder::requestPermission() {
    if (!activity_) return;
    callActivityVoid(activity_,"requestCameraPermission");
    state_.store(ChronoCameraState::AwaitingPermission,std::memory_order_release);
}

void ChronoCameraRecorder::fail(ChronoCaptureError error,const char* detail) {
    frames_.fail(error,detail);
    stopRequested_.store(true,std::memory_order_release);
    state_.store(ChronoCameraState::Failed,std::memory_order_release);
    KC_CAMERA_LOGE("capture stopped: %s (%s)",chronoCaptureErrorName(error),detail?detail:"");
}

bool ChronoCameraRecorder::selectCameraProfile() {
    cameraManager_=ACameraManager_create();
    if (!cameraManager_) return false;
    ScopedIdList ids{cameraManager_,nullptr};
    if (ACameraManager_getCameraIdList(cameraManager_,&ids.value)!=ACAMERA_OK || !ids.value)
        return false;
    const bool automatic=config_.cameraId=="auto" || config_.cameraId=="back";
    int bestScore=std::numeric_limits<int>::min();
    for (int index=0;index<ids.value->numCameras;++index) {
        const char* id=ids.value->cameraIds[index];
        if (!id || (!automatic && config_.cameraId!=id)) continue;
        ScopedMetadata metadata;
        if (ACameraManager_getCameraCharacteristics(cameraManager_,id,&metadata.value)!=ACAMERA_OK ||
            !metadata.value || !supportsStream(metadata.value,config_.width,config_.height) ||
            !supportsFixedFps(metadata.value,config_.fps)) continue;
        const auto minimum=minimumFrameDuration(metadata.value,config_.width,config_.height);
        const auto requestedPeriod=1'000'000'000ll/static_cast<std::int64_t>(config_.fps);
        if (minimum<=0 || minimum>requestedPeriod) continue;
        ChronoCameraProfile candidate;
        candidate.cameraId=id;
        candidate.width=config_.width; candidate.height=config_.height;
        candidate.fpsMin=config_.fps; candidate.fpsMax=config_.fps;
        candidate.minimumFrameDurationNs=minimum;
        ACameraMetadata_const_entry entry{};
        if (metadataEntry(metadata.value,ACAMERA_LENS_FACING,entry)) candidate.lensFacing=entry.data.u8[0];
        if (metadataEntry(metadata.value,ACAMERA_INFO_SUPPORTED_HARDWARE_LEVEL,entry))
            candidate.hardwareLevel=entry.data.u8[0];
        if (metadataEntry(metadata.value,ACAMERA_SENSOR_INFO_TIMESTAMP_SOURCE,entry))
            candidate.timestampSource=entry.data.u8[0];
        if (metadataEntry(metadata.value,ACAMERA_SENSOR_ORIENTATION,entry))
            candidate.sensorOrientation=entry.data.i32[0];
        if (copyI32Entry(metadata.value,ACAMERA_SENSOR_INFO_ACTIVE_ARRAY_SIZE,candidate.activeArray))
            candidate.presence|=ProfileActiveArray;
        if (copyFloatEntry(metadata.value,ACAMERA_SENSOR_INFO_PHYSICAL_SIZE,candidate.physicalSizeMm))
            candidate.presence|=ProfilePhysicalSize;
        if (copyFloatEntry(metadata.value,ACAMERA_LENS_INTRINSIC_CALIBRATION,candidate.intrinsicCalibration))
            candidate.presence|=ProfileIntrinsics;
        if (copyFloatEntry(metadata.value,ACAMERA_LENS_DISTORTION,candidate.distortion))
            candidate.presence|=ProfileDistortion;
        candidate.characteristicsSha256=profileDigest(candidate);
        int score=0;
        if (candidate.lensFacing==ACAMERA_LENS_FACING_BACK) score+=100;
        if (candidate.hardwareLevel==ACAMERA_INFO_SUPPORTED_HARDWARE_LEVEL_3) score+=30;
        else if (candidate.hardwareLevel==ACAMERA_INFO_SUPPORTED_HARDWARE_LEVEL_FULL) score+=20;
        if (!automatic) score+=1000;
        if (score>bestScore) {
            bestScore=score;
            selectedProfile_=std::move(candidate);
        }
    }
    return bestScore!=std::numeric_limits<int>::min();
}

bool ChronoCameraRecorder::openSelectedCamera() {
    if (!cameraManager_ || selectedProfile_.cameraId.empty()) return false;
    if (AImageReader_new(
            static_cast<std::int32_t>(config_.width),static_cast<std::int32_t>(config_.height),
            AIMAGE_FORMAT_YUV_420_888,config_.queueSlots,&imageReader_)!=AMEDIA_OK || !imageReader_)
        return false;
    AImageReader_ImageListener imageListener{this,&ChronoCameraRecorder::onImageAvailable};
    if (AImageReader_setImageListener(imageReader_,&imageListener)!=AMEDIA_OK ||
        AImageReader_getWindow(imageReader_,&imageWindow_)!=AMEDIA_OK || !imageWindow_)
        return false;
    ACameraDevice_StateCallbacks deviceCallbacks{
        this,&ChronoCameraRecorder::onDeviceDisconnected,&ChronoCameraRecorder::onDeviceError
    };
    if (ACameraManager_openCamera(
            cameraManager_,selectedProfile_.cameraId.c_str(),&deviceCallbacks,&cameraDevice_
        )!=ACAMERA_OK || !cameraDevice_) return false;
    if (ACaptureSessionOutputContainer_create(&outputContainer_)!=ACAMERA_OK || !outputContainer_ ||
        ACaptureSessionOutput_create(imageWindow_,&sessionOutput_)!=ACAMERA_OK || !sessionOutput_ ||
        ACaptureSessionOutputContainer_add(outputContainer_,sessionOutput_)!=ACAMERA_OK ||
        ACameraOutputTarget_create(imageWindow_,&outputTarget_)!=ACAMERA_OK || !outputTarget_ ||
        ACameraDevice_createCaptureRequest(cameraDevice_,TEMPLATE_RECORD,&captureRequest_)!=ACAMERA_OK ||
        !captureRequest_ || ACaptureRequest_addTarget(captureRequest_,outputTarget_)!=ACAMERA_OK)
        return false;
    const std::array<std::int32_t,2> fps{{config_.fps,config_.fps}};
    if (ACaptureRequest_setEntry_i32(
            captureRequest_,ACAMERA_CONTROL_AE_TARGET_FPS_RANGE,fps.size(),fps.data()
        )!=ACAMERA_OK) return false;
    const std::uint8_t controlMode=ACAMERA_CONTROL_MODE_AUTO;
    const std::uint8_t aeMode=ACAMERA_CONTROL_AE_MODE_ON;
    const std::uint8_t awbMode=ACAMERA_CONTROL_AWB_MODE_AUTO;
    const std::uint8_t afMode=ACAMERA_CONTROL_AF_MODE_CONTINUOUS_VIDEO;
    const std::uint8_t stabilization=ACAMERA_CONTROL_VIDEO_STABILIZATION_MODE_OFF;
    if (ACaptureRequest_setEntry_u8(captureRequest_,ACAMERA_CONTROL_MODE,1u,&controlMode)!=ACAMERA_OK ||
        ACaptureRequest_setEntry_u8(captureRequest_,ACAMERA_CONTROL_AE_MODE,1u,&aeMode)!=ACAMERA_OK ||
        ACaptureRequest_setEntry_u8(captureRequest_,ACAMERA_CONTROL_AWB_MODE,1u,&awbMode)!=ACAMERA_OK ||
        ACaptureRequest_setEntry_u8(captureRequest_,ACAMERA_CONTROL_AF_MODE,1u,&afMode)!=ACAMERA_OK ||
        ACaptureRequest_setEntry_u8(
            captureRequest_,ACAMERA_CONTROL_VIDEO_STABILIZATION_MODE,1u,&stabilization
        )!=ACAMERA_OK) return false;
    ACameraCaptureSession_stateCallbacks sessionCallbacks{
        this,&ChronoCameraRecorder::onSessionClosed,
        &ChronoCameraRecorder::onSessionReady,&ChronoCameraRecorder::onSessionActive
    };
    if (ACameraDevice_createCaptureSession(
            cameraDevice_,outputContainer_,&sessionCallbacks,&captureSession_
        )!=ACAMERA_OK || !captureSession_) return false;

    acceptingImages_.store(true,std::memory_order_release);
    intentionalStop_.store(false,std::memory_order_release);
    {
        std::scoped_lock drainLock(drainMutex_);
        sequenceFinished_=false;
        repeatingSequenceId_=-1;
    }
    ACaptureRequest* requests[]{captureRequest_};
    camera_status_t status=ACAMERA_ERROR_UNKNOWN;
    int sequenceId=-1;
    if (android_get_device_api_level()>=33) {
        void* library=dlopen("libcamera2ndk.so",RTLD_NOW|RTLD_LOCAL);
        using RepeatingV2=camera_status_t(*)(
            ACameraCaptureSession*,ACameraCaptureSession_captureCallbacksV2*,
            int,ACaptureRequest**,int*
        );
        const auto function=library?reinterpret_cast<RepeatingV2>(
            dlsym(library,"ACameraCaptureSession_setRepeatingRequestV2")):nullptr;
        if (function) {
            ACameraCaptureSession_captureCallbacksV2 callbacks{};
            callbacks.context=this;
            callbacks.onCaptureStarted=&ChronoCameraRecorder::onCaptureStartedV2;
            callbacks.onCaptureCompleted=&ChronoCameraRecorder::onCaptureCompleted;
            callbacks.onCaptureFailed=&ChronoCameraRecorder::onCaptureFailed;
            callbacks.onCaptureSequenceCompleted=&ChronoCameraRecorder::onSequenceCompleted;
            callbacks.onCaptureSequenceAborted=&ChronoCameraRecorder::onSequenceAborted;
            callbacks.onCaptureBufferLost=&ChronoCameraRecorder::onBufferLost;
            status=function(captureSession_,&callbacks,1,requests,&sequenceId);
        }
        if (library) dlclose(library);
    }
    if (status!=ACAMERA_OK) {
        ACameraCaptureSession_captureCallbacks callbacks{};
        callbacks.context=this;
        callbacks.onCaptureStarted=&ChronoCameraRecorder::onCaptureStarted;
        callbacks.onCaptureCompleted=&ChronoCameraRecorder::onCaptureCompleted;
        callbacks.onCaptureFailed=&ChronoCameraRecorder::onCaptureFailed;
        callbacks.onCaptureSequenceCompleted=&ChronoCameraRecorder::onSequenceCompleted;
        callbacks.onCaptureSequenceAborted=&ChronoCameraRecorder::onSequenceAborted;
        callbacks.onCaptureBufferLost=&ChronoCameraRecorder::onBufferLost;
        sequenceId=-1;
        status=ACameraCaptureSession_setRepeatingRequest(
            captureSession_,&callbacks,1,requests,&sequenceId);
    }
    if (status!=ACAMERA_OK) {
        acceptingImages_.store(false,std::memory_order_release);
        return false;
    }
    {
        std::scoped_lock drainLock(drainMutex_);
        repeatingSequenceId_=sequenceId;
    }
    return true;
}

bool ChronoCameraRecorder::start() {
    const auto current=state();
    if (current==ChronoCameraState::Capturing) return true;
    if (current==ChronoCameraState::Unconfigured || current==ChronoCameraState::Failed) return false;
    if (!hasPermission()) {
        requestPermission();
        return false;
    }
    state_.store(ChronoCameraState::Starting,std::memory_order_release);
    stopRequested_.store(false,std::memory_order_release);
    if (!selectCameraProfile() || !openSelectedCamera()) {
        releaseCameraResources();
        fail(ChronoCaptureError::CameraDevice,
            "requested Camera2 YUV420 size/fixed-FPS profile could not be opened");
        return false;
    }
    state_.store(ChronoCameraState::Capturing,std::memory_order_release);
    KC_CAMERA_LOGI(
        "Camera2 authority node=%u id=%s size=%ux%u fps=%u/%u min_frame_ns=%lld "
        "lens=%u hardware=%u timestamp_source=%u queue=%u pixel=UGCODE24_420_CAMERA_EXACT",
        config_.nodeIndex,selectedProfile_.cameraId.c_str(),selectedProfile_.width,
        selectedProfile_.height,selectedProfile_.fpsMin,selectedProfile_.fpsMax,
        static_cast<long long>(selectedProfile_.minimumFrameDurationNs),
        selectedProfile_.lensFacing,selectedProfile_.hardwareLevel,selectedProfile_.timestampSource,
        config_.queueSlots
    );
    return true;
}

void ChronoCameraRecorder::releaseCameraResources() {
    acceptingImages_.store(false,std::memory_order_release);
    if (captureSession_) {
        ACameraCaptureSession_stopRepeating(captureSession_);
        ACameraCaptureSession_abortCaptures(captureSession_);
    }
    if (imageReader_) AImageReader_setImageListener(imageReader_,nullptr);
    {
        // Do not delete AImageReader while its dedicated callback is copying.
        std::scoped_lock callbackLock(callbackMutex_);
    }
    if (captureSession_) {
        ACameraCaptureSession_close(captureSession_);
        captureSession_=nullptr;
    }
    if (cameraDevice_) {
        ACameraDevice_close(cameraDevice_);
        cameraDevice_=nullptr;
    }
    if (captureRequest_) { ACaptureRequest_free(captureRequest_); captureRequest_=nullptr; }
    if (outputTarget_) { ACameraOutputTarget_free(outputTarget_); outputTarget_=nullptr; }
    if (sessionOutput_) { ACaptureSessionOutput_free(sessionOutput_); sessionOutput_=nullptr; }
    if (outputContainer_) {
        ACaptureSessionOutputContainer_free(outputContainer_);
        outputContainer_=nullptr;
    }
    if (imageReader_) { AImageReader_delete(imageReader_); imageReader_=nullptr; }
    imageWindow_=nullptr;
    if (cameraManager_) { ACameraManager_delete(cameraManager_); cameraManager_=nullptr; }
}

void ChronoCameraRecorder::stop() {
    const auto current=state();
    if (current==ChronoCameraState::Unconfigured) return;
    if (captureSession_ && current==ChronoCameraState::Capturing) {
        intentionalStop_.store(true,std::memory_order_release);
        const auto status=ACameraCaptureSession_stopRepeating(captureSession_);
        bool sequenceFinished=false;
        if (status==ACAMERA_OK) {
            std::unique_lock drainLock(drainMutex_);
            sequenceFinished=drainCondition_.wait_for(
                drainLock,std::chrono::milliseconds(1500),
                [this]{ return sequenceFinished_ || frames_.failed(); });
            if (sequenceFinished && !frames_.failed()) {
                static_cast<void>(drainCondition_.wait_for(
                    drainLock,std::chrono::milliseconds(500),[this] {
                        return acceptedImages_.load(std::memory_order_acquire)==
                            captureResults_.load(std::memory_order_acquire) || frames_.failed();
                    }));
            }
        }
        KC_CAMERA_LOGI(
            "Camera2 stop boundary sequence_finished=%s accepted=%llu results=%llu",
            sequenceFinished?"true":"false",
            static_cast<unsigned long long>(acceptedImages_.load(std::memory_order_relaxed)),
            static_cast<unsigned long long>(captureResults_.load(std::memory_order_relaxed)));
    }
    releaseCameraResources();
    intentionalStop_.store(false,std::memory_order_release);
    stopRequested_.store(false,std::memory_order_release);
    if (current!=ChronoCameraState::Failed)
        state_.store(ChronoCameraState::Stopped,std::memory_order_release);
}

void ChronoCameraRecorder::pumpPermissionAndErrors() {
    if (stopRequested_.exchange(false,std::memory_order_acq_rel)) {
        const auto failed=frames_.failed();
        releaseCameraResources();
        state_.store(failed?ChronoCameraState::Failed:ChronoCameraState::Stopped,
            std::memory_order_release);
    }
}

bool ChronoCameraRecorder::copyImage(AImage* image) {
    if (!image) return false;
    std::int32_t format=0,imageWidth=0,imageHeight=0,planeCount=0;
    std::int64_t timestamp=0;
    AImageCropRect crop{};
    if (AImage_getFormat(image,&format)!=AMEDIA_OK || format!=AIMAGE_FORMAT_YUV_420_888 ||
        AImage_getWidth(image,&imageWidth)!=AMEDIA_OK || AImage_getHeight(image,&imageHeight)!=AMEDIA_OK ||
        AImage_getNumberOfPlanes(image,&planeCount)!=AMEDIA_OK || planeCount!=3 ||
        AImage_getTimestamp(image,&timestamp)!=AMEDIA_OK ||
        AImage_getCropRect(image,&crop)!=AMEDIA_OK) return false;
    const auto cropWidth=crop.right-crop.left;
    const auto cropHeight=crop.bottom-crop.top;
    if (imageWidth<=0 || imageHeight<=0 || crop.left<0 || crop.top<0 ||
        (crop.left&1)!=0 || (crop.top&1)!=0 ||
        cropWidth!=static_cast<std::int32_t>(config_.width) ||
        cropHeight!=static_cast<std::int32_t>(config_.height)) return false;
    ChronoDenseYuvWriteView target;
    if (!frames_.beginWrite(timestamp,target)) return false;
    const std::array<std::uint32_t,3> originX{{
        static_cast<std::uint32_t>(crop.left),
        static_cast<std::uint32_t>(crop.left/2),
        static_cast<std::uint32_t>(crop.left/2),
    }};
    const std::array<std::uint32_t,3> originY{{
        static_cast<std::uint32_t>(crop.top),
        static_cast<std::uint32_t>(crop.top/2),
        static_cast<std::uint32_t>(crop.top/2),
    }};
    const std::array<std::uint32_t,3> widths{{config_.width,config_.width/2u,config_.width/2u}};
    const std::array<std::uint32_t,3> heights{{config_.height,config_.height/2u,config_.height/2u}};
    const std::array<std::span<std::uint8_t>,3> targets{{target.y,target.u,target.v}};
    for (std::int32_t planeIndex=0;planeIndex<3;++planeIndex) {
        std::uint8_t* source=nullptr;
        int sourceBytes=0,rowStride=0,pixelStride=0;
        if (AImage_getPlaneData(image,planeIndex,&source,&sourceBytes)!=AMEDIA_OK || sourceBytes<0 ||
            AImage_getPlaneRowStride(image,planeIndex,&rowStride)!=AMEDIA_OK ||
            AImage_getPlanePixelStride(image,planeIndex,&pixelStride)!=AMEDIA_OK ||
            !copyStridedPlane(
                source,static_cast<std::size_t>(sourceBytes),rowStride,pixelStride,
                originX[planeIndex],originY[planeIndex],widths[planeIndex],heights[planeIndex],
                targets[planeIndex]
            )) {
            frames_.abortWrite(target.slot,ChronoCaptureError::InvalidImage,
                "YUV_420_888 plane extent/stride is invalid");
            return false;
        }
    }
    return frames_.completeWrite(target.slot);
}

void ChronoCameraRecorder::onImageAvailable(void* context,AImageReader* reader) {
    auto* recorder=static_cast<ChronoCameraRecorder*>(context);
    if (!recorder || !reader) return;
    std::scoped_lock callbackLock(recorder->callbackMutex_);
    for (;;) {
        ScopedImage image;
        const auto status=AImageReader_acquireNextImage(reader,&image.value);
        if (status==AMEDIA_IMGREADER_NO_BUFFER_AVAILABLE) break;
        if (status!=AMEDIA_OK || !image.value) {
            recorder->fail(ChronoCaptureError::InvalidImage,"AImageReader acquireNextImage failed");
            break;
        }
        recorder->imageCallbacks_.fetch_add(1u,std::memory_order_relaxed);
        if (!recorder->acceptingImages_.load(std::memory_order_acquire)) continue;
        if (!recorder->copyImage(image.value)) {
            if (!recorder->frames_.failed())
                recorder->fail(ChronoCaptureError::InvalidImage,"Camera2 image normalization failed");
            else recorder->stopRequested_.store(true,std::memory_order_release);
            break;
        }
        recorder->acceptedImages_.fetch_add(1u,std::memory_order_relaxed);
        recorder->drainCondition_.notify_all();
    }
}

void ChronoCameraRecorder::rememberFrameNumber(
    std::int64_t timestampNs,std::int64_t frameNumber
) {
    std::scoped_lock lock(startedFramesMutex_);
    const auto item=std::find_if(startedFrames_.begin(),startedFrames_.end(),
        [](const StartedFrame& value){ return !value.used; });
    if (item==startedFrames_.end()) {
        fail(ChronoCaptureError::MetadataPressure,"Camera2 frame-number correlation table is full");
        return;
    }
    item->used=true;
    item->timestampNs=timestampNs;
    item->frameNumber=frameNumber;
}

std::int64_t ChronoCameraRecorder::takeFrameNumber(std::int64_t timestampNs) {
    std::scoped_lock lock(startedFramesMutex_);
    for (auto& item:startedFrames_) {
        if (!item.used || item.timestampNs!=timestampNs) continue;
        item.used=false;
        return item.frameNumber;
    }
    return -1;
}

bool ChronoCameraRecorder::extractMetadata(
    const ACameraMetadata* result,ChronoCameraMetadata& metadata
) {
    if (!getI64(result,ACAMERA_SENSOR_TIMESTAMP,metadata.sensorTimestampNs) ||
        metadata.sensorTimestampNs<=0) return false;
    metadata.frameNumber=takeFrameNumber(metadata.sensorTimestampNs);
    if (metadata.frameNumber>=0) metadata.presence|=ChronoMetadataFrameNumber;
    if (getI64(result,ACAMERA_SENSOR_EXPOSURE_TIME,metadata.exposureTimeNs))
        metadata.presence|=ChronoMetadataExposureTime;
    if (getI64(result,ACAMERA_SENSOR_FRAME_DURATION,metadata.frameDurationNs))
        metadata.presence|=ChronoMetadataFrameDuration;
    if (getI64(result,ACAMERA_SENSOR_ROLLING_SHUTTER_SKEW,metadata.rollingShutterSkewNs))
        metadata.presence|=ChronoMetadataRollingShutterSkew;
    if (getI32(result,ACAMERA_SENSOR_SENSITIVITY,metadata.sensitivityIso))
        metadata.presence|=ChronoMetadataSensitivity;
    if (getFloat(result,ACAMERA_LENS_FOCAL_LENGTH,metadata.focalLengthMm))
        metadata.presence|=ChronoMetadataFocalLength;
    if (getFloat(result,ACAMERA_LENS_FOCUS_DISTANCE,metadata.focusDistanceDiopters))
        metadata.presence|=ChronoMetadataFocusDistance;
    if (getFloat(result,ACAMERA_LENS_APERTURE,metadata.aperture))
        metadata.presence|=ChronoMetadataAperture;
    if (copyI32Entry(result,ACAMERA_SCALER_CROP_REGION,metadata.cropRegion))
        metadata.presence|=ChronoMetadataCropRegion;
    if (getByte(result,ACAMERA_CONTROL_AE_STATE,metadata.aeState))
        metadata.presence|=ChronoMetadataAeState;
    if (getByte(result,ACAMERA_CONTROL_AF_STATE,metadata.afState))
        metadata.presence|=ChronoMetadataAfState;
    if (getByte(result,ACAMERA_CONTROL_AWB_STATE,metadata.awbState))
        metadata.presence|=ChronoMetadataAwbState;
    if (getByte(result,ACAMERA_LENS_STATE,metadata.lensState))
        metadata.presence|=ChronoMetadataLensState;
    if (getI32(result,ACAMERA_CONTROL_AE_EXPOSURE_COMPENSATION,metadata.aeCompensation))
        metadata.presence|=ChronoMetadataAeCompensation;
    if (getI32(result,ACAMERA_CONTROL_POST_RAW_SENSITIVITY_BOOST,metadata.postRawSensitivityBoost))
        metadata.presence|=ChronoMetadataPostRawSensitivityBoost;
    return true;
}

void ChronoCameraRecorder::onCaptureStarted(
    void*,ACameraCaptureSession*,const ACaptureRequest*,std::int64_t
) {}

void ChronoCameraRecorder::onCaptureStartedV2(
    void* context,ACameraCaptureSession*,const ACaptureRequest*,
    std::int64_t timestamp,std::int64_t frameNumber
) {
    auto* recorder=static_cast<ChronoCameraRecorder*>(context);
    if (recorder) recorder->rememberFrameNumber(timestamp,frameNumber);
}

void ChronoCameraRecorder::onCaptureCompleted(
    void* context,ACameraCaptureSession*,ACaptureRequest*,const ACameraMetadata* result
) {
    auto* recorder=static_cast<ChronoCameraRecorder*>(context);
    if (!recorder || !recorder->acceptingImages_.load(std::memory_order_acquire)) return;
    ChronoCameraMetadata metadata;
    if (!recorder->extractMetadata(result,metadata) || !recorder->frames_.attachMetadata(metadata)) {
        if (!recorder->frames_.failed())
            recorder->fail(ChronoCaptureError::InvalidImage,"Camera2 capture metadata is invalid");
        else recorder->stopRequested_.store(true,std::memory_order_release);
        return;
    }
    recorder->captureResults_.fetch_add(1u,std::memory_order_relaxed);
    recorder->drainCondition_.notify_all();
}

void ChronoCameraRecorder::onCaptureFailed(
    void* context,ACameraCaptureSession*,ACaptureRequest*,ACameraCaptureFailure*
) {
    auto* recorder=static_cast<ChronoCameraRecorder*>(context);
    if (!recorder) return;
    recorder->captureFailures_.fetch_add(1u,std::memory_order_relaxed);
    recorder->fail(ChronoCaptureError::CaptureFailure,"Camera2 reported a failed capture");
}

void ChronoCameraRecorder::onBufferLost(
    void* context,ACameraCaptureSession*,ACaptureRequest*,ANativeWindow*,std::int64_t
) {
    auto* recorder=static_cast<ChronoCameraRecorder*>(context);
    if (!recorder) return;
    recorder->lostBuffers_.fetch_add(1u,std::memory_order_relaxed);
    recorder->fail(ChronoCaptureError::BufferLost,"Camera2 reported a lost authoritative buffer");
}

void ChronoCameraRecorder::onDeviceDisconnected(void* context,ACameraDevice*) {
    auto* recorder=static_cast<ChronoCameraRecorder*>(context);
    if (recorder) recorder->fail(ChronoCaptureError::CameraDisconnected,"Camera2 device disconnected");
}
void ChronoCameraRecorder::onDeviceError(void* context,ACameraDevice*,int) {
    auto* recorder=static_cast<ChronoCameraRecorder*>(context);
    if (recorder) recorder->fail(ChronoCaptureError::CameraDevice,"Camera2 device error");
}
void ChronoCameraRecorder::onSessionClosed(void*,ACameraCaptureSession*) {}
void ChronoCameraRecorder::onSessionReady(void*,ACameraCaptureSession*) {}
void ChronoCameraRecorder::onSessionActive(void*,ACameraCaptureSession*) {}
void ChronoCameraRecorder::onSequenceCompleted(
    void* context,ACameraCaptureSession*,int sequenceId,std::int64_t
) {
    auto* recorder=static_cast<ChronoCameraRecorder*>(context);
    if (!recorder) return;
    {
        std::scoped_lock drainLock(recorder->drainMutex_);
        if (recorder->repeatingSequenceId_<0 ||
            recorder->repeatingSequenceId_==sequenceId)
            recorder->sequenceFinished_=true;
    }
    recorder->drainCondition_.notify_all();
}
void ChronoCameraRecorder::onSequenceAborted(void* context,ACameraCaptureSession*,int) {
    auto* recorder=static_cast<ChronoCameraRecorder*>(context);
    if (!recorder) return;
    {
        std::scoped_lock drainLock(recorder->drainMutex_);
        recorder->sequenceFinished_=true;
    }
    recorder->drainCondition_.notify_all();
    if (recorder->acceptingImages_.load(std::memory_order_acquire) &&
        !recorder->intentionalStop_.load(std::memory_order_acquire))
        recorder->fail(ChronoCaptureError::CaptureFailure,"Camera2 repeating sequence aborted");
}

ChronoCameraStats ChronoCameraRecorder::stats() const {
    return {
        imageCallbacks_.load(std::memory_order_relaxed),
        acceptedImages_.load(std::memory_order_relaxed),
        captureResults_.load(std::memory_order_relaxed),
        captureFailures_.load(std::memory_order_relaxed),
        lostBuffers_.load(std::memory_order_relaxed),
    };
}

} // namespace kc
