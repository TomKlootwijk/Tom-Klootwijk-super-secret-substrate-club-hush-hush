#include "engine.hpp"
#include <android/log.h>
#include <chrono>
#include <thread>

namespace {
void command(android_app* app,int32_t cmd) {
    auto* engine=static_cast<kc::Engine*>(app->userData);
    switch (cmd) {
        case APP_CMD_INIT_WINDOW: engine->initializeWindow(); break;
        case APP_CMD_TERM_WINDOW: engine->terminateWindow(); break;
        case APP_CMD_GAINED_FOCUS: engine->setFocused(true); break;
        case APP_CMD_LOST_FOCUS: engine->setFocused(false); break;
        default: break;
    }
}
int32_t input(android_app* app,AInputEvent* event) {
    return static_cast<kc::Engine*>(app->userData)->handleInput(event);
}
}

void android_main(android_app* app) {
    app_dummy();
    kc::Engine engine(app);
    app->userData=&engine;
    app->onAppCmd=command;
    app->onInputEvent=input;
    using clock=std::chrono::steady_clock;
    auto previous=clock::now();
    while (!app->destroyRequested) {
        android_poll_source* source=nullptr;
        const int timeout=(engine.ready() && engine.focused())?0:-1;
        int events=0;
        ALooper_pollOnce(timeout,nullptr,&events,reinterpret_cast<void**>(&source));
        if (source) source->process(app,source);
        if (app->destroyRequested) break;
        const auto now=clock::now();
        const float dt=std::chrono::duration<float>(now-previous).count();
        previous=now;
        engine.frame(dt);
        if (engine.ready() && engine.focused()) std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    engine.terminateWindow();
}
