#include "engine.hpp"
#include "body_physics.hpp"
#include <android/api-level.h>
#include <android/log.h>
#include <dlfcn.h>
#include <sys/system_properties.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <thread>

#define KC_LOGI(...) __android_log_print(ANDROID_LOG_INFO,"UGTS-KC392",__VA_ARGS__)
#define KC_LOGE(...) __android_log_print(ANDROID_LOG_ERROR,"UGTS-KC392",__VA_ARGS__)

#ifndef UGTS_KC_PROFILE_HINT
#define UGTS_KC_PROFILE_HINT "auto"
#endif

namespace kc {
namespace {
std::string property(const char* name) {
    char value[PROP_VALUE_MAX]{};
    __system_property_get(name,value);
    return value;
}
std::uint32_t ramMb() {
    std::ifstream file("/proc/meminfo");
    std::string key,unit; std::uint64_t kb=0;
    if (file>>key>>kb>>unit) return static_cast<std::uint32_t>(kb/1024);
    return 4096;
}
float touchDensityScale(const android_app* app) {
    if (!app || !app->config) return 1.0f;
    const auto density=AConfiguration_getDensity(app->config);
    // Android reserves 0xfffe/0xffff for ANY/NONE. Treat those, zero, and
    // implausible vendor values as the mdpi fallback instead of creating an
    // enormous tap radius.
    if (density<72 || density>1000) return 1.0f;
    return clamp(static_cast<float>(density)/160.0f,0.75f,4.0f);
}
} // namespace

Engine::Engine(android_app* app):app_(app) {}

std::vector<std::uint8_t> Engine::readAsset(const char* path) {
    AAsset* asset=AAssetManager_open(app_->activity->assetManager,path,AASSET_MODE_BUFFER);
    if (!asset) return {};
    const auto length=AAsset_getLength(asset);
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(length));
    if (length>0) AAsset_read(asset,bytes.data(),length);
    AAsset_close(asset);
    return bytes;
}

DeviceInfo Engine::deviceInfo() const {
    DeviceInfo info;
    info.model=property("ro.product.model");
    info.manufacturer=property("ro.product.manufacturer");
    info.gpu=renderer_.gpuRenderer();
    info.ramMb=ramMb();
    info.cpuCores=std::max(1u,std::thread::hardware_concurrency());
    info.glesMajor=3; info.glesMinor=0;
    const std::string text=info.manufacturer+" "+info.model;
    info.refreshHz=(text.find("POCO X7 Pro")!=std::string::npos || text.find("2412DPC0")!=std::string::npos)?120.0f:60.0f;
    return info;
}

void Engine::requestFrameRate(float fps) {
    using Function=int(*)(ANativeWindow*,float,std::int8_t);
    void* library=dlopen("libandroid.so",RTLD_NOW);
    if (!library) return;
    auto function=reinterpret_cast<Function>(dlsym(library,"ANativeWindow_setFrameRate"));
    if (function && app_->window) function(app_->window,fps,0);
    dlclose(library);
}

int Engine::thermalStatus() const {
    if (android_get_device_api_level()<29) return 0;
    JNIEnv* env=nullptr;
    bool detach=false;
    if (app_->activity->vm->GetEnv(reinterpret_cast<void**>(&env),JNI_VERSION_1_6)!=JNI_OK) {
        if (app_->activity->vm->AttachCurrentThread(&env,nullptr)!=JNI_OK) return 0;
        detach=true;
    }
    int result=0;
    jclass activityClass=env->GetObjectClass(app_->activity->clazz);
    jmethodID getSystemService=env->GetMethodID(activityClass,"getSystemService","(Ljava/lang/String;)Ljava/lang/Object;");
    jstring powerName=env->NewStringUTF("power");
    jobject manager=env->CallObjectMethod(app_->activity->clazz,getSystemService,powerName);
    env->DeleteLocalRef(powerName);
    if (manager) {
        jclass managerClass=env->GetObjectClass(manager);
        jmethodID getStatus=env->GetMethodID(managerClass,"getCurrentThermalStatus","()I");
        if (getStatus) result=env->CallIntMethod(manager,getStatus);
        env->DeleteLocalRef(managerClass);
        env->DeleteLocalRef(manager);
    }
    env->DeleteLocalRef(activityClass);
    if (env->ExceptionCheck()) { env->ExceptionClear(); result=0; }
    if (detach) app_->activity->vm->DetachCurrentThread();
    return result;
}

