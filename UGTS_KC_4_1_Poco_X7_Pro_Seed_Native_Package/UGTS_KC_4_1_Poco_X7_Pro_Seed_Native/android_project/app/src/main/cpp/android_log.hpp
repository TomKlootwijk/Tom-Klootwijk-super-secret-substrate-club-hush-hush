#pragma once
#include <android/log.h>
#define UGTS_LOGI(...) __android_log_print(ANDROID_LOG_INFO,"UGTS-KC-4.1",__VA_ARGS__)
#define UGTS_LOGW(...) __android_log_print(ANDROID_LOG_WARN,"UGTS-KC-4.1",__VA_ARGS__)
#define UGTS_LOGE(...) __android_log_print(ANDROID_LOG_ERROR,"UGTS-KC-4.1",__VA_ARGS__)
