#include "renderer_gles3.hpp"
#include <android/log.h>
#include <algorithm>
#include <cmath>

#define KC_LOGE(...) __android_log_print(ANDROID_LOG_ERROR,"UGTS-KC392",__VA_ARGS__)

namespace kc {

static_assert(sizeof(Mat4)==16u*sizeof(float));

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
    const auto pvs=compile(GL_VERTEX_SHADER,readAsset(assets,"shaders/grove_post.vert"));
    const auto pfs=compile(GL_FRAGMENT_SHADER,readAsset(assets,"shaders/grove_post.frag"));
    const GLuint shaders[]={vs,fs,pvs,pfs};
    const auto deleteShaders=[&shaders]() {
        for (const GLuint shader:shaders) {
            if (shader) glDeleteShader(shader);
        }
    };
    if (!vs || !fs || !pvs || !pfs) {
        deleteShaders();
        return false;
    }
    program_=glCreateProgram();
    glAttachShader(program_,vs); glAttachShader(program_,fs); glLinkProgram(program_);
    GLint ok=GL_FALSE; glGetProgramiv(program_,GL_LINK_STATUS,&ok);
    if (!ok) {
        char log[2048]{};
        glGetProgramInfoLog(program_,sizeof(log),nullptr,log);
        KC_LOGE("program link failed: %s",log);
        deleteShaders();
        return false;
    }
    uViewProjection_=glGetUniformLocation(program_,"uViewProjection");
    uModel_=glGetUniformLocation(program_,"uModel");
    uInstanced_=glGetUniformLocation(program_,"uInstanced");
    uBaseColor_=glGetUniformLocation(program_,"uBaseColor");
    uMetallic_=glGetUniformLocation(program_,"uMetallic");
    uRoughness_=glGetUniformLocation(program_,"uRoughness");
    uEmissive_=glGetUniformLocation(program_,"uEmissive");
    uCameraPosition_=glGetUniformLocation(program_,"uCameraPosition");
    uLightDirection_=glGetUniformLocation(program_,"uLightDirection");
    uLightColor_=glGetUniformLocation(program_,"uLightColor");
    uLightIntensity_=glGetUniformLocation(program_,"uLightIntensity");
    uAmbient_=glGetUniformLocation(program_,"uAmbient");
    uPulse_=glGetUniformLocation(program_,"uPulse");
    postProgram_=glCreateProgram();
    glAttachShader(postProgram_,pvs); glAttachShader(postProgram_,pfs); glLinkProgram(postProgram_);
    GLint postOk=GL_FALSE; glGetProgramiv(postProgram_,GL_LINK_STATUS,&postOk);
    deleteShaders();
    if (!postOk) {
        char log[2048]{};
        glGetProgramInfoLog(postProgram_,sizeof(log),nullptr,log);
        KC_LOGE("post program link failed: %s",log);
        return false;
    }
    pColor_=glGetUniformLocation(postProgram_,"uColor");
    pTime_=glGetUniformLocation(postProgram_,"uTime");
    pBloom_=glGetUniformLocation(postProgram_,"uBloom");
    pFlash_=glGetUniformLocation(postProgram_,"uFlash");
    pAberration_=glGetUniformLocation(postProgram_,"uAberration");
    pVignette_=glGetUniformLocation(postProgram_,"uVignette");
    pSaturation_=glGetUniformLocation(postProgram_,"uSaturation");
    pContrast_=glGetUniformLocation(postProgram_,"uContrast");
    pShock_=glGetUniformLocation(postProgram_,"uShock");
    pShockCenter_=glGetUniformLocation(postProgram_,"uShockCenter");
    pJuicePulse_=glGetUniformLocation(postProgram_,"uJuicePulse");
    return true;
}