bool Engine::loadContent() {
    if (contentLoaded_) return true;
    try {
        scene_=parseScenePack(readAsset("signature_scene.kc3d"));
        if (!std::isfinite(scene_.fixedDt) || scene_.fixedDt<=0.0f || scene_.fixedDt>0.25f)
            throw std::runtime_error("scene fixedDt must be finite and in (0, 0.25]");
        if (scene_.qualities.empty()) throw std::runtime_error("scene needs at least one quality tier");
        nodes_=scene_.nodes;
        // Capture parent-local child TRS before any component or world
        // composition mutates the flat NodeData consumed by gameplay/rendering.
        transformHierarchy_.load(readAsset("hierarchies.kchi"),nodes_);
        particles_.clear();
        renderNodes_.clear();
        const auto polarBytes=readAsset("packed_kinematics.kcpk");
        polarKinematics_.load(polarBytes,nodes_);
        polarKinematics_.compose(nodes_);
        const auto animationBytes=readAsset("transform_animations.kcan");
        transformAnimations_.load(animationBytes,nodes_);
        transformAnimations_.compose(nodes_);
        const auto scatterBytes=readAsset("scatter_populations.kcsp");
        scatterPopulations_.load(scatterBytes,nodes_);
        const auto graphBytes=readAsset("visual_graphs.kcvg");
        if (!graphBytes.empty()) graphVm_.load(graphBytes,nodes_.size());
        graphVm_.setTransformAnimations(&transformAnimations_);
        transformHierarchy_.compose(nodes_);
    } catch (const std::exception& error) {
        KC_LOGE("failed to load game content: %s",error.what());
        return false;
    }
    contentLoaded_=true;
    return true;
}

bool Engine::initializeWindow() {
    if (!app_->window || !loadContent()) return false;
    if (!renderer_.initialize(
            app_->window,
            app_->activity->assetManager,
            scene_,
            scatterPopulations_
        )) {
        KC_LOGE("GLES3 renderer initialization failed");
        return false;
    }
    const auto info=deviceInfo();
    tuning_=selectGroveTuning(info);
    juice_.configure(tuning_.juiceIntensity,1.0f,1.0f+tuning_.bloom*0.5f);
    profile_=selectProfile(scene_,info,UGTS_KC_PROFILE_HINT);
    qualityIndex_=0;
    for (std::size_t i=0;i<scene_.qualities.size();++i) if (scene_.qualities[i].id==profile_.qualityId) qualityIndex_=i;
    adaptive_=AdaptiveQuality(qualityIndex_);
    requestFrameRate(static_cast<float>(profile_.targetFps));
    if (!graphReady_) {
        graphVm_.ready(nodes_);
        // Ready may move an ancestor, so descendants need a fresh world pose
        // before the first rendered frame.
        transformHierarchy_.compose(nodes_);
        reportGraphResults();
        graphReady_=true;
    }
    KC_LOGI("UGTS-KC 3.9.2 profile=%s grove=%s quality=%s fps=%u scale=%.2f model=%s gpu=%s ram=%uMB juice=%.2f",
        profile_.profileId.c_str(),tuning_.profileId.c_str(),profile_.qualityId.c_str(),profile_.targetFps,profile_.renderScale,
        info.model.c_str(),info.gpu.c_str(),info.ramMb,tuning_.juiceIntensity);
    return true;
}

void Engine::terminateWindow() { renderer_.shutdown(); }

GraphInputState Engine::graphInputState() const {
    GraphInputState result;
    result.moveX=moveX_; result.moveZ=moveZ_;
    result.lookX=lookX_; result.lookY=lookY_;
    result.jump=jump_; result.dash=dash_;
    return result;
}

void Engine::reportGraphResults() {
    for (const auto& issue:graphVm_.issues()) {
        const auto graph=graphVm_.graphId(issue.graph);
        KC_LOGE("visual graph %.*s node=%u disabled: %s",
            static_cast<int>(graph.size()),graph.data(),static_cast<unsigned>(issue.node),graphVmErrorName(issue.code));
    }
    for (const auto& event:graphVm_.events()) {
        const char* source=event.source>=0 && static_cast<std::size_t>(event.source)<nodes_.size()?nodes_[static_cast<std::size_t>(event.source)].id.c_str():"-";
        const char* target=event.target>=0 && static_cast<std::size_t>(event.target)<nodes_.size()?nodes_[static_cast<std::size_t>(event.target)].id.c_str():"-";
        KC_LOGI("visual graph event=%.*s source=%s target=%s",
            static_cast<int>(event.kind.size()),event.kind.data(),source,target);
    }
}

