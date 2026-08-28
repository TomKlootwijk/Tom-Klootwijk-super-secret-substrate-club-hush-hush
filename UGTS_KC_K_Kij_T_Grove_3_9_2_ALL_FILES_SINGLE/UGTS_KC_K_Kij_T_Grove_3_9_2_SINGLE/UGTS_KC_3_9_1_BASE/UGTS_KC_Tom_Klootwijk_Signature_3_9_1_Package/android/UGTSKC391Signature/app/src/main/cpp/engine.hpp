#pragma once
#include "adaptive_quality.hpp"
#include "device_profile.hpp"
#include "renderer_gles3.hpp"
#include <android/input.h>
#include <android_native_app_glue.h>
#include <chrono>
#include <vector>

namespace kc {

class Engine {
public:
    explicit Engine(android_app* app);
    bool initializeWindow();
    void terminateWindow();
    void setFocused(bool value) { focused_=value; }
    bool focused() const { return focused_; }
    bool ready() const { return renderer_.ready(); }
    int handleInput(AInputEvent* event);
    void frame(float dt);
private:
    std::vector<std::uint8_t> readAsset(const char* path);
    DeviceInfo deviceInfo() const;
    int thermalStatus() const;
    void requestFrameRate(float fps);
    void fixedUpdate(float dt);
    NodeData* player();
    float colliderRadius(const NodeData& node) const;
    android_app* app_;
    ScenePack scene_;
    std::vector<NodeData> nodes_;
    RendererGles3 renderer_;
    ProfileSelection profile_;
    AdaptiveQuality adaptive_;
    std::size_t qualityIndex_=0;
    bool focused_=false;
    float accumulator_=0,time_=0;
    float yaw_=0.68f,pitch_=0.42f,distance_=16.0f;
    Vec3 cameraTarget_{0,1,0};
    float moveX_=0,moveZ_=0,lookX_=0,lookY_=0;
    bool jump_=false;
    bool touchMove_=false,touchLook_=false;
    float touchStartX_=0,touchStartY_=0,lastTouchX_=0,lastTouchY_=0;
    int score_=0;
    float fpsAccumulator_=0;
    int fpsFrames_=0;
    float measuredFps_=60;
    int lastThermal_=0;
};

} // namespace kc
