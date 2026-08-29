#pragma once
#include "adaptive_quality.hpp"
#include "grove_juice.hpp"
#include "grove_tuning.hpp"
#include "device_profile.hpp"
#include "graph_vm.hpp"
#include "polar_kinematics.hpp"
#include "renderer_gles3.hpp"
#include "touch_router.hpp"
#include "trigger_area.hpp"
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
    struct EffectParticle {
        NodeData node;
        Vec3 startScale{};
        float age=0.0f;
        float lifetime=0.6f;
    };
    std::vector<std::uint8_t> readAsset(const char* path);
    bool loadContent();
    DeviceInfo deviceInfo() const;
    int thermalStatus() const;
    void requestFrameRate(float fps);
    void fixedUpdate(float dt);
    void triggerJuice(std::uint32_t kind, const Vec3& origin, float intensity=1.0f);
    void spawnBurst(const Vec3& origin, std::uint32_t kind, float intensity);
    void updateParticles(float dt);
    GraphInputState graphInputState() const;
    void reportGraphResults();
    void dispatchTriggerAreas(float dt,const GraphInputState& input);
    NodeData* player();
    float colliderRadius(const NodeData& node) const;
    android_app* app_;
    ScenePack scene_;
    std::vector<NodeData> nodes_;
    std::vector<EffectParticle> particles_;
    std::vector<NodeData> renderNodes_;
    RendererGles3 renderer_;
    ProfileSelection profile_;
    AdaptiveQuality adaptive_;
    GroveJuice juice_;
    GroveTuning tuning_;
    GraphVm graphVm_;
    PackedPolarKinematics polarKinematics_;
    std::size_t qualityIndex_=0;
    bool focused_=false;
    bool contentLoaded_=false,graphReady_=false;
    float accumulator_=0,time_=0;
    float yaw_=0.68f,pitch_=0.42f,distance_=16.0f;
    Vec3 cameraTarget_{0,1,0};
    float moveX_=0,moveZ_=0,lookX_=0,lookY_=0;
    bool jump_=false;
    bool dash_=false;
    GraphInputState previousGraphInput_{};
    std::uint64_t fixedTick_=0;
    TouchRouter touchRouter_;
    TriggerAreaTracker triggerAreas_;
    bool triggerSensorLimitLogged_=false;
    int score_=0;
    bool groundedLast_=false;
    Vec3 dashDirection_{};
    float dashTimer_=0.0f;
    float hazardCooldown_=0.0f;
    float goalCooldown_=0.0f;
    float fpsAccumulator_=0;
    int fpsFrames_=0;
    float measuredFps_=60;
    int lastThermal_=0;
};

} // namespace kc
