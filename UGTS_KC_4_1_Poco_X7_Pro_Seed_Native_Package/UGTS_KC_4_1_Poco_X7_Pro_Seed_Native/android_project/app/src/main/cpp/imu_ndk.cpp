#include "imu_ndk.hpp"
#include "android_log.hpp"
#include <algorithm>
#include <cmath>
namespace ugts41::android {
bool ImuNdk::start(ALooper*l,const std::string&pkg){constexpr int kUserLooperId=3;stop();manager_=ASensorManager_getInstanceForPackage(pkg.c_str());if(!manager_)manager_=ASensorManager_getInstance();if(!manager_||!l)return false;queue_=ASensorManager_createEventQueue(manager_,l,kUserLooperId,callback,this);if(!queue_)return false;accel_=ASensorManager_getDefaultSensor(manager_,ASENSOR_TYPE_ACCELEROMETER);gyro_=ASensorManager_getDefaultSensor(manager_,ASENSOR_TYPE_GYROSCOPE);rotation_=ASensorManager_getDefaultSensor(manager_,ASENSOR_TYPE_ROTATION_VECTOR);for(auto*s:{accel_,gyro_,rotation_})if(s){ASensorEventQueue_enableSensor(queue_,s);ASensorEventQueue_setEventRate(queue_,s,std::max(5000,ASensor_getMinDelay(s)));}UGTS_LOGI("IMU active accel=%d gyro=%d rotation=%d",accel_!=nullptr,gyro_!=nullptr,rotation_!=nullptr);return true;}
void ImuNdk::stop(){if(queue_&&manager_){for(auto*s:{accel_,gyro_,rotation_})if(s)ASensorEventQueue_disableSensor(queue_,s);ASensorManager_destroyEventQueue(manager_,queue_);}queue_=nullptr;manager_=nullptr;accel_=nullptr;gyro_=nullptr;rotation_=nullptr;}
int ImuNdk::callback(int,int,void*d){return static_cast<ImuNdk*>(d)->drain();}
int ImuNdk::drain(){if(!queue_)return 1;ASensorEvent ev[32];ssize_t n;while((n=ASensorEventQueue_getEvents(queue_,ev,32))>0){std::scoped_lock lock(mutex_);for(ssize_t i=0;i<n;i++){auto&e=ev[i];latest_.timestamp_ns=std::max<std::uint64_t>(latest_.timestamp_ns,e.timestamp);if(e.type==ASENSOR_TYPE_ACCELEROMETER)latest_.acceleration={e.acceleration.x,e.acceleration.y,e.acceleration.z};else if(e.type==ASENSOR_TYPE_GYROSCOPE)latest_.angular_velocity={e.vector.x,e.vector.y,e.vector.z};else if(e.type==ASENSOR_TYPE_ROTATION_VECTOR){float x=e.data[0],y=e.data[1],z=e.data[2],w=e.data[3];if(std::abs(w)<1e-6f)w=std::sqrt(std::max(0.0f,1-x*x-y*y-z*z));float q=std::sqrt(x*x+y*y+z*z+w*w);if(q>1e-6f)latest_.orientation={x/q,y/q,z/q,w/q};}}}return 1;}
ImuSample ImuNdk::latest()const{std::scoped_lock lock(mutex_);return latest_;}
}
