#pragma once
#include "camera_ndk.hpp"
#include "core/feature_extractor.hpp"
#include "core/ledger.hpp"
#include "core/pipeline.hpp"
#include "device_profile.hpp"
#include "imu_ndk.hpp"
#include "renderer_bayer.hpp"
#include "storage_android.hpp"
#include "thermal_policy.hpp"
#include <android/input.h>
#include <android_native_app_glue.h>
#include <chrono>
#include <memory>
#include <vector>
namespace ugts41::android {
class Engine{
public:explicit Engine(android_app*);~Engine();bool initialize_window();void terminate_window();void set_focused(bool v){focused_=v;}bool focused()const{return focused_;}bool ready()const{return renderer_.ready();}int handle_input(AInputEvent*);void frame(float dt);void shutdown();
private:std::vector<std::uint8_t>asset(const char*);std::uint64_t now_ns()const;std::uint64_t create_seed()const;void ensure_camera();void start_recording();void stop_recording();void commit(const EventProposal&);void process(const FrameObservation&,const std::vector<std::uint8_t>&analysis,std::uint64_t raw_bytes,bool synthetic);void synthetic_frame(std::uint64_t timestamp);void update_thermal();void reset_performance_metrics();void log_performance_metrics()const;
android_app*app_;RendererBayer renderer_;CameraNdk camera_;ImuNdk imu_;DeviceInfo device_{};RuntimeProfile profile_{};ThermalTuning thermal_{};std::unique_ptr<SeededFeatureExtractor>extractor_;KeyframeSelector selector_;SpatialLedger ledger_;DemoWorld demo_;std::unique_ptr<SessionStorage>storage_;SessionStats stats_{};std::vector<std::uint8_t>display_luma_;std::vector<FeaturePoint>display_features_;std::vector<std::uint32_t>processing_us_,capture_age_us_,render_us_;ViewMode mode_=ViewMode::Camera;bool focused_=false,recording_=false,camera_requested_=false;std::uint64_t session_seed_=0,last_processed_ns_=0,last_thermal_ns_=0,permission_retry_ns_=0,perf_start_ns_=0,last_camera_sequence_=0,camera_overwritten_=0;std::uint32_t frame_index_=0,render_sample_counter_=0;float down_x_=0,time_=0;std::array<std::uint8_t,32>profile_hash_{};
};
}