void Engine::dispatchTriggerAreas(float dt,const GraphInputState& input) {
    const auto transitions=triggerAreas_.update(nodes_);
    if (triggerAreas_.sensorLimitReached() && !triggerSensorLimitLogged_) {
        KC_LOGE("trigger areas capped at %u sensors",static_cast<unsigned>(TriggerAreaTracker::MaxSensors));
        triggerSensorLimitLogged_=true;
    }
    const GraphInputFrame frame{input,previousGraphInput_};
    for (const auto& transition:transitions) {
        graphVm_.trigger(
            transition.transition==TriggerTransition::Enter,
            transition.sensor,transition.player,dt,fixedTick_,frame,nodes_
        );
    }
}

NodeData* Engine::player() {
    for (auto& node:nodes_) if (node.alive && node.active && (node.tagMask&TagPlayer)) return &node;
    return nullptr;
}

float Engine::colliderRadius(const NodeData& node) const {
    return bodyBoundingRadius(node);
}

void Engine::triggerJuice(std::uint32_t kind, const Vec3& origin, float intensity) {
    juice_.event(kind,intensity);
    spawnBurst(origin,kind,intensity);
}

void Engine::spawnBurst(const Vec3& origin, std::uint32_t kind, float intensity) {
    if (tuning_.particleBudget==0 || scene_.meshes.empty() || scene_.materials.empty()) return;
    const char* materialId=(kind==GroveJuice::Hazard)?"hazard":(kind==GroveJuice::Dash)?"signature_cyan":"signature_gold";
    std::size_t meshIndex=scene_.meshes.size(), materialIndex=scene_.materials.size();
    for (std::size_t i=0;i<scene_.meshes.size();++i) if (scene_.meshes[i].id=="sphere") { meshIndex=i; break; }
    for (std::size_t i=0;i<scene_.materials.size();++i) if (scene_.materials[i].id==materialId) { materialIndex=i; break; }
    if (meshIndex==scene_.meshes.size() || materialIndex==scene_.materials.size()) return;
    const std::uint32_t requested=kind==GroveJuice::Goal?42u:(kind==GroveJuice::Hazard?22u:(kind==GroveJuice::Pickup?16u:8u));
    const auto count=std::min<std::uint32_t>(requested,std::max(4u,tuning_.particleBudget/8u));
    const float strength=clamp(intensity,0.25f,1.0f);
    particles_.reserve(std::min<std::size_t>(tuning_.particleBudget,particles_.size()+count));
    for (std::uint32_t i=0;i<count;++i) {
        const float phase=time_*4.0f+static_cast<float>(i)*2.39996323f+static_cast<float>(particles_.size())*0.173f;
        const float speed=(1.4f+0.16f*static_cast<float>(i%7))*strength;
        const float size=(kind==GroveJuice::Goal?0.105f:0.070f)*(0.8f+0.06f*static_cast<float>(i%5));
        EffectParticle particle;
        particle.node.id="grove_burst";
        particle.node.meshIndex=static_cast<std::uint32_t>(meshIndex);
        particle.node.materialIndex=static_cast<std::uint32_t>(materialIndex);
        particle.node.translation=origin;
        particle.node.scale={size,size,size};
        particle.startScale=particle.node.scale;
        particle.node.velocity={std::cos(phase)*speed,1.4f+0.16f*static_cast<float>(i%6),std::sin(phase)*speed};
        particle.node.angularVelocity={0.8f+0.1f*static_cast<float>(i%4),1.6f+0.12f*static_cast<float>(i%5),0.45f};
        particle.node.collider.type=0;
        particle.node.tagMask=TagDecorative;
        particle.lifetime=kind==GroveJuice::Goal?1.15f:0.65f;
        particles_.push_back(std::move(particle));
    }
    const auto budget=static_cast<std::size_t>(tuning_.particleBudget);
    if (particles_.size()>budget) particles_.erase(particles_.begin(),particles_.begin()+static_cast<std::ptrdiff_t>(particles_.size()-budget));
}