bool RendererGles3::initialize(
    ANativeWindow* window,
    AAssetManager* assets,
    const ScenePack& scene,
    const ScatterPopulations& scatterPopulations
) {
    shutdown();
    if (!window || !assets) return false;
    const auto rollback=[this]() {
        shutdown();
        return false;
    };
    display_=eglGetDisplay(EGL_DEFAULT_DISPLAY);
    if (display_==EGL_NO_DISPLAY || !eglInitialize(display_,nullptr,nullptr)) return rollback();
    const EGLint configAttributes[]={
        EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT,
        EGL_SURFACE_TYPE,EGL_WINDOW_BIT,
        EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,
        EGL_DEPTH_SIZE,24,EGL_NONE
    };
    EGLint count=0;
    if (!eglChooseConfig(display_,configAttributes,&config_,1,&count) || count<1) return rollback();
    EGLint format=0;
    if (!eglGetConfigAttrib(display_,config_,EGL_NATIVE_VISUAL_ID,&format) ||
        ANativeWindow_setBuffersGeometry(window,0,0,format)!=0) return rollback();
    const EGLint contextAttributes[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE};
    context_=eglCreateContext(display_,config_,EGL_NO_CONTEXT,contextAttributes);
    if (context_==EGL_NO_CONTEXT) return rollback();
    surface_=eglCreateWindowSurface(display_,config_,window,nullptr);
    if (surface_==EGL_NO_SURFACE || !eglMakeCurrent(display_,surface_,surface_,context_)) return rollback();
    eglSwapInterval(display_,1);
    if (!eglQuerySurface(display_,surface_,EGL_WIDTH,&width_) ||
        !eglQuerySurface(display_,surface_,EGL_HEIGHT,&height_)) return rollback();
    const char* renderer=reinterpret_cast<const char*>(glGetString(GL_RENDERER));
    gpuRenderer_=renderer?renderer:"unknown";
    if (!createProgram(assets)) return rollback();
    meshes_.resize(scene.meshes.size());
    for (std::size_t i=0;i<scene.meshes.size();++i) {
        const auto& mesh=scene.meshes[i];
        auto& gpu=meshes_[i];
        glGenBuffers(1,&gpu.vbo); glBindBuffer(GL_ARRAY_BUFFER,gpu.vbo);
        if (!gpu.vbo) {
            KC_LOGE("could not allocate mesh vertex buffer");
            return rollback();
        }
        glBufferData(GL_ARRAY_BUFFER,static_cast<GLsizeiptr>(mesh.vertices.size()*sizeof(Vertex)),mesh.vertices.data(),GL_STATIC_DRAW);
        glGenBuffers(1,&gpu.ibo); glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,gpu.ibo);
        if (!gpu.ibo) {
            KC_LOGE("could not allocate mesh index buffer");
            return rollback();
        }
        glBufferData(GL_ELEMENT_ARRAY_BUFFER,static_cast<GLsizeiptr>(mesh.indices.size()*sizeof(std::uint32_t)),mesh.indices.data(),GL_STATIC_DRAW);
        gpu.indexCount=static_cast<GLsizei>(mesh.indices.size());
    }
    scatterGroups_.reserve(scatterPopulations.groupCount());
    for (const auto& group:scatterPopulations.groups()) {
        if (group.prototypeNodeIndex>=scene.nodes.size() ||
            group.instances.size()+1u!=group.instanceCount) {
            KC_LOGE("invalid KCSP renderer group");
            return rollback();
        }
        std::vector<Mat4> matrices;
        matrices.reserve(group.instances.size());
        for (const auto& instance:group.instances) matrices.push_back(instance.model);
        GpuScatterGroup gpu;
        gpu.prototypeNodeIndex=group.prototypeNodeIndex;
        gpu.generatedCount=static_cast<GLsizei>(matrices.size());
        glGenBuffers(1,&gpu.matrixBuffer);
        if (!gpu.matrixBuffer) {
            KC_LOGE("could not allocate KCSP instance buffer");
            return rollback();
        }
        glBindBuffer(GL_ARRAY_BUFFER,gpu.matrixBuffer);
        glBufferData(
            GL_ARRAY_BUFFER,
            static_cast<GLsizeiptr>(matrices.size()*sizeof(Mat4)),
            matrices.data(),
            GL_STATIC_DRAW
        );
        scatterGroups_.push_back(gpu);
    }
    glBindBuffer(GL_ARRAY_BUFFER,0);
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

