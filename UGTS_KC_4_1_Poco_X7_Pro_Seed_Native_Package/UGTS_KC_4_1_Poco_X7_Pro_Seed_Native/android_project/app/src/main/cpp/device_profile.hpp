#pragma once
#include "core/feature_extractor.hpp"
#include "core/kseed_codec.hpp"
#include <android/native_window.h>
#include <cstdint>
#include <string>
namespace ugts41::android {
struct DeviceInfo{std::string manufacturer,model,device,gpu;std::uint32_t ram_mb=0,cpu_cores=0;float display_refresh_hz=60;};
struct RuntimeProfile{std::string id="android_balanced";std::uint16_t camera_width=960,camera_height=540,camera_fps=30,presentation_fps=60;FeatureConfig features{};StorageMode storage_mode=StorageMode::SeedAndDeltas;std::size_t chunk_bytes=64U*1024U;bool poco_optimized=false;};
DeviceInfo detect_device_info(std::string gpu_renderer={});
RuntimeProfile select_runtime_profile(const DeviceInfo&,std::string requested="auto");
void request_window_frame_rate(ANativeWindow*,float fps);
}
