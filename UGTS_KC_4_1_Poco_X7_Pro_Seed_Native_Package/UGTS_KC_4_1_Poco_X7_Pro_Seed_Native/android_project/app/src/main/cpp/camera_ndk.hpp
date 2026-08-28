#pragma once
#include <camera/NdkCameraDevice.h>
#include <camera/NdkCameraManager.h>
#include <media/NdkImageReader.h>
#include <android/native_window.h>
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>
namespace ugts41::android {
struct CameraFrame{std::uint64_t sequence=0,timestamp_ns=0;std::uint16_t width=0,height=0;std::vector<std::uint8_t>luma;};
struct CameraDescriptor{std::string camera_id="none",facing="unknown",calibration="unverified";std::uint16_t width=0,height=0,fps=0;};
class CameraNdk{
public:CameraNdk()=default;~CameraNdk(){stop();}bool start(std::uint16_t requested_width,std::uint16_t requested_height,std::uint16_t fps);void stop();bool consume(CameraFrame&out);bool active()const{return session_!=nullptr;}const CameraDescriptor&descriptor()const{return descriptor_;}
private:static void on_image(void*,AImageReader*);static void on_disconnected(void*,ACameraDevice*);static void on_error(void*,ACameraDevice*,int);static void on_closed(void*,ACameraCaptureSession*);static void on_ready(void*,ACameraCaptureSession*);static void on_active(void*,ACameraCaptureSession*);void acquire_image(AImageReader*);bool choose_camera(std::uint16_t,std::uint16_t,std::uint16_t);
ACameraManager*manager_=nullptr;ACameraDevice*device_=nullptr;ACameraCaptureSession*session_=nullptr;AImageReader*reader_=nullptr;ANativeWindow*reader_window_=nullptr;ACaptureSessionOutputContainer*outputs_=nullptr;ACaptureSessionOutput*output_=nullptr;ACameraOutputTarget*target_=nullptr;ACaptureRequest*request_=nullptr;std::string camera_id_;CameraDescriptor descriptor_{};mutable std::mutex mutex_;CameraFrame latest_{};std::uint64_t consumed_sequence_=0,next_sequence_=0;
};
}