void RendererGles3::render(const ScenePack& scene,const std::vector<NodeData>& nodes,Vec3 target,float yaw,float pitch,float distance,float scale,std::uint32_t maxNodes,float time,const GroveJuiceFrame& juice,bool postProcessing) {
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
    glUniform3f(uCameraPosition_,eye.x,eye.y,eye.z);
    glUniform3f(uLightDirection_,scene.lightDirection.x,scene.lightDirection.y,scene.lightDirection.z);
    glUniform3f(uLightColor_,scene.lightColor.x,scene.lightColor.y,scene.lightColor.z);
    glUniform1f(uLightIntensity_,scene.lightIntensity);
    glUniform1f(uAmbient_,scene.ambient);
    glUniform1f(uPulse_,std::sin(time*2.0f));

    std::uint32_t drawn=0;
    glUniform1i(uInstanced_,GL_FALSE);
    for (const auto& node:nodes) {
        if (drawn>=maxNodes) break;
        if (!node.alive || !node.active || node.meshIndex>=meshes_.size() || node.materialIndex>=scene.materials.size()) continue;
        const auto& gpu=meshes_[node.meshIndex];
        const auto& material=scene.materials[node.materialIndex];
        const auto model=trs(node.translation,node.rotation,node.scale);
        glUniformMatrix4fv(uModel_,1,GL_FALSE,model.data());
        glUniform4fv(uBaseColor_,1,material.baseColor.data());
        glUniform1f(uMetallic_,material.metallic);
        glUniform1f(uRoughness_,material.roughness);
        glUniform3f(uEmissive_,material.emissive.x,material.emissive.y,material.emissive.z);
        if (material.doubleSided) glDisable(GL_CULL_FACE); else glEnable(GL_CULL_FACE);
        glBindBuffer(GL_ARRAY_BUFFER,gpu.vbo);
        glEnableVertexAttribArray(0); glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(Vertex),reinterpret_cast<void*>(offsetof(Vertex,position)));
        glEnableVertexAttribArray(1); glVertexAttribPointer(1,3,GL_FLOAT,GL_FALSE,sizeof(Vertex),reinterpret_cast<void*>(offsetof(Vertex,normal)));
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,gpu.ibo);
        glDrawElements(GL_TRIANGLES,gpu.indexCount,GL_UNSIGNED_INT,nullptr);
        ++drawn;
    }
    if (drawn<maxNodes && !scatterGroups_.empty()) {
        glUniform1i(uInstanced_,GL_TRUE);
        for (const auto& group:scatterGroups_) {
            if (drawn>=maxNodes) break;
            if (group.prototypeNodeIndex>=nodes.size() || group.generatedCount<=0) continue;
            const auto& prototype=nodes[group.prototypeNodeIndex];
            if (!prototype.alive || !prototype.active ||
                prototype.meshIndex>=meshes_.size() ||
                prototype.materialIndex>=scene.materials.size()) continue;
            const auto remaining=maxNodes-drawn;
            const auto visibleCopies=static_cast<GLsizei>(std::min<std::uint32_t>(
                static_cast<std::uint32_t>(group.generatedCount),remaining
            ));
            const auto& gpu=meshes_[prototype.meshIndex];
            const auto& material=scene.materials[prototype.materialIndex];
            glUniform4fv(uBaseColor_,1,material.baseColor.data());
            glUniform1f(uMetallic_,material.metallic);
            glUniform1f(uRoughness_,material.roughness);
            glUniform3f(uEmissive_,material.emissive.x,material.emissive.y,material.emissive.z);
            if (material.doubleSided) glDisable(GL_CULL_FACE); else glEnable(GL_CULL_FACE);
            glBindBuffer(GL_ARRAY_BUFFER,gpu.vbo);
            glEnableVertexAttribArray(0); glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(Vertex),reinterpret_cast<void*>(offsetof(Vertex,position)));
            glEnableVertexAttribArray(1); glVertexAttribPointer(1,3,GL_FLOAT,GL_FALSE,sizeof(Vertex),reinterpret_cast<void*>(offsetof(Vertex,normal)));
            glBindBuffer(GL_ARRAY_BUFFER,group.matrixBuffer);
            for (GLuint column=0;column<4;++column) {
                const GLuint location=2u+column;
                glEnableVertexAttribArray(location);
                glVertexAttribPointer(
                    location,4,GL_FLOAT,GL_FALSE,sizeof(Mat4),
                    reinterpret_cast<void*>(static_cast<std::uintptr_t>(column*4u*sizeof(float)))
                );
                glVertexAttribDivisor(location,1);
            }
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,gpu.ibo);
            glDrawElementsInstanced(
                GL_TRIANGLES,gpu.indexCount,GL_UNSIGNED_INT,nullptr,visibleCopies
            );
            drawn+=static_cast<std::uint32_t>(visibleCopies);
        }
        for (GLuint location=2;location<=5;++location) {
            glVertexAttribDivisor(location,0);
            glDisableVertexAttribArray(location);
        }
        glUniform1i(uInstanced_,GL_FALSE);
    }
    glBindFramebuffer(GL_FRAMEBUFFER,0);
    glViewport(0,0,width_,height_);
    if (postProcessing && postProgram_ && colorTexture_) {
        glDisable(GL_DEPTH_TEST);
        glDisable(GL_CULL_FACE);
        glUseProgram(postProgram_);
        glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D,colorTexture_);
        glUniform1i(pColor_,0);
        glUniform1f(pTime_,time);
        glUniform1f(pBloom_,juice.bloom);
        glUniform1f(pFlash_,juice.flash);
        glUniform1f(pAberration_,juice.aberration);
        glUniform1f(pVignette_,juice.vignette);
        glUniform1f(pSaturation_,juice.saturation);
        glUniform1f(pContrast_,juice.contrast);
        glUniform1f(pShock_,juice.shock);
        glUniform2f(pShockCenter_,juice.shockX,juice.shockY);
        glUniform1f(pJuicePulse_,juice.pulse);
        glDrawArrays(GL_TRIANGLES,0,3);
        glBindTexture(GL_TEXTURE_2D,0);
        glUseProgram(program_);
    } else {
        glBindFramebuffer(GL_READ_FRAMEBUFFER,framebuffer_);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER,0);
        glBlitFramebuffer(0,0,internalWidth_,internalHeight_,0,0,width_,height_,GL_COLOR_BUFFER_BIT,GL_LINEAR);
    }
    glEnable(GL_DEPTH_TEST);
    eglSwapBuffers(display_,surface_);
}

