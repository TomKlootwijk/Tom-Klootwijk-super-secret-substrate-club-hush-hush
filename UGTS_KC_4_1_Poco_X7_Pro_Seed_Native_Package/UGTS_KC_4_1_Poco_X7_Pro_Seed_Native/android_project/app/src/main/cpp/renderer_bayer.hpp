#pragma once
#include "core/pipeline.hpp"
#include "core/types.hpp"
#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <android/asset_manager.h>
#include <android/native_window.h>
#include <array>
#include <cstdint>
#include <string>
#include <vector>
namespace ugts41::android {
enum class ViewMode:int{Camera=0,MapDemo=1,Ledger=2};
struct RenderSnapshot{ViewMode mode=ViewMode::Camera;const std::vector<std::uint8_t>*luma=nullptr;std::uint16_t luma_width=0,luma_height=0;const std::vector<FeaturePoint>*features=nullptr;const DemoWorld*demo=nullptr;const SessionStats*stats=nullptr;std::array<std::uint8_t,32>state_hash{};std::uint64_t seed=0;int thermal=0;bool recording=false,camera_active=false;std::string profile;};
class RendererBayer{
public:bool initialize(ANativeWindow*,AAssetManager*);void shutdown();void render(const RenderSnapshot&,float time_seconds);bool ready()const{return display_!=EGL_NO_DISPLAY&&surface_!=EGL_NO_SURFACE&&program_!=0;}std::string gpu()const{return gpu_;}
private:std::string asset_text(AAssetManager*,const char*);GLuint compile(GLenum,const std::string&);void make_canvas(const RenderSnapshot&);void pixel(int,int,std::uint8_t);void line(int,int,int,int,std::uint8_t);void text(int,int,const std::string&,std::uint8_t);void glyph(int,int,char,std::uint8_t);
EGLDisplay display_=EGL_NO_DISPLAY;EGLSurface surface_=EGL_NO_SURFACE;EGLContext context_=EGL_NO_CONTEXT;EGLConfig config_=nullptr;GLuint program_=0,texture_=0;GLint u_luma_=-1,u_mode_=-1,u_pulse_=-1;int window_width_=0,window_height_=0;std::uint16_t canvas_width_=160,canvas_height_=90;std::vector<std::uint8_t>canvas_;std::string gpu_="unknown";
};
}