void Engine::updateParticles(float dt) {
    for (auto& particle:particles_) {
        particle.age+=dt;
        particle.node.velocity.y-=5.5f*dt;
        particle.node.translation=particle.node.translation+particle.node.velocity*dt;
        const float life=clamp(1.0f-particle.age/particle.lifetime,0.0f,1.0f);
        particle.node.scale=particle.startScale*(0.35f+life*0.9f);
        const float angular=length(particle.node.angularVelocity);
        if (angular>1.0e-5f) particle.node.rotation=normalize(multiply(axisAngle(particle.node.angularVelocity/angular,angular*dt),particle.node.rotation));
    }
    particles_.erase(std::remove_if(particles_.begin(),particles_.end(),[](const EffectParticle& particle){ return particle.age>=particle.lifetime; }),particles_.end());
}

void Engine::fixedUpdate(float dt) {
    const auto currentInput=graphInputState();
    // Packed transform components are authoritative at the beginning of the
    // fixed step, so learner graphs see their freshly composed NodeData.
    polarKinematics_.tick(dt,nodes_);
    transformAnimations_.tick(dt,nodes_);
    // Animation graph actions run after this tick. Play composes time zero
    // immediately, then the selected clip advances on the next fixed update.
    graphVm_.tick(dt,fixedTick_,GraphInputFrame{currentInput,previousGraphInput_},nodes_);
    updateParticles(dt);
    hazardCooldown_=std::max(0.0f,hazardCooldown_-dt);
    goalCooldown_=std::max(0.0f,goalCooldown_-dt);
    for (auto& node:nodes_) {
        if (!node.alive || !node.active) continue;
        const float angular=length(node.angularVelocity);
        if (angular>1.0e-5f) node.rotation=normalize(multiply(axisAngle(node.angularVelocity/angular,angular*dt),node.rotation));
    }
    NodeData* p=player();
    const std::size_t playerIndex=p
        ?static_cast<std::size_t>(p-nodes_.data())
        :NoBodyExclusion;
    // Tick graphs (including Apply Force) before every generic dynamic body,
    // while the existing Player controller remains the single owner of Player
    // translation, grounding, and bounds behavior.
    integrateDynamicBodies(nodes_,scene_.gravity,dt,playerIndex);
    constrainDynamicBodies(
        nodes_,scene_.floorY,scene_.boundsMin,scene_.boundsMax,playerIndex
    );
    if (!p) {
        static_cast<void>(resolveDynamicBodyPairs(nodes_));
        dispatchTriggerAreas(dt,currentInput);
        graphVm_.finishStep(dt,fixedTick_,GraphInputFrame{currentInput,previousGraphInput_},nodes_);
        transformHierarchy_.compose(nodes_);
        ++fixedTick_;
        reportGraphResults();
        previousGraphInput_=currentInput;
        jump_=false; dash_=false;
        return;
    }
    if (dash_ && dashTimer_<=0.0f) {
        dashDirection_={moveX_,0.0f,moveZ_};
        if (length(dashDirection_)<0.1f) dashDirection_={-std::sin(yaw_),0.0f,-std::cos(yaw_)};
        else dashDirection_=normalize(dashDirection_);
        dashTimer_=0.18f;
        triggerJuice(GroveJuice::Dash,p->translation,0.9f);
    }
    dash_=false;
    const float dashSpeed=dashTimer_>0.0f?scene_.playerSpeed*1.35f:0.0f;
    p->velocity.x=moveX_*scene_.playerSpeed+dashDirection_.x*dashSpeed;
    p->velocity.z=moveZ_*scene_.playerSpeed+dashDirection_.z*dashSpeed;
    const float verticalExtent=p->collider.type==1?p->collider.radius*std::abs(p->scale.y):p->collider.halfExtents.y*std::abs(p->scale.y);
    const bool grounded=p->translation.y-verticalExtent<=scene_.floorY+0.02f;
    if (grounded && !groundedLast_) triggerJuice(GroveJuice::Land,p->translation,1.0f);
    if (jump_ && grounded) { p->velocity.y=scene_.jumpSpeed; triggerJuice(GroveJuice::Jump,p->translation,0.75f); }
    jump_=false;
    groundedLast_=grounded;
    if (p->dynamic) p->velocity=p->velocity+scene_.gravity*dt;
    p->translation=p->translation+p->velocity*dt;
    if (p->translation.y-verticalExtent<scene_.floorY) {
        p->translation.y=scene_.floorY+verticalExtent;
        if (p->velocity.y<0) p->velocity.y=0;
    }
    const float radius=colliderRadius(*p);
    p->translation.x=clamp(p->translation.x,scene_.boundsMin.x+radius,scene_.boundsMax.x-radius);
    p->translation.z=clamp(p->translation.z,scene_.boundsMin.z+radius,scene_.boundsMax.z-radius);
    static_cast<void>(resolveDynamicBodyPairs(nodes_));
    dispatchTriggerAreas(dt,currentInput);
    for (auto& node:nodes_) {
        if (!node.alive || !node.active || &node==p) continue;
        const float distance=length(node.translation-p->translation);
        if (distance>radius+colliderRadius(node)) continue;
        if (node.tagMask&TagCollectible) {
            node.alive=false; ++score_;
            triggerJuice(GroveJuice::Pickup,node.translation,1.0f);
            KC_LOGI("collectible %s score=%d",node.id.c_str(),score_);
        } else if ((node.tagMask&TagHazard) && hazardCooldown_<=0.0f) {
            const Vec3 delta=p->translation-node.translation;
            const Vec3 knockback=length(delta)>0.05f?normalize(delta):Vec3{0,0,1};
            p->translation=p->translation+knockback*0.72f;
            p->velocity=p->velocity+knockback*(scene_.playerSpeed*0.75f);
            hazardCooldown_=0.65f;
            triggerJuice(GroveJuice::Hazard,node.translation,1.0f);
        } else if (node.tagMask&TagGoal) {
            if (goalCooldown_<=0.0f) {
                KC_LOGI("goal reached, score=%d",score_);
                goalCooldown_=1.5f;
                triggerJuice(GroveJuice::Goal,node.translation,1.0f);
            }
        }
    }
    graphVm_.finishStep(dt,fixedTick_,GraphInputFrame{currentInput,previousGraphInput_},nodes_);
    // Graph completion and tag gameplay are the final transform writers in a
    // fixed step. Publish deterministic child world TRS only after both.
    transformHierarchy_.compose(nodes_);
    dashTimer_=std::max(0.0f,dashTimer_-dt);
    cameraTarget_=p->translation+Vec3{0,1,0};
    ++fixedTick_;
    reportGraphResults();
    previousGraphInput_=currentInput;
}