void RendererGles3::shutdown() {
    if (display_!=EGL_NO_DISPLAY) {
        const bool current=context_!=EGL_NO_CONTEXT && surface_!=EGL_NO_SURFACE &&
            eglMakeCurrent(display_,surface_,surface_,context_)==EGL_TRUE;
        if (current) {
            for (auto& mesh:meshes_) {
                if (mesh.vbo) glDeleteBuffers(1,&mesh.vbo);
                if (mesh.ibo) glDeleteBuffers(1,&mesh.ibo);
            }
            for (auto& group:scatterGroups_) {
                if (group.matrixBuffer) glDeleteBuffers(1,&group.matrixBuffer);
            }
            destroyFramebuffer();
            if (program_) glDeleteProgram(program_);
            if (postProgram_) glDeleteProgram(postProgram_);
        }
        meshes_.clear();
        scatterGroups_.clear();
        framebuffer_=colorTexture_=depthBuffer_=0;
        internalWidth_=internalHeight_=0;
        eglMakeCurrent(display_,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);
        if (context_!=EGL_NO_CONTEXT) eglDestroyContext(display_,context_);
        if (surface_!=EGL_NO_SURFACE) eglDestroySurface(display_,surface_);
        eglTerminate(display_);
    } else {
        meshes_.clear();
        scatterGroups_.clear();
    }
    display_=EGL_NO_DISPLAY; surface_=EGL_NO_SURFACE; context_=EGL_NO_CONTEXT;
    config_=nullptr;
    program_=0; postProgram_=0;
    uViewProjection_=uModel_=uInstanced_=uBaseColor_=-1;
    uMetallic_=uRoughness_=uEmissive_=uCameraPosition_=-1;
    uLightDirection_=uLightColor_=uLightIntensity_=uAmbient_=uPulse_=-1;
    pColor_=pTime_=pBloom_=pFlash_=pAberration_=pVignette_=pSaturation_=pContrast_=-1;
    pShock_=pShockCenter_=pJuicePulse_=-1;
    width_=height_=internalWidth_=internalHeight_=0;
    currentScale_=0.0f;
    gpuRenderer_.clear();
}

} // namespace kc
