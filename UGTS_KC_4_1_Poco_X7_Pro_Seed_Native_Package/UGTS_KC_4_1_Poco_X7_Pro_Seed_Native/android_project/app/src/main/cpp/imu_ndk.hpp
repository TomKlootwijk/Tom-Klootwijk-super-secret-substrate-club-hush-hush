#pragma once
#include "core/types.hpp"
#include <android/looper.h>
#include <android/sensor.h>
#include <mutex>
#include <string>
namespace ugts41::android {class ImuNdk{public:bool start(ALooper*,const std::string&package_name);void stop();ImuSample latest()const;bool active()const{return queue_!=nullptr;}private:static int callback(int,int,void*);int drain();ASensorManager*manager_=nullptr;ASensorEventQueue*queue_=nullptr;const ASensor*accel_=nullptr,*gyro_=nullptr,*rotation_=nullptr;mutable std::mutex mutex_;ImuSample latest_{};};}
