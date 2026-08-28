#include "renderer_gles3.hpp"
#include <android/log.h>
#include <algorithm>
#include <cmath>

#define KC_LOGE(...) __android_log_print(ANDROID_LOG_ERROR,"UGTS-KC391",__VA_ARGS__)

namespace kc {

RendererGles3::~RendererGles3() { shutdown(); }

std::string RendererGles3::readAsset(AAssetManager* manager,const char* name) {
    AAsset* asset=AAssetManager_open(manager,name,AASSET_MODE_BUFFER);
    if (!asset) return {};
    const auto length=AAsset_getLength(asset);
    std::string result(static_cast<std::size_t>(length),'\0');
    if (length>0) AAsset_read(asset,result.data(),length);
    AAsset_close(asset);
    return result;
}

GLuint RendererGles3::compile(GLenum type,const std::string& source) {
    const GLuint shader=glCreateShader(type);
    const char* text=source.c_str();
    glShaderSource(shader,1,&text,nullptr);
    glCompileShader(shader);
    GLint ok=GL_FALSE;
    glGetShaderiv(shader,GL_COMPILE_STATUS,&ok);
    if (!ok) {
        char log[2048]{};
        glGetShaderInfoLog(shader,sizeof(log),nullptr,log);
        KC_LOGE("shader compile failed: %s",log);
        glDeleteShader(shader);
        return 0;
    }
    return shader;
}

bool RendererGles3::createProgram(AAssetManager* assets) {
    const auto vs=compile(GL_VERTEX_SHADER,readAsset(assets,"shaders/scene.vert"));
    const auto fs=compile(GL_FRAGMENT_SHADER,readAsset(assets,"shaders/scene.frag"));
    if (!vs || !fs) return false;
    program_=glCreateProgram();
    glAttachShader(program_,vs); glAttachShader(program_,fs); glLinkProgram(program_);
    glDeleteShader(vs); glDeleteShader(fs);
    GLint ok=GL_FALSE; glGetProgramiv(program_,GL_LINK_STATUS,&ok);
    if (!ok) {
        char log[2048]{};
        glGetProgramInfoLog(program_,sizeof(log),nullptr,log);
        KC_LOGE("program link failed: %s",log);
        return false;
    }
    uViewProjection_=glGetUniformLocation(program_,"uViewProjection");
    uModel_=glGetUniformLocation(program_,"uModel");
    uBaseColor_=glGetUniformLocation(program_,"uBaseColor");
    uEmissive_=glGetUniformLocation(program_,"uEmissive");
    uLightDirection_=glGetUniformLocation(program_,"uLightDirection");
    uLightColor_=glGetUniformLocation(program_,"uLightColor");
    uLightIntensity_=glGetUniformLocation(program_,"uLightIntensity");
    uAmbient_=glGetUniformLocation(program_,"uAmbient");
    uPulse_=glGetUniformLocation(program_,"uPulse");
    return true;
}

bool RendererGles3::initialize(ANativeWindow* window,AAssetManager* assets,const ScenePack& scene) {
    shutdown();
    display_=eglGetDisplay(EGL_DEFAULT_DISPLAY);
    if (display_==EGL_NO_DISPLAY || !eglInitialize(display_,nullptr,nullptr)) return false;
    const EGLint configAttributes[]={
        EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT,
        EGL_SURFACE_TYPE,EGL_WINDOW_BIT,
        EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,
        EGL_DEPTH_SIZE,24,EGL_NONE
    };
    EGLint count=0;
    if (!eglChooseConfig(display_,configAttributes,&config_,1,&count) || count<1) return false;
    EGLint format=0; eglGetConfigAttrib(display_,config_,EGL_NATIVE_VISUAL_ID,&format);
    ANativeWindow_setBuffersGeometry(window,0,0,format);
    const EGLint contextAttributes[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE};
    context_=eglCreateContext(display_,config_,EGL_NO_CONTEXT,contextAttributes);
    surface_=eglCreateWindowSurface(display_,config_,window,nullptr);
    if (context_==EGL_NO_CONTEXT || surface_==EGL_NO_SURFACE || !eglMakeCurrent(display_,surface_,surface_,context_)) return false;
    eglSwapInterval(display_,1);
    eglQuerySurface(display_,surface_,EGL_WIDTH,&width_);
    eglQuerySurface(display_,surface_,EGL_HEIGHT,&height_);
    const char* renderer=reinterpret_cast<const char*>(glGetString(GL_RENDERER));
    gpuRenderer_=renderer?renderer:"unknown";
    if (!createProgram(assets)) return false;
    meshes_.resize(scene.meshes.size());
    for (std::size_t i=0;i<scene.meshes.size();++i) {
        const auto& mesh=scene.meshes[i];
        auto& gpu=meshes_[i];
        glGenBuffers(1,&gpu.vbo); glBindBuffer(GL_ARRAY_BUFFER,gpu.vbo);
        glBufferData(GL_ARRAY_BUFFER,static_cast<GLsizeiptr>(mesh.vertices.size()*sizeof(Vertex)),mesh.vertices.data(),GL_STATIC_DRAW);
        glGenBuffers(1,&gpu.ibo); glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,gpu.ibo);
        glBufferData(GL_ELEMENT_ARRAY_BUFFER,static_cast<GLsizeiptr>(mesh.indices.size()*sizeof(std::uint32_t)),mesh.indices.data(),GL_STATIC_DRAW);
        gpu.indexCount=static_cast<GLsizei>(mesh.indices.size());
    }
    glEnable(GL_DEPTH_TEST); glDepthFunc(GL_LEQUAL);
    glEnable(GL_CULL_FACE); glCullFace(GL_BACK);
    return true;
}

