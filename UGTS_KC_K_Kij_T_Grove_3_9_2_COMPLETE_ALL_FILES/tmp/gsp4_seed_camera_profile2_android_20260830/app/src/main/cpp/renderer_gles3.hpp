#pragma once
#include "chrono_video_lut.hpp"
#if !UGTS_KC_GSP4_SEED_CAMERA
#include "chrono_video_player.hpp"
#endif
#include "gpu_timer_query.hpp"
#include "grove_juice.hpp"
#include "polar_kinematics.hpp"
#include "polar_populations.hpp"
#include "render_substrate.hpp"
#include "scatter_population.hpp"
#include "scene_pack.hpp"
#include "transform_hierarchy.hpp"
#include "transform_animation.hpp"
#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <android/asset_manager.h>
#include <android/native_activity.h>
#include <android/native_window.h>
#include <limits>
#include <string>
#include <vector>

namespace kc {

class RendererGles3 {
public:
    static constexpr std::uint32_t PolarInstanceStrideBytes=36u;
    static constexpr std::uint32_t PolarMaterialValidFlag=0x40000000u;
    static constexpr std::uint32_t PolarGeneratedCopyFlag=0x80000000u;
    RendererGles3() = default;
    ~RendererGles3();
    bool initialize(
        ANativeWindow* window,
        ANativeActivity* activity,
        AAssetManager* assets,
        const ScenePack& scene,
        const ScatterPopulations& scatterPopulations,
        const PackedPolarKinematics& polarKinematics,
        const PolarPopulations& polarPopulations,
        const TransformHierarchy& transformHierarchy,
        const TransformAnimations& transformAnimations,
        const ChronoVideoLut& chronoVideoLut,
        const RenderSubstrateConfig& substrate
    );
    void shutdown();
    void setChronoFocused(bool focused,std::int64_t steadyNowNanoseconds) {
#if !UGTS_KC_GSP4_SEED_CAMERA
        chronoVideoPlayer_.setFocused(focused,steadyNowNanoseconds);
#else
        (void)focused;
        (void)steadyNowNanoseconds;
#endif
    }
    bool ready() const {
        return display_!=EGL_NO_DISPLAY && surface_!=EGL_NO_SURFACE &&
            context_!=EGL_NO_CONTEXT && program_!=0;
    }
    void render(
        const ScenePack& scene,const std::vector<NodeData>& nodes,
        const PackedPolarKinematics& polarKinematics,
        const PolarPopulations& polarPopulations,float polarAlpha,
        Vec3 cameraTarget,float yaw,float pitch,float distance,float renderScale,
        std::uint32_t maxNodes,std::uint32_t particleBudget,
        std::uint64_t fixedTick,float timeSeconds,std::int64_t steadyNowNanoseconds,
        const GroveJuiceFrame& juice,
        bool postProcessing
    );
    std::string gpuRenderer() const { return gpuRenderer_; }
    int width() const { return width_; }
    int height() const { return height_; }
private:
    struct GpuMesh { GLuint vbo=0,ibo=0; GLsizei indexCount=0; };
    struct GpuScatterGroup {
        GLuint matrixBuffer=0;
        std::uint32_t prototypeNodeIndex=0;
        GLsizei generatedCount=0;
    };
    struct GpuPolarProfile {
        GLuint lutTexture=0;
        float rhoMin=0.0f,rhoMax=0.0f,logR0=0.0f,radiusScale=1.0f;
        GLint lutSize=0;
    };
    struct PolarInstance {
        std::uint32_t previousLow=0,previousHigh=0,currentLow=0,currentHigh=0;
        float baseY=0.0f,scaleX=1.0f,scaleY=1.0f,scaleZ=1.0f;
        // Low 12 bits are the shared seeded material phase. Bit 30 marks a
        // valid KCPR material coordinate and bit 31 marks a generated copy,
        // without expanding this frozen 36-byte staging record.
        std::uint32_t glowPhase12=0;
    };
    static_assert(offsetof(PolarInstance,glowPhase12)==32u);
    static_assert(sizeof(PolarInstance)==PolarInstanceStrideBytes);
    struct GpuPolarGroup {
        GLuint instanceBuffer=0;
        std::uint16_t profile=0;
        std::uint16_t burstRecipeIndex=std::numeric_limits<std::uint16_t>::max();
        std::uint16_t glowRecipeIndex=std::numeric_limits<std::uint16_t>::max();
        std::uint32_t mesh=0,material=0;
        std::vector<std::uint32_t> componentIndices;
        // One entry per compact KCPR recipe, never one entry per generated
        // copy. Visible copies are derived from these ranges on demand.
        std::vector<std::uint16_t> populationRecipeIndices;
        std::vector<PolarPopulations::RenderCopy> visiblePopulationCopies;
        std::vector<PolarInstance> staging;
        GLsizeiptr capacityBytes=0;
        bool runtimeDisabled=false;
        bool uploadFailureLogged=false;
    };
    struct PolarUniforms {
        GLint viewProjection=-1,baseColor=-1,metallic=-1,roughness=-1,emissive=-1;
        GLint cameraPosition=-1,lightDirection=-1,lightColor=-1,lightIntensity=-1;
        GLint ambient=-1,pulse=-1,alpha=-1,profile=-1,lut=-1,lutSize=-1;
        GLint burstMode=-1,burstAnchorPose=-1,burstRecipe=-1,burstScale=-1;
        GLint glowMode=-1,glowRecipe=-1;
        GLint polarMaterialMode=-1,polarMaterialBands=-1;
        GLint polarMaterialStrength=-1;
    };
    bool createProgram(AAssetManager* assets);
    bool configurePolar(
        const ScenePack& scene,const PackedPolarKinematics& polarKinematics,
        const PolarPopulations& polarPopulations,
        const TransformHierarchy& transformHierarchy,
        const TransformAnimations& transformAnimations
    );
    bool uploadPolarLuts(const PackedPolarKinematics& polarKinematics);
    bool uploadChronoVideoLut(const ChronoVideoLut& chronoVideoLut);
    PolarUniforms polarUniforms(GLuint program) const;
    std::string readAsset(AAssetManager* assets,const char* name);
    GLuint compile(GLenum type,const std::string& source);
    void rebuildFramebuffer(int width,int height,float scale);
    void destroyFramebuffer();
    EGLDisplay display_=EGL_NO_DISPLAY;
    EGLSurface surface_=EGL_NO_SURFACE;
    EGLContext context_=EGL_NO_CONTEXT;
    EGLConfig config_=nullptr;
    GLuint program_=0,polarDirectProgram_=0,polarLutProgram_=0,postProgram_=0;
    GLint uViewProjection_=-1,uModel_=-1,uInstanced_=-1,uBaseColor_=-1;
    GLint uMetallic_=-1,uRoughness_=-1,uEmissive_=-1,uCameraPosition_=-1;
    GLint uLightDirection_=-1,uLightColor_=-1,uLightIntensity_=-1,uAmbient_=-1,uPulse_=-1;
    GLint uPolarGlowField_=-1;
    GLint uPolarMaterialCoord_=-1,uPolarMaterialMode_=-1;
    GLint uPolarMaterialBands_=-1,uPolarMaterialStrength_=-1;
    PolarUniforms directPolarUniforms_{},lutPolarUniforms_{};
    GLint pColor_=-1,pTime_=-1,pBloom_=-1,pFlash_=-1,pAberration_=-1,pVignette_=-1,pSaturation_=-1,pContrast_=-1,pShock_=-1,pShockCenter_=-1,pJuicePulse_=-1;
    GLint pBayerMode_=-1,pBayerLevels_=-1,pBayerStrength_=-1,pOutputHeight_=-1;
    std::vector<GpuMesh> meshes_;
    std::vector<GpuScatterGroup> scatterGroups_;
    std::vector<GpuPolarProfile> polarProfiles_;
    std::vector<GpuPolarGroup> polarGroups_;
    std::vector<std::uint8_t> gpuPolarNodeMask_;
    std::vector<std::int32_t> gpuPolarRecipeGroup_;
    std::vector<std::uint8_t> gpuPolarNodeQueued_;
    RenderSubstrateConfig substrate_{};
    PolarRenderMode effectivePolarMode_=PolarRenderMode::Cpu;
    std::string polarReason_="asset_absent";
    std::uint32_t gpuPolarInstanceCount_=0,gpuPolarFallbackCount_=0;
    std::uint32_t gpuPolarGeneratedCount_=0,cpuPolarGeneratedCount_=0;
    std::uint32_t loggedGeneratedVisible_=std::numeric_limits<std::uint32_t>::max();
    GpuTimerQuery gpuTimer_;
    std::uint64_t loggedGpuTimerSamples_=0;
    bool gpuTimerInitiallySupported_=false,gpuTimerRuntimeFailureLogged_=false;
    GLuint framebuffer_=0,colorTexture_=0,depthBuffer_=0;
    GLuint chronoVideoLutTexture_=0;
#if !UGTS_KC_GSP4_SEED_CAMERA
    ChronoVideoPlayer chronoVideoPlayer_;
#endif
    int width_=0,height_=0,internalWidth_=0,internalHeight_=0;
    float currentScale_=0;
    std::string gpuRenderer_;
};

} // namespace kc
