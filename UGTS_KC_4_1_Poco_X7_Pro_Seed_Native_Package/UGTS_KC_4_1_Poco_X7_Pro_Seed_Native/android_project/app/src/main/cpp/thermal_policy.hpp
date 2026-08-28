#pragma once
#include "device_profile.hpp"
#include <android_native_app_glue.h>
namespace ugts41::android {struct ThermalTuning{int status=0;std::uint16_t process_fps=30,feature_budget=96;bool thumbnails=false,pause_capture=false;};int query_thermal_status(android_app*);ThermalTuning thermal_tuning(const RuntimeProfile&,int status);}
