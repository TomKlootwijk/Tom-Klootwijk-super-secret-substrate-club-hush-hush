#pragma once
#include "scene_pack.hpp"
#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <android/asset_manager.h>
#include <android/native_window.h>
#include <string>
#include <vector>

namespace kc {

class RendererGles3 {
public:
    RendererGles3() = default;
    ~RendererGles3();
    bool initialize(ANativeWindow* window,AAssetManager* assets,const ScenePack& scene);
    void shutdown();
    bool ready() const { return display_!=EGL_NO_DISPLAY && surface_!=EGL_NO_SURFACE; }
    void render(const ScenePack& scene,const std::vector<NodeData>& nodes,Vec3 cameraTarget,float yaw,float pitch,float distance,float renderScale,std::uint32_t maxNodes,float timeSeconds);
    std::string gpuRenderer() const { return gpuRenderer_; }
    int width() const { return width_; }
    int height() const { return height_; }
private:
    struct GpuMesh { GLuint vbo=0,ibo=0; GLsizei indexCount=0; };
    bool createProgram(AAssetManager* assets);
    std::string readAsset(AAssetManager* assets,const char* name);
    GLuint compile(GLenum type,const std::string& source);
    void rebuildFramebuffer(int width,int height,float scale);
    void destroyFramebuffer();
    EGLDisplay display_=EGL_NO_DISPLAY;
    EGLSurface surface_=EGL_NO_SURFACE;
    EGLContext context_=EGL_NO_CONTEXT;
    EGLConfig config_=nullptr;
    GLuint program_=0;
    GLint uViewProjection_=-1,uModel_=-1,uBaseColor_=-1,uEmissive_=-1;
    GLint uLightDirection_=-1,uLightColor_=-1,uLightIntensity_=-1,uAmbient_=-1,uPulse_=-1;
    std::vector<GpuMesh> meshes_;
    GLuint framebuffer_=0,colorTexture_=0,depthBuffer_=0;
    int width_=0,height_=0,internalWidth_=0,internalHeight_=0;
    float currentScale_=0;
    std::string gpuRenderer_;
};

} // namespace kc