void Engine::frame(float dt) {
    if (!ready() || !focused_) return;
    dt=clamp(dt,0.0f,0.1f);
    accumulator_+=dt; time_+=dt;
    while (accumulator_>=scene_.fixedDt) {
        fixedUpdate(scene_.fixedDt);
        accumulator_-=scene_.fixedDt;
    }
    yaw_+=lookX_*dt*1.8f; pitch_=clamp(pitch_+lookY_*dt*1.4f,-0.05f,1.25f);
    fpsAccumulator_+=dt; ++fpsFrames_;
    if (fpsAccumulator_>=1.0f) {
        measuredFps_=fpsFrames_/fpsAccumulator_;
        lastThermal_=thermalStatus();
        qualityIndex_=adaptive_.update(scene_,measuredFps_,static_cast<float>(profile_.targetFps),lastThermal_,fpsAccumulator_);
        fpsAccumulator_=0; fpsFrames_=0;
    }
    juice_.update(dt,time_);
    const auto juice=juice_.frame();
    const float shake=juice.cameraShake;
    if (shake>0.001f) {
        const float sx=std::sin(time_*46.0f)*shake;
        const float sy=std::cos(time_*39.0f)*shake*0.7f;
        cameraTarget_.x += sx*0.035f; cameraTarget_.y += sy*0.025f;
    }
    const auto& quality=scene_.qualities[std::min(qualityIndex_,scene_.qualities.size()-1)];
    const bool usePost=tuning_.post && quality.postProcessing;
    renderNodes_=nodes_;
    renderNodes_.reserve(nodes_.size()+particles_.size());
    for (const auto& particle:particles_) renderNodes_.push_back(particle.node);
    renderer_.render(scene_,renderNodes_,cameraTarget_,yaw_,pitch_,distance_,quality.renderScale,quality.maxVisibleNodes,time_,juice,usePost);
}

