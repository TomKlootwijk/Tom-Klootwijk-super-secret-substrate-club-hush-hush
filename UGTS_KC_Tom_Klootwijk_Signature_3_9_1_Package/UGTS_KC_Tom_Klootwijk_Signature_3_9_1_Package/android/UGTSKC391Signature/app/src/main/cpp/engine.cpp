#include "engine.hpp"
#include <android/api-level.h>
#include <android/log.h>
#include <dlfcn.h>
#include <sys/system_properties.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <thread>

#define KC_LOGI(...) __android_log_print(ANDROID_LOG_INFO,"UGTS-KC391",__VA_ARGS__)
#define KC_LOGE(...) __android_log_print(ANDROID_LOG_ERROR,"UGTS-KC391",__VA_ARGS__)

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

bool Engine::initializeWindow() {
    if (!app_->window) return false;
    try {
        scene_=parseScenePack(readAsset("signature_scene.kc3d"));
    } catch (...) {
        KC_LOGE("failed to parse signature_scene.kc3d");
        return false;
    }
    nodes_=scene_.nodes;
    if (!renderer_.initialize(app_->window,app_->activity->assetManager,scene_)) {
        KC_LOGE("GLES3 renderer initialization failed");
        return false;
    }
    profile_=selectProfile(scene_,deviceInfo(),UGTS_KC_PROFILE_HINT);
    qualityIndex_=0;
    for (std::size_t i=0;i<scene_.qualities.size();++i) if (scene_.qualities[i].id==profile_.qualityId) qualityIndex_=i;
    adaptive_=AdaptiveQuality(qualityIndex_);
    requestFrameRate(static_cast<float>(profile_.targetFps));
    const auto info=deviceInfo();
    KC_LOGI("UGTS-KC 3.9.1 profile=%s quality=%s fps=%u scale=%.2f model=%s gpu=%s ram=%uMB",
        profile_.profileId.c_str(),profile_.qualityId.c_str(),profile_.targetFps,profile_.renderScale,
        info.model.c_str(),info.gpu.c_str(),info.ramMb);
    return true;
}

void Engine::terminateWindow() { renderer_.shutdown(); }

NodeData* Engine::player() {
    for (auto& node:nodes_) if (node.alive && (node.tagMask&TagPlayer)) return &node;
    return nullptr;
}

float Engine::colliderRadius(const NodeData& node) const {
    const float scale=std::max({std::abs(node.scale.x),std::abs(node.scale.y),std::abs(node.scale.z)});
    if (node.collider.type==1) return node.collider.radius*scale;
    if (node.collider.type==2) return length({node.collider.halfExtents.x*node.scale.x,node.collider.halfExtents.y*node.scale.y,node.collider.halfExtents.z*node.scale.z});
    return 0;
}

void Engine::fixedUpdate(float dt) {
    for (auto& node:nodes_) {
        if (!node.alive) continue;
        const float angular=length(node.angularVelocity);
        if (angular>1.0e-5f) node.rotation=normalize(multiply(axisAngle(node.angularVelocity/angular,angular*dt),node.rotation));
    }
    NodeData* p=player();
    if (!p) return;
    p->velocity.x=moveX_*scene_.playerSpeed;
    p->velocity.z=moveZ_*scene_.playerSpeed;
    const float verticalExtent=p->collider.type==1?p->collider.radius*std::abs(p->scale.y):p->collider.halfExtents.y*std::abs(p->scale.y);
    const bool grounded=p->translation.y-verticalExtent<=scene_.floorY+0.02f;
    if (jump_ && grounded) p->velocity.y=scene_.jumpSpeed;
    jump_=false;
    if (p->dynamic) p->velocity=p->velocity+scene_.gravity*dt;
    p->translation=p->translation+p->velocity*dt;
    if (p->translation.y-verticalExtent<scene_.floorY) {
        p->translation.y=scene_.floorY+verticalExtent;
        if (p->velocity.y<0) p->velocity.y=0;
    }
    const float radius=colliderRadius(*p);
    p->translation.x=clamp(p->translation.x,scene_.boundsMin.x+radius,scene_.boundsMax.x-radius);
    p->translation.z=clamp(p->translation.z,scene_.boundsMin.z+radius,scene_.boundsMax.z-radius);
    cameraTarget_=p->translation+Vec3{0,1,0};
    for (auto& node:nodes_) {
        if (!node.alive || &node==p) continue;
        const float distance=length(node.translation-p->translation);
        if (distance>radius+colliderRadius(node)) continue;
        if (node.tagMask&TagCollectible) {
            node.alive=false; ++score_;
            KC_LOGI("collectible %s score=%d",node.id.c_str(),score_);
        } else if (node.tagMask&TagGoal) {
            KC_LOGI("signature goal reached, score=%d",score_);
        }
    }
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
    const auto& quality=scene_.qualities[std::min(qualityIndex_,scene_.qualities.size()-1)];
    renderer_.render(scene_,nodes_,cameraTarget_,yaw_,pitch_,distance_,quality.renderScale,quality.maxVisibleNodes,time_);
}

