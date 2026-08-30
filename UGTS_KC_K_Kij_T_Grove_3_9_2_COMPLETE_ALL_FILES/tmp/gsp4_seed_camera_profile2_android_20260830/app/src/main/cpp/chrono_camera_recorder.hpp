#pragma once

#include "chrono_capture_queue.hpp"
#include "chrono_scene_binding.hpp"

#include <android/native_activity.h>
#include <camera/NdkCameraCaptureSession.h>
#include <camera/NdkCameraDevice.h>
#include <camera/NdkCameraManager.h>
#include <media/NdkImageReader.h>

#include <array>
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <mutex>
#include <string>

namespace kc {

enum class ChronoCameraState : std::uint8_t {
    Unconfigured=0,
    Stopped,
    AwaitingPermission,
    Starting,
    Capturing,
    Failed,
};

struct ChronoCameraProfile {
    std::string cameraId;
    std::uint32_t width=0,height=0;
    std::uint16_t fpsMin=0,fpsMax=0;
    std::int64_t minimumFrameDurationNs=0;
    std::uint8_t lensFacing=0;
    std::uint8_t hardwareLevel=0;
    std::uint8_t timestampSource=0;
    std::int32_t sensorOrientation=0;
    std::array<std::int32_t,4> activeArray{};
    std::array<float,2> physicalSizeMm{};
    std::array<float,5> intrinsicCalibration{};
    std::array<float,5> distortion{};
    std::uint32_t presence=0;
    ChronoSha256Digest characteristicsSha256{};
};

struct ChronoCameraStats {
    std::uint64_t imageCallbacks=0;
    std::uint64_t acceptedImages=0;
    std::uint64_t captureResults=0;
    std::uint64_t captureFailures=0;
    std::uint64_t lostBuffers=0;
};

class ChronoCameraRecorder final {
public:
    ChronoCameraRecorder()=default;
    ~ChronoCameraRecorder();
    ChronoCameraRecorder(const ChronoCameraRecorder&)=delete;
    ChronoCameraRecorder& operator=(const ChronoCameraRecorder&)=delete;

    bool configure(ANativeActivity* activity,const ChronoSceneBinding& binding);
    bool start();
    void stop();
    void pumpPermissionAndErrors();
    void requestPermission();
    bool hasPermission() const;

    ChronoCameraState state() const { return state_.load(std::memory_order_acquire); }
    std::uint32_t ownerNodeIndex() const { return config_.nodeIndex; }
    const ChronoCameraProfile& selectedProfile() const { return selectedProfile_; }
    ChronoCaptureFrameQueue& frames() { return frames_; }
    const ChronoCaptureFrameQueue& frames() const { return frames_; }
    ChronoCameraStats stats() const;
    const std::string& outputBasename() const { return config_.outputBasename; }

private:
    struct StartedFrame {
        bool used=false;
        std::int64_t timestampNs=0;
        std::int64_t frameNumber=-1;
    };

    bool selectCameraProfile();
    bool openSelectedCamera();
    void releaseCameraResources();
    bool copyImage(AImage* image);
    bool extractMetadata(const ACameraMetadata* result,ChronoCameraMetadata& metadata);
    void rememberFrameNumber(std::int64_t timestampNs,std::int64_t frameNumber);
    std::int64_t takeFrameNumber(std::int64_t timestampNs);
    void fail(ChronoCaptureError error,const char* detail);

    static void onImageAvailable(void* context,AImageReader* reader);
    static void onDeviceDisconnected(void* context,ACameraDevice* device);
    static void onDeviceError(void* context,ACameraDevice* device,int error);
    static void onSessionClosed(void* context,ACameraCaptureSession* session);
    static void onSessionReady(void* context,ACameraCaptureSession* session);
    static void onSessionActive(void* context,ACameraCaptureSession* session);
    static void onCaptureStarted(
        void* context,ACameraCaptureSession* session,
        const ACaptureRequest* request,std::int64_t timestamp
    );
    static void onCaptureStartedV2(
        void* context,ACameraCaptureSession* session,
        const ACaptureRequest* request,std::int64_t timestamp,std::int64_t frameNumber
    );
    static void onCaptureCompleted(
        void* context,ACameraCaptureSession* session,
        ACaptureRequest* request,const ACameraMetadata* result
    );
    static void onCaptureFailed(
        void* context,ACameraCaptureSession* session,
        ACaptureRequest* request,ACameraCaptureFailure* failure
    );
    static void onSequenceCompleted(
        void* context,ACameraCaptureSession* session,int sequenceId,std::int64_t frameNumber
    );
    static void onSequenceAborted(
        void* context,ACameraCaptureSession* session,int sequenceId
    );
    static void onBufferLost(
        void* context,ACameraCaptureSession* session,
        ACaptureRequest* request,ANativeWindow* window,std::int64_t frameNumber
    );

    ANativeActivity* activity_=nullptr;
    ChronoSceneBinding config_{};
    ChronoCameraProfile selectedProfile_{};
    ChronoCaptureFrameQueue frames_{};
    std::atomic<ChronoCameraState> state_{ChronoCameraState::Unconfigured};
    std::atomic<bool> acceptingImages_{false};
    std::atomic<bool> stopRequested_{false};
    mutable std::mutex callbackMutex_;
    mutable std::mutex startedFramesMutex_;
    mutable std::mutex drainMutex_;
    std::condition_variable drainCondition_;
    bool sequenceFinished_=false;
    int repeatingSequenceId_=-1;
    std::atomic<bool> intentionalStop_{false};
    std::array<StartedFrame,64> startedFrames_{};
    std::atomic<std::uint64_t> imageCallbacks_{0};
    std::atomic<std::uint64_t> acceptedImages_{0};
    std::atomic<std::uint64_t> captureResults_{0};
    std::atomic<std::uint64_t> captureFailures_{0};
    std::atomic<std::uint64_t> lostBuffers_{0};

    ACameraManager* cameraManager_=nullptr;
    ACameraDevice* cameraDevice_=nullptr;
    AImageReader* imageReader_=nullptr;
    ANativeWindow* imageWindow_=nullptr; // owned by imageReader_
    ACaptureSessionOutputContainer* outputContainer_=nullptr;
    ACaptureSessionOutput* sessionOutput_=nullptr;
    ACameraOutputTarget* outputTarget_=nullptr;
    ACaptureRequest* captureRequest_=nullptr;
    ACameraCaptureSession* captureSession_=nullptr;
};

} // namespace kc
