#include "bayer_core.h"

typedef unsigned long bd_size_t;
typedef unsigned long bd_pthread_t;
typedef struct BdJavaVM BdJavaVM;
typedef struct BdJNIEnv BdJNIEnv;
typedef void* bd_jobject;
typedef struct AAssetManager AAssetManager;
typedef struct ANativeWindow ANativeWindow;
typedef struct AInputQueue AInputQueue;

typedef struct ARect {
    bd_i32 left;
    bd_i32 top;
    bd_i32 right;
    bd_i32 bottom;
} ARect;

typedef struct ANativeWindow_Buffer {
    bd_i32 width;
    bd_i32 height;
    bd_i32 stride;
    bd_i32 format;
    void* bits;
    bd_u32 reserved[6];
} ANativeWindow_Buffer;

typedef struct ANativeActivity ANativeActivity;
typedef struct ANativeActivityCallbacks {
    void (*onStart)(ANativeActivity* activity);
    void (*onResume)(ANativeActivity* activity);
    void* (*onSaveInstanceState)(ANativeActivity* activity, bd_size_t* outSize);
    void (*onPause)(ANativeActivity* activity);
    void (*onStop)(ANativeActivity* activity);
    void (*onDestroy)(ANativeActivity* activity);
    void (*onWindowFocusChanged)(ANativeActivity* activity, bd_i32 hasFocus);
    void (*onNativeWindowCreated)(ANativeActivity* activity, ANativeWindow* window);
    void (*onNativeWindowResized)(ANativeActivity* activity, ANativeWindow* window);
    void (*onNativeWindowRedrawNeeded)(ANativeActivity* activity, ANativeWindow* window);
    void (*onNativeWindowDestroyed)(ANativeActivity* activity, ANativeWindow* window);
    void (*onInputQueueCreated)(ANativeActivity* activity, AInputQueue* queue);
    void (*onInputQueueDestroyed)(ANativeActivity* activity, AInputQueue* queue);
    void (*onContentRectChanged)(ANativeActivity* activity, const ARect* rect);
    void (*onConfigurationChanged)(ANativeActivity* activity);
    void (*onLowMemory)(ANativeActivity* activity);
} ANativeActivityCallbacks;

struct ANativeActivity {
    ANativeActivityCallbacks* callbacks;
    BdJavaVM* vm;
    BdJNIEnv* env;
    bd_jobject clazz;
    const char* internalDataPath;
    const char* externalDataPath;
    bd_i32 sdkVersion;
    void* instance;
    AAssetManager* assetManager;
    const char* obbPath;
};

extern void ANativeActivity_setWindowFlags(ANativeActivity* activity, bd_u32 addFlags, bd_u32 removeFlags);
extern void ANativeWindow_acquire(ANativeWindow* window);
extern void ANativeWindow_release(ANativeWindow* window);
extern bd_i32 ANativeWindow_getWidth(ANativeWindow* window);
extern bd_i32 ANativeWindow_getHeight(ANativeWindow* window);
extern bd_i32 ANativeWindow_setBuffersGeometry(ANativeWindow* window, bd_i32 width, bd_i32 height, bd_i32 format);
extern bd_i32 ANativeWindow_lock(ANativeWindow* window, ANativeWindow_Buffer* outBuffer, ARect* dirtyBounds);
extern bd_i32 ANativeWindow_unlockAndPost(ANativeWindow* window);
extern bd_i32 pthread_create(bd_pthread_t* thread, const void* attributes, void* (*start)(void*), void* argument);
extern bd_i32 pthread_join(bd_pthread_t thread, void** result);
extern bd_i32 usleep(bd_u32 microseconds);

enum {
    BD_WINDOW_FORMAT_RGBA_8888 = 1,
    BD_WINDOW_FORMAT_RGBX_8888 = 2,
    BD_WINDOW_FORMAT_RGB_565 = 4,
    BD_WINDOW_FLAG_KEEP_SCREEN_ON = 0x00000080u,
    BD_WINDOW_FLAG_FULLSCREEN = 0x00000400u
};

