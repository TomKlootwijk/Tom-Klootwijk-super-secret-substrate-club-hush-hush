#pragma once

#include "chrono_camera_recorder.hpp"
#include "yuv_seed_capture.hpp"

#include <android/native_activity.h>

#include <atomic>
#include <cstdint>
#include <memory>
#include <string>
#include <thread>
#include <vector>

namespace kc {

enum class ChronoSeedCaptureState : std::uint8_t {
    Absent=0,
    Configured,
    AwaitingPermission,
    Capturing,
    Finalizing,
    Complete,
    Failed,
};

class ChronoSeedCaptureSession final {
public:
    ChronoSeedCaptureSession()=default;
    ~ChronoSeedCaptureSession();
    ChronoSeedCaptureSession(const ChronoSeedCaptureSession&)=delete;
    ChronoSeedCaptureSession& operator=(const ChronoSeedCaptureSession&)=delete;

    bool configure(
        ANativeActivity* activity,
        const ChronoSceneBinding& binding,
        std::vector<std::uint8_t> literalUglut2
    );
    bool requestStart();
    void stopAndFinalize();
    void abort();
    void pump();

    ChronoSeedCaptureState state() const { return state_.load(std::memory_order_acquire); }
    bool configured() const { return state()!=ChronoSeedCaptureState::Absent; }
    std::uint32_t ownerNodeIndex() const { return binding_.nodeIndex; }
    bool autostart() const { return binding_.autostart; }
    const std::string& finalPath() const { return finalPath_; }

private:
    bool startAuthorized();
    void runWriter();
    void joinWriter();
    void fail(const char* detail);
    bool finalizeAndReplay();

    ANativeActivity* activity_=nullptr;
    ChronoSceneBinding binding_{};
    std::vector<std::uint8_t> literalUglut2_;
    ChronoCameraRecorder camera_{};
    std::unique_ptr<ugts::chrono::YuvSeedCaptureWriter> writer_;
    std::thread writerThread_;
    std::atomic<bool> startRequested_{false};
    std::atomic<bool> writerStopRequested_{false};
    std::atomic<bool> writerFailed_{false};
    std::atomic<ChronoSeedCaptureState> state_{ChronoSeedCaptureState::Absent};
    std::string partialPath_;
    std::string finalPath_;
};

} // namespace kc