void RendererGles3::destroyFramebuffer() {
    if (depthBuffer_) glDeleteRenderbuffers(1,&depthBuffer_);
    if (colorTexture_) glDeleteTextures(1,&colorTexture_);
    if (framebuffer_) glDeleteFramebuffers(1,&framebuffer_);
    framebuffer_=colorTexture_=depthBuffer_=0;
    internalWidth_=internalHeight_=0;
}

void RendererGles3::rebuildFramebuffer(int width,int height,float scale) {
    const int iw=std::max(1,static_cast<int>(std::round(width*scale)));
    const int ih=std::max(1,static_cast<int>(std::round(height*scale)));
    if (iw==internalWidth_ && ih==internalHeight_) return;
    destroyFramebuffer();
    internalWidth_=iw; internalHeight_=ih; currentScale_=scale;
    glGenFramebuffers(1,&framebuffer_); glBindFramebuffer(GL_FRAMEBUFFER,framebuffer_);
    glGenTextures(1,&colorTexture_); glBindTexture(GL_TEXTURE_2D,colorTexture_);
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,iw,ih,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,colorTexture_,0);
    glGenRenderbuffers(1,&depthBuffer_); glBindRenderbuffer(GL_RENDERBUFFER,depthBuffer_);
    glRenderbufferStorage(GL_RENDERBUFFER,GL_DEPTH_COMPONENT24,iw,ih);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER,GL_DEPTH_ATTACHMENT,GL_RENDERBUFFER,depthBuffer_);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE) KC_LOGE("dynamic-resolution framebuffer incomplete");
}

