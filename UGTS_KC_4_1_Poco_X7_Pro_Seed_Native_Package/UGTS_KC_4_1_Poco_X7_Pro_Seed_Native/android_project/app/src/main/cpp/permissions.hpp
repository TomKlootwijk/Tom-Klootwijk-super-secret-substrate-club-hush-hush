#pragma once
#include <android_native_app_glue.h>
namespace ugts41::android {bool camera_permission_granted(android_app*);void request_camera_permission(android_app*,int request_code=41);}