int Engine::handleInput(AInputEvent* event) {
    const int type=AInputEvent_getType(event);
    if (type==AINPUT_EVENT_TYPE_KEY) {
        const int key=AKeyEvent_getKeyCode(event);
        const bool down=AKeyEvent_getAction(event)!=AKEY_EVENT_ACTION_UP;
        if (key==AKEYCODE_W || key==AKEYCODE_DPAD_UP) moveZ_=down?-1.0f:0.0f;
        else if (key==AKEYCODE_S || key==AKEYCODE_DPAD_DOWN) moveZ_=down?1.0f:0.0f;
        else if (key==AKEYCODE_A || key==AKEYCODE_DPAD_LEFT) moveX_=down?-1.0f:0.0f;
        else if (key==AKEYCODE_D || key==AKEYCODE_DPAD_RIGHT) moveX_=down?1.0f:0.0f;
        else if ((key==AKEYCODE_SPACE || key==AKEYCODE_BUTTON_A) && down) jump_=true;
        else return 0;
        return 1;
    }
    if (type!=AINPUT_EVENT_TYPE_MOTION) return 0;
    const int source=AInputEvent_getSource(event);
    if (source&AINPUT_SOURCE_JOYSTICK) {
        moveX_=AMotionEvent_getAxisValue(event,AMOTION_EVENT_AXIS_X,0);
        moveZ_=AMotionEvent_getAxisValue(event,AMOTION_EVENT_AXIS_Y,0);
        lookX_=AMotionEvent_getAxisValue(event,AMOTION_EVENT_AXIS_Z,0);
        lookY_=AMotionEvent_getAxisValue(event,AMOTION_EVENT_AXIS_RZ,0);
        return 1;
    }
    const int action=AMotionEvent_getAction(event)&AMOTION_EVENT_ACTION_MASK;
    const float x=AMotionEvent_getX(event,0), y=AMotionEvent_getY(event,0);
    if (action==AMOTION_EVENT_ACTION_DOWN) {
        touchStartX_=lastTouchX_=x; touchStartY_=lastTouchY_=y;
        touchMove_=x<renderer_.width()*0.45f; touchLook_=!touchMove_;
        return 1;
    }
    if (action==AMOTION_EVENT_ACTION_MOVE) {
        if (touchMove_) {
            const float radius=std::max(80.0f,renderer_.width()*0.12f);
            moveX_=clamp((x-touchStartX_)/radius,-1,1);
            moveZ_=clamp((y-touchStartY_)/radius,-1,1);
        } else if (touchLook_) {
            yaw_-=(x-lastTouchX_)*0.006f;
            pitch_=clamp(pitch_-(y-lastTouchY_)*0.006f,-0.05f,1.25f);
        }
        if (AMotionEvent_getPointerCount(event)>=2) {
            const float x1=AMotionEvent_getX(event,1), y1=AMotionEvent_getY(event,1);
            const float spacing=std::hypot(x1-x,y1-y);
            static float previousSpacing=spacing;
            distance_=clamp(distance_-(spacing-previousSpacing)*0.02f,5.0f,30.0f);
            previousSpacing=spacing;
        }
        lastTouchX_=x; lastTouchY_=y;
        return 1;
    }
    if (action==AMOTION_EVENT_ACTION_UP || action==AMOTION_EVENT_ACTION_CANCEL) {
        if (touchMove_) moveX_=moveZ_=0;
        touchMove_=touchLook_=false;
        return 1;
    }
    return 0;
}

} // namespace kc
