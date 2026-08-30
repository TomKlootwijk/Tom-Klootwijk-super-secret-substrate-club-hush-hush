#include "engine.hpp"
#include <android/log.h>
#include <chrono>
#include <thread>

namespace {
using SteadyClock=std::chrono::steady_clock;
std::int64_t steadyNowNanoseconds() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        SteadyClock::now().time_since_epoch()).count();
}
void command(android_app* app,int32_t cmd) {
    auto* engine=static_cast<kc::Engine*>(app->userData);
    switch (cmd) {
        case APP_CMD_INIT_WINDOW: engine->initializeWindow(steadyNowNanoseconds()); break;
        case APP_CMD_TERM_WINDOW: engine->terminateWindow(); break;
        case APP_CMD_GAINED_FOCUS: engine->setFocused(true,steadyNowNanoseconds()); break;
        case APP_CMD_LOST_FOCUS: engine->setFocused(false,steadyNowNanoseconds()); break;
        default: break;
    }
}
int32_t input(android_app* app,AInputEvent* event) {
    return static_cast<kc::Engine*>(app->userData)->handleInput(event);
}
}

void android_main(android_app* app) {
    // Force-link native_app_glue so NativeActivity can resolve ANativeActivity_onCreate.
    app_dummy();
    kc::Engine engine(app);
    app->userData=&engine;
    app->onAppCmd=command;
    app->onInputEvent=input;
    auto previous=SteadyClock::now();
    while (!app->destroyRequested) {
        android_poll_source* source=nullptr;
        const int timeout=(engine.ready() && engine.focused())?0:-1;
        int events=0;
        while (ALooper_pollOnce(timeout,nullptr,&events,reinterpret_cast<void**>(&source))>=0) {
            if (source) source->process(app,source);
            if (app->destroyRequested) break;
            // INIT_WINDOW and GAINED_FOCUS can arrive in the same blocking poll
            // cycle. Break as soon as both are true so the first frame is drawn.
            if (engine.ready() && engine.focused()) break;
        }
        const auto now=SteadyClock::now();
        const float dt=std::chrono::duration<float>(now-previous).count();
        previous=now;
        const auto nowNanoseconds=std::chrono::duration_cast<std::chrono::nanoseconds>(
            now.time_since_epoch()).count();
        engine.frame(dt,nowNanoseconds);
        if (engine.ready() && engine.focused()) std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    engine.terminateWindow();
}