void RendererGles3::render(const ScenePack& scene,const std::vector<NodeData>& nodes,Vec3 target,float yaw,float pitch,float distance,float scale,std::uint32_t maxNodes,float time) {
    if (!ready()) return;
    eglQuerySurface(display_,surface_,EGL_WIDTH,&width_);
    eglQuerySurface(display_,surface_,EGL_HEIGHT,&height_);
    rebuildFramebuffer(width_,height_,clamp(scale,0.45f,1.0f));
    glBindFramebuffer(GL_FRAMEBUFFER,framebuffer_);
    glViewport(0,0,internalWidth_,internalHeight_);
    glClearColor(scene.background[0],scene.background[1],scene.background[2],scene.background[3]);
    glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
    glUseProgram(program_);
    const Vec3 eye={
        target.x+distance*std::cos(pitch)*std::sin(yaw),
        target.y+distance*std::sin(pitch),
        target.z+distance*std::cos(pitch)*std::cos(yaw)
    };
    const auto projection=perspective(scene.cameraFovDegrees*kPi/180.0f,static_cast<float>(internalWidth_)/std::max(1,internalHeight_),scene.cameraNear,scene.cameraFar);
    const auto view=lookAt(eye,target,scene.cameraUp);
    const auto vp=multiply(projection,view);
    glUniformMatrix4fv(uViewProjection_,1,GL_FALSE,vp.data());
    glUniform3f(uLightDirection_,scene.lightDirection.x,scene.lightDirection.y,scene.lightDirection.z);
    glUniform3f(uLightColor_,scene.lightColor.x,scene.lightColor.y,scene.lightColor.z);
    glUniform1f(uLightIntensity_,scene.lightIntensity);
    glUniform1f(uAmbient_,scene.ambient);
    glUniform1f(uPulse_,std::sin(time*2.0f));

    std::uint32_t drawn=0;
    for (const auto& node:nodes) {
        if (!node.alive || drawn>=maxNodes || node.meshIndex>=meshes_.size() || node.materialIndex>=scene.materials.size()) continue;
        const auto& gpu=meshes_[node.meshIndex];
        const auto& material=scene.materials[node.materialIndex];
        const auto model=trs(node.translation,node.rotation,node.scale);
        glUniformMatrix4fv(uModel_,1,GL_FALSE,model.data());
        glUniform4fv(uBaseColor_,1,material.baseColor.data());
        glUniform3f(uEmissive_,material.emissive.x,material.emissive.y,material.emissive.z);
        if (material.doubleSided) glDisable(GL_CULL_FACE); else glEnable(GL_CULL_FACE);
        glBindBuffer(GL_ARRAY_BUFFER,gpu.vbo);
        glEnableVertexAttribArray(0); glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(Vertex),reinterpret_cast<void*>(offsetof(Vertex,position)));
        glEnableVertexAttribArray(1); glVertexAttribPointer(1,3,GL_FLOAT,GL_FALSE,sizeof(Vertex),reinterpret_cast<void*>(offsetof(Vertex,normal)));
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,gpu.ibo);
        glDrawElements(GL_TRIANGLES,gpu.indexCount,GL_UNSIGNED_INT,nullptr);
        ++drawn;
    }
    glBindFramebuffer(GL_READ_FRAMEBUFFER,framebuffer_);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER,0);
    glBlitFramebuffer(0,0,internalWidth_,internalHeight_,0,0,width_,height_,GL_COLOR_BUFFER_BIT,GL_LINEAR);
    eglSwapBuffers(display_,surface_);
}

void RendererGles3::shutdown() {
    if (display_!=EGL_NO_DISPLAY) {
        eglMakeCurrent(display_,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);
        for (auto& mesh:meshes_) {
            if (mesh.vbo) glDeleteBuffers(1,&mesh.vbo);
            if (mesh.ibo) glDeleteBuffers(1,&mesh.ibo);
        }
        meshes_.clear();
        destroyFramebuffer();
        if (program_) glDeleteProgram(program_);
        if (context_!=EGL_NO_CONTEXT) eglDestroyContext(display_,context_);
        if (surface_!=EGL_NO_SURFACE) eglDestroySurface(display_,surface_);
        eglTerminate(display_);
    }
    display_=EGL_NO_DISPLAY; surface_=EGL_NO_SURFACE; context_=EGL_NO_CONTEXT; program_=0;
}

} // namespace kc