int Engine::handleInput(AInputEvent* event) {
    const int type=AInputEvent_getType(event);
    if (type==AINPUT_EVENT_TYPE_KEY) {
        const int key=AKeyEvent_getKeyCode(event);
        const bool down=AKeyEvent_getAction(event)!=AKEY_EVENT_ACTION_UP;
        const bool repeated=down && AKeyEvent_getRepeatCount(event)>0;
        if (key==AKEYCODE_W || key==AKEYCODE_DPAD_UP) moveZ_=down?-1.0f:0.0f;
        else if (key==AKEYCODE_S || key==AKEYCODE_DPAD_DOWN) moveZ_=down?1.0f:0.0f;
        else if (key==AKEYCODE_A || key==AKEYCODE_DPAD_LEFT) moveX_=down?-1.0f:0.0f;
        else if (key==AKEYCODE_D || key==AKEYCODE_DPAD_RIGHT) moveX_=down?1.0f:0.0f;
        else if (key==AKEYCODE_SPACE) {
            if (down && !repeated) { jump_=true; dash_=true; }
        }
        else if (key==AKEYCODE_J || key==AKEYCODE_BUTTON_A) { if (down && !repeated) jump_=true; }
        else if (key==AKEYCODE_ENTER || key==AKEYCODE_SHIFT_LEFT ||
                key==AKEYCODE_SHIFT_RIGHT || key==AKEYCODE_BUTTON_B) {
            if (down && !repeated) dash_=true;
        }
        else return 0;
        return 1;
    }
    if (type!=AINPUT_EVENT_TYPE_MOTION) return 0;
    const int source=AInputEvent_getSource(event);
    if ((source&AINPUT_SOURCE_JOYSTICK)==AINPUT_SOURCE_JOYSTICK) {
        moveX_=AMotionEvent_getAxisValue(event,AMOTION_EVENT_AXIS_X,0);
        moveZ_=AMotionEvent_getAxisValue(event,AMOTION_EVENT_AXIS_Y,0);
        lookX_=AMotionEvent_getAxisValue(event,AMOTION_EVENT_AXIS_Z,0);
        lookY_=AMotionEvent_getAxisValue(event,AMOTION_EVENT_AXIS_RZ,0);
        return 1;
    }
    const int rawAction=AMotionEvent_getAction(event);
    const int maskedAction=rawAction&AMOTION_EVENT_ACTION_MASK;
    TouchAction touchAction;
    switch (maskedAction) {
        case AMOTION_EVENT_ACTION_DOWN: touchAction=TouchAction::Down; break;
        case AMOTION_EVENT_ACTION_POINTER_DOWN: touchAction=TouchAction::PointerDown; break;
        case AMOTION_EVENT_ACTION_MOVE: touchAction=TouchAction::Move; break;
        case AMOTION_EVENT_ACTION_POINTER_UP: touchAction=TouchAction::PointerUp; break;
        case AMOTION_EVENT_ACTION_UP: touchAction=TouchAction::Up; break;
        case AMOTION_EVENT_ACTION_CANCEL: touchAction=TouchAction::Cancel; break;
        default: return 0;
    }

    const auto pointerCount=static_cast<std::size_t>(AMotionEvent_getPointerCount(event));
    std::array<TouchPoint,TouchRouter::MaxPointers> points{};
    if (pointerCount>points.size()) return 0;
    for (std::size_t i=0;i<pointerCount;++i) {
        points[i]={
            AMotionEvent_getPointerId(event,i),
            AMotionEvent_getX(event,i),
            AMotionEvent_getY(event,i),
        };
    }
    std::int32_t changedId=-1;
    if (touchAction!=TouchAction::Move && touchAction!=TouchAction::Cancel) {
        const auto actionIndex=static_cast<std::size_t>(
            (rawAction&AMOTION_EVENT_ACTION_POINTER_INDEX_MASK)>>AMOTION_EVENT_ACTION_POINTER_INDEX_SHIFT
        );
        if (actionIndex>=pointerCount) return 0;
        changedId=points[actionIndex].id;
    }
    touchRouter_.setViewport(
        static_cast<float>(renderer_.width()),static_cast<float>(renderer_.height()),
        touchDensityScale(app_)
    );
    const auto update=touchRouter_.handle(TouchEvent{
        touchAction,changedId,std::span<const TouchPoint>(points.data(),pointerCount)
    });
    moveX_=update.moveX;
    moveZ_=update.moveZ;
    yaw_-=update.lookDeltaX*0.006f;
    pitch_=clamp(pitch_-update.lookDeltaY*0.006f,-0.05f,1.25f);
    distance_=clamp(distance_-update.zoomDelta*0.02f,5.0f,30.0f);
    if (update.jumpPressed) jump_=true;
    if (update.dashPressed) dash_=true;
    if (update.cancelled) jump_=dash_=false;
    return 1;
}

} // namespace kc