typedef struct BdNativeState {
    ANativeActivity* activity;
    ANativeWindow* window;
    bd_pthread_t thread;
    volatile bd_i32 running;
    volatile bd_i32 active;
    volatile bd_i32 threadStarted;
    bd_i32 targetWidth;
    bd_i32 targetHeight;
    BdFrameState frame;
} BdNativeState;

static BdNativeState g_state;

static bd_i32 bd_clamp_i32(bd_i32 v, bd_i32 lo, bd_i32 hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

static void bd_configure_window(BdNativeState* state, ANativeWindow* window) {
    bd_i32 physicalWidth = ANativeWindow_getWidth(window);
    bd_i32 physicalHeight = ANativeWindow_getHeight(window);
    if (physicalWidth <= 0) physicalWidth = 1920;
    if (physicalHeight <= 0) physicalHeight = 1080;

    if (physicalWidth >= physicalHeight) {
        state->targetWidth = 480;
        state->targetHeight = (480 * physicalHeight + physicalWidth / 2) / physicalWidth;
        state->targetHeight = bd_clamp_i32((state->targetHeight + 7) & ~7, 160, 320);
    } else {
        state->targetHeight = 480;
        state->targetWidth = (480 * physicalWidth + physicalHeight / 2) / physicalHeight;
        state->targetWidth = bd_clamp_i32((state->targetWidth + 7) & ~7, 160, 320);
    }
    ANativeWindow_setBuffersGeometry(window, state->targetWidth, state->targetHeight, BD_WINDOW_FORMAT_RGB_565);
}

static bd_u32 bd_expand565(bd_u16 value) {
    const bd_u32 r5 = (value >> 11) & 31u;
    const bd_u32 g6 = (value >> 5) & 63u;
    const bd_u32 b5 = value & 31u;
    const bd_u32 r8 = (r5 << 3) | (r5 >> 2);
    const bd_u32 g8 = (g6 << 2) | (g6 >> 4);
    const bd_u32 b8 = (b5 << 3) | (b5 >> 2);
    return 0xff000000u | (b8 << 16) | (g8 << 8) | r8;
}

static void bd_draw_locked(BdNativeState* state, ANativeWindow_Buffer* buffer) {
    state->frame.mode = (bd_u8)((state->frame.tick / 450u) & 3u);
    state->frame.palette = state->frame.mode;
    state->frame.levels = 4u;
    state->frame.flags = 1u;

    if (buffer->format == BD_WINDOW_FORMAT_RGB_565) {
        bd_render_rgb565((bd_u16*)buffer->bits, buffer->stride, buffer->width, buffer->height, &state->frame);
    } else if (buffer->format == BD_WINDOW_FORMAT_RGBA_8888 || buffer->format == BD_WINDOW_FORMAT_RGBX_8888) {
        bd_u32* pixels = (bd_u32*)buffer->bits;
        for (bd_i32 y = 0; y < buffer->height; ++y) {
            bd_u32* row = pixels + y * buffer->stride;
            for (bd_i32 x = 0; x < buffer->width; ++x) {
                row[x] = bd_expand565(bd_pixel_rgb565(x, y, buffer->width, buffer->height, &state->frame));
            }
        }
    }
    ++state->frame.tick;
}

static void* bd_render_thread(void* argument) {
    BdNativeState* state = (BdNativeState*)argument;
    while (state->running) {
        if (!state->active || !state->window) {
            usleep(50000u);
            continue;
        }
        ANativeWindow_Buffer buffer;
        if (ANativeWindow_lock(state->window, &buffer, (ARect*)0) == 0) {
            bd_draw_locked(state, &buffer);
            ANativeWindow_unlockAndPost(state->window);
        }
        usleep(33333u);
    }
    return (void*)0;
}

static void bd_stop_thread(BdNativeState* state) {
    if (!state->threadStarted) return;
    state->running = 0;
    pthread_join(state->thread, (void**)0);
    state->threadStarted = 0;
}

static void bd_start_thread(BdNativeState* state) {
    if (state->threadStarted || !state->window) return;
    state->running = 1;
    if (pthread_create(&state->thread, (const void*)0, bd_render_thread, state) == 0) state->threadStarted = 1;
    else state->running = 0;
}

static void bd_on_resume(ANativeActivity* activity) {
    BdNativeState* state = (BdNativeState*)activity->instance;
    if (state) state->active = 1;
}

static void bd_on_pause(ANativeActivity* activity) {
    BdNativeState* state = (BdNativeState*)activity->instance;
    if (state) state->active = 0;
}

static void bd_on_focus(ANativeActivity* activity, bd_i32 hasFocus) {
    BdNativeState* state = (BdNativeState*)activity->instance;
    if (state) state->active = hasFocus ? 1 : 0;
}

static void bd_on_window_created(ANativeActivity* activity, ANativeWindow* window) {
    BdNativeState* state = (BdNativeState*)activity->instance;
    if (!state || !window) return;
    bd_stop_thread(state);
    if (state->window) ANativeWindow_release(state->window);
    state->window = window;
    ANativeWindow_acquire(window);
    bd_configure_window(state, window);
    state->active = 1;
    bd_start_thread(state);
}

static void bd_on_window_resized(ANativeActivity* activity, ANativeWindow* window) {
    BdNativeState* state = (BdNativeState*)activity->instance;
    if (state && window) bd_configure_window(state, window);
}

static void bd_on_window_redraw(ANativeActivity* activity, ANativeWindow* window) {
    BdNativeState* state = (BdNativeState*)activity->instance;
    if (state && window && !state->threadStarted) bd_start_thread(state);
}

static void bd_on_window_destroyed(ANativeActivity* activity, ANativeWindow* window) {
    BdNativeState* state = (BdNativeState*)activity->instance;
    if (!state) return;
    state->active = 0;
    bd_stop_thread(state);
    if (state->window) {
        ANativeWindow_release(state->window);
        state->window = (ANativeWindow*)0;
    }
    (void)window;
}

static void bd_on_destroy(ANativeActivity* activity) {
    BdNativeState* state = (BdNativeState*)activity->instance;
    if (!state) return;
    state->active = 0;
    bd_stop_thread(state);
    if (state->window) {
        ANativeWindow_release(state->window);
        state->window = (ANativeWindow*)0;
    }
    activity->instance = (void*)0;
}

__attribute__((visibility("default")))
void ANativeActivity_onCreate(ANativeActivity* activity, void* savedState, bd_size_t savedStateSize) {
    (void)savedState;
    (void)savedStateSize;
    g_state.activity = activity;
    g_state.window = (ANativeWindow*)0;
    g_state.running = 0;
    g_state.active = 1;
    g_state.threadStarted = 0;
    g_state.targetWidth = 480;
    g_state.targetHeight = 216;
    g_state.frame.seed = 0x39A4B47Eu;
    g_state.frame.tick = 0u;
    g_state.frame.mode = 0u;
    g_state.frame.palette = 0u;
    g_state.frame.levels = 4u;
    g_state.frame.flags = 1u;
    activity->instance = &g_state;

    activity->callbacks->onResume = bd_on_resume;
    activity->callbacks->onPause = bd_on_pause;
    activity->callbacks->onDestroy = bd_on_destroy;
    activity->callbacks->onWindowFocusChanged = bd_on_focus;
    activity->callbacks->onNativeWindowCreated = bd_on_window_created;
    activity->callbacks->onNativeWindowResized = bd_on_window_resized;
    activity->callbacks->onNativeWindowRedrawNeeded = bd_on_window_redraw;
    activity->callbacks->onNativeWindowDestroyed = bd_on_window_destroyed;

    ANativeActivity_setWindowFlags(activity,
        BD_WINDOW_FLAG_KEEP_SCREEN_ON | BD_WINDOW_FLAG_FULLSCREEN,
        0u);
}
