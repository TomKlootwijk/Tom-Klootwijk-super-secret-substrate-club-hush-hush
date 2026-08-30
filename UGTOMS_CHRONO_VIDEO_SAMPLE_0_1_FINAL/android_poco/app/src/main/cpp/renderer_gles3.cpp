#include "renderer_gles3.hpp"
#include <android/log.h>
#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <tuple>

#define KC_LOGE(...) __android_log_print(ANDROID_LOG_ERROR,"UGTS-KC392",__VA_ARGS__)
#define KC_LOGI(...) __android_log_print(ANDROID_LOG_INFO,"UGTS-KC392",__VA_ARGS__)

namespace kc {

static_assert(sizeof(Mat4)==16u*sizeof(float)); // GPU matrix instance ABI

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
    const auto polarSource=readAsset(assets,"shaders/polar_scene.vert");
    const auto polarDirectVs=compile(GL_VERTEX_SHADER,polarSource);
    auto polarLutSource=polarSource;
    const auto versionEnd=polarLutSource.find('\n');
    if (versionEnd!=std::string::npos)
        polarLutSource.insert(versionEnd+1u,"#define POLAR_LUT 1\n");
    const auto polarLutVs=versionEnd==std::string::npos
        ?GLuint{0}:compile(GL_VERTEX_SHADER,polarLutSource);
    const auto fs=compile(GL_FRAGMENT_SHADER,readAsset(assets,"shaders/scene.frag"));
    const auto pvs=compile(GL_VERTEX_SHADER,readAsset(assets,"shaders/grove_post.vert"));
    const auto pfs=compile(GL_FRAGMENT_SHADER,readAsset(assets,"shaders/grove_post.frag"));
    const GLuint shaders[]={vs,polarDirectVs,polarLutVs,fs,pvs,pfs};
    const auto deleteShaders=[&shaders]() {
        for (const GLuint shader:shaders) {
            if (shader) glDeleteShader(shader);
        }
    };
    if (!vs || !polarDirectVs || !fs || !pvs || !pfs) {
        deleteShaders();
        return false;
    }
    const auto link=[&](GLuint vertex,GLuint fragment,const char* label) {
        const auto result=glCreateProgram();
        glAttachShader(result,vertex); glAttachShader(result,fragment); glLinkProgram(result);
        GLint ok=GL_FALSE; glGetProgramiv(result,GL_LINK_STATUS,&ok);
        if (ok) return result;
        char log[2048]{};
        glGetProgramInfoLog(result,sizeof(log),nullptr,log);
        KC_LOGE("%s program link failed: %s",label,log);
        glDeleteProgram(result);
        return GLuint{0};
    };
    program_=link(vs,fs,"scene");
    polarDirectProgram_=link(polarDirectVs,fs,"polar direct scene");
    if (polarLutVs) polarLutProgram_=link(polarLutVs,fs,"polar LUT scene");
    postProgram_=link(pvs,pfs,"post");
    if (!program_ || !polarDirectProgram_ || !postProgram_) {
        deleteShaders();
        return false;
    }
    KC_LOGI("render shaders scene=linked polar_direct=linked polar_lut=%s post=linked",
        polarLutProgram_?"linked":"unavailable");
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
    uPolarGlowField_=glGetUniformLocation(program_,"uPolarGlowField");
    uPolarMaterialCoord_=glGetUniformLocation(program_,"uPolarMaterialCoord");
    uPolarMaterialMode_=glGetUniformLocation(program_,"uPolarMaterialMode");
    uPolarMaterialBands_=glGetUniformLocation(program_,"uPolarMaterialBands");
    uPolarMaterialStrength_=glGetUniformLocation(program_,"uPolarMaterialStrength");
    directPolarUniforms_=polarUniforms(polarDirectProgram_);
    if (polarLutProgram_) lutPolarUniforms_=polarUniforms(polarLutProgram_);
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
    pBayerMode_=glGetUniformLocation(postProgram_,"uBayerMode");
    pBayerLevels_=glGetUniformLocation(postProgram_,"uBayerLevels");
    pBayerStrength_=glGetUniformLocation(postProgram_,"uBayerStrength");
    pOutputHeight_=glGetUniformLocation(postProgram_,"uOutputHeight");
    deleteShaders();
    return true;
}

RendererGles3::PolarUniforms RendererGles3::polarUniforms(GLuint program) const {
    PolarUniforms result;
    result.viewProjection=glGetUniformLocation(program,"uViewProjection");
    result.baseColor=glGetUniformLocation(program,"uBaseColor");
    result.metallic=glGetUniformLocation(program,"uMetallic");
    result.roughness=glGetUniformLocation(program,"uRoughness");
    result.emissive=glGetUniformLocation(program,"uEmissive");
    result.cameraPosition=glGetUniformLocation(program,"uCameraPosition");
    result.lightDirection=glGetUniformLocation(program,"uLightDirection");
    result.lightColor=glGetUniformLocation(program,"uLightColor");
    result.lightIntensity=glGetUniformLocation(program,"uLightIntensity");
    result.ambient=glGetUniformLocation(program,"uAmbient");
    result.pulse=glGetUniformLocation(program,"uPulse");
    result.alpha=glGetUniformLocation(program,"uPolarAlpha");
    result.profile=glGetUniformLocation(program,"uPolarProfile");
    result.lut=glGetUniformLocation(program,"uPolarLut");
    result.lutSize=glGetUniformLocation(program,"uPolarLutSize");
    result.burstMode=glGetUniformLocation(program,"uBurstMode");
    result.burstAnchorPose=glGetUniformLocation(program,"uBurstAnchorPose");
    result.burstRecipe=glGetUniformLocation(program,"uBurstRecipe");
    result.burstScale=glGetUniformLocation(program,"uBurstScale");
    result.glowMode=glGetUniformLocation(program,"uGlowMode");
    result.glowRecipe=glGetUniformLocation(program,"uGlowRecipe");
    result.polarMaterialMode=glGetUniformLocation(program,"uPolarMaterialMode");
    result.polarMaterialBands=glGetUniformLocation(program,"uPolarMaterialBands");
    result.polarMaterialStrength=glGetUniformLocation(program,"uPolarMaterialStrength");
    return result;
}

bool RendererGles3::uploadPolarLuts(const PackedPolarKinematics& polarKinematics) {
    GLint maximumTextureSize=0;
    glGetIntegerv(GL_MAX_TEXTURE_SIZE,&maximumTextureSize);
    while (glGetError()!=GL_NO_ERROR) {}
    const auto& profiles=polarKinematics.profiles();
    for (std::size_t profileIndex=0;profileIndex<profiles.size();++profileIndex) {
        const auto& source=profiles[profileIndex];
        auto& target=polarProfiles_[profileIndex];
        const auto count=source.sine.size();
        if (count<2 || source.cosine.size()!=count || source.normalizedRadii.size()!=count ||
            source.sineHalf.size()!=count || source.cosineHalf.size()!=count ||
            source.normalizedRadiusHalf.size()!=count ||
            count+1u>static_cast<std::size_t>(std::max(0,maximumTextureSize))) return false;
        std::vector<std::uint16_t> texels((count+1u)*4u,0u);
        for (std::size_t index=0;index<count;++index) {
            // The vertex shader consumes direction.xy as world X/Z. Match
            // the authoritative CPU/direct convention: X=cos(theta), Z=sin(theta).
            texels[index*4u]=source.cosineHalf[index];
            texels[index*4u+1u]=source.sineHalf[index];
            texels[index*4u+2u]=source.normalizedRadiusHalf[index];
        }
        // Direction interpolation may cross theta=Tau. A duplicated first
        // direction sample makes that seam an ordinary adjacent fetch.
        texels[count*4u]=source.cosineHalf.front();
        texels[count*4u+1u]=source.sineHalf.front();
        texels[count*4u+2u]=source.normalizedRadiusHalf.back();
        glGenTextures(1,&target.lutTexture);
        if (!target.lutTexture) return false;
        glBindTexture(GL_TEXTURE_2D,target.lutTexture);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
        glTexImage2D(
            GL_TEXTURE_2D,0,GL_RGBA16F,static_cast<GLsizei>(count+1u),1,0,
            GL_RGBA,GL_HALF_FLOAT,texels.data()
        );
        if (glGetError()!=GL_NO_ERROR) return false;
        target.lutSize=static_cast<GLint>(count);
    }
    glBindTexture(GL_TEXTURE_2D,0);
    return true;
}

bool RendererGles3::uploadChronoVideoLut(const ChronoVideoLut& source) {
    if (!source.present) return true;
    GLint maximumTextureSize=0;
    glGetIntegerv(GL_MAX_TEXTURE_SIZE,&maximumTextureSize);
    if (source.thetaBins>static_cast<std::uint32_t>(std::max(0,maximumTextureSize)) ||
        source.rhoBins>static_cast<std::uint32_t>(std::max(0,maximumTextureSize))) {
        KC_LOGE("UGCVLUT1 dimensions exceed GL_MAX_TEXTURE_SIZE");
        return false;
    }
    while (glGetError()!=GL_NO_ERROR) {}
    glGenTextures(1,&chronoVideoLutTexture_);
    if (!chronoVideoLutTexture_) return false;
    glBindTexture(GL_TEXTURE_2D,chronoVideoLutTexture_);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
    glTexImage2D(
        GL_TEXTURE_2D,0,GL_RGBA16UI,
        static_cast<GLsizei>(source.thetaBins),static_cast<GLsizei>(source.rhoBins),0,
        GL_RGBA_INTEGER,GL_UNSIGNED_SHORT,source.texels.data()
    );
    const auto error=glGetError();
    glBindTexture(GL_TEXTURE_2D,0);
    if (error!=GL_NO_ERROR) {
        KC_LOGE("UGCVLUT1 RGBA16UI upload failed: GL error 0x%x",error);
        return false;
    }
    KC_LOGI(
        "UGCVLUT1 uploaded to GLES3: source=%ux%u polar=%ux%u bytes=%zu authority=derived_cache",
        source.sourceWidth,source.sourceHeight,source.thetaBins,source.rhoBins,
        source.texels.size()*sizeof(std::uint16_t)
    );
    return true;
}

bool RendererGles3::configurePolar(
    const ScenePack& scene,const PackedPolarKinematics& polarKinematics,
    const PolarPopulations& polarPopulations,
    const TransformHierarchy& transformHierarchy,
    const TransformAnimations& transformAnimations
) {
    const auto& profiles=polarKinematics.profiles();
    const auto& components=polarKinematics.components();
    const auto generatedCount=polarPopulations.generatedCount();
    const auto totalPolarInstances=components.size()+generatedCount;
    polarProfiles_.assign(profiles.size(),{});
    polarGroups_.clear();
    gpuPolarNodeMask_.assign(scene.nodes.size(),0u);
    gpuPolarRecipeGroup_.assign(polarPopulations.recipeCount(),-1);
    gpuPolarNodeQueued_.assign(scene.nodes.size(),0u);
    gpuPolarInstanceCount_=0;
    gpuPolarGeneratedCount_=0;
    cpuPolarGeneratedCount_=static_cast<std::uint32_t>(generatedCount);
    gpuPolarFallbackCount_=static_cast<std::uint32_t>(totalPolarInstances);
    effectivePolarMode_=PolarRenderMode::Cpu;
    polarReason_=substrate_.present?"requested_cpu":"asset_absent";
    const auto releaseGpuPolar=[this]() {
        for (auto& group:polarGroups_) {
            if (group.instanceBuffer) glDeleteBuffers(1,&group.instanceBuffer);
            group.instanceBuffer=0;
        }
        polarGroups_.clear();
        for (auto& profile:polarProfiles_) {
            if (profile.lutTexture) glDeleteTextures(1,&profile.lutTexture);
            profile.lutTexture=0;
        }
        std::fill(gpuPolarNodeMask_.begin(),gpuPolarNodeMask_.end(),0u);
        std::fill(gpuPolarRecipeGroup_.begin(),gpuPolarRecipeGroup_.end(),-1);
        gpuPolarInstanceCount_=0;
        gpuPolarGeneratedCount_=0;
    };

    for (std::size_t index=0;index<profiles.size();++index) {
        const auto& source=profiles[index];
        auto& target=polarProfiles_[index];
        target.rhoMin=static_cast<float>(source.rhoMin);
        target.rhoMax=static_cast<float>(source.rhoMax);
        target.logR0=static_cast<float>(std::log(source.r0));
        target.radiusScale=source.radiusScale;
        const auto minimumExponent=target.logR0+target.rhoMin;
        const auto maximumExponent=target.logR0+target.rhoMax;
        const auto minimumSafeExponent=std::log(std::numeric_limits<float>::min());
        const auto maximumSafeExponent=std::log(std::numeric_limits<float>::max());
        if (!std::isfinite(target.rhoMin)||!std::isfinite(target.rhoMax)||
            !std::isfinite(target.logR0)||!std::isfinite(target.radiusScale)||
            !std::isfinite(minimumExponent)||!std::isfinite(maximumExponent)||
            target.rhoMin>=target.rhoMax||target.radiusScale<=0.0f||
            minimumExponent<minimumSafeExponent||
            maximumExponent>maximumSafeExponent) {
            polarReason_="profile_not_binary32";
            KC_LOGI("render substrate polar_requested=%s polar_effective=cpu gpu_instances=0 gpu_profiles=0 gpu_batches=0 cpu_fallbacks=%u animation_fallbacks=0 polar_recipes=%u generated=%u generated_gpu=0 generated_cpu=%u reason=%s polar_material=%s material_bands=%u material_strength=%.3f bayer=%s levels=%u strength=%.3f",
                polarRenderModeName(substrate_.polarMode),
                static_cast<unsigned>(totalPolarInstances),
                static_cast<unsigned>(polarPopulations.recipeCount()),
                static_cast<unsigned>(generatedCount),
                static_cast<unsigned>(generatedCount),polarReason_.c_str(),
                polarMaterialModeName(substrate_.polarMaterialMode),
                static_cast<unsigned>(substrate_.polarMaterialBands),
                substrate_.polarMaterialStrength,
                bayerRenderModeName(substrate_.bayerMode),
                static_cast<unsigned>(substrate_.levels),substrate_.strength);
            return true;
        }
    }

    if (totalPolarInstances==0u) {
        polarReason_="no_polar_components";
    } else if (substrate_.present && substrate_.polarMode!=PolarRenderMode::Cpu) {
        GLint attributes=0,vertexTextures=0;
        glGetIntegerv(GL_MAX_VERTEX_ATTRIBS,&attributes);
        glGetIntegerv(GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS,&vertexTextures);
        if (attributes<5) {
            polarReason_="insufficient_vertex_attributes";
        } else if (substrate_.polarMode==PolarRenderMode::Direct) {
            effectivePolarMode_=PolarRenderMode::Direct;
            polarReason_="none";
        } else if (substrate_.polarMode==PolarRenderMode::Lut) {
            if (!polarLutProgram_) polarReason_="lut_shader_unavailable";
            else if (vertexTextures<1) polarReason_="no_vertex_texture_units";
            else if (!uploadPolarLuts(polarKinematics)) polarReason_="lut_upload_failed";
            else { effectivePolarMode_=PolarRenderMode::Lut; polarReason_="none"; }
        } else {
            if (polarLutProgram_ && vertexTextures>=1 && uploadPolarLuts(polarKinematics)) {
                effectivePolarMode_=PolarRenderMode::Lut;
                polarReason_="auto_lut";
            } else {
                for (auto& profile:polarProfiles_) {
                    if (profile.lutTexture) glDeleteTextures(1,&profile.lutTexture);
                    profile.lutTexture=0;
                }
                effectivePolarMode_=PolarRenderMode::Direct;
                polarReason_=!polarLutProgram_?"auto_direct_lut_shader_unavailable":
                    (vertexTextures<1?"auto_direct_no_vertex_textures":"auto_direct_lut_upload_failed");
            }
        }
    }

    std::uint32_t hierarchyFallbacks=0,animationFallbacks=0,referenceFallbacks=0;
    if (effectivePolarMode_==PolarRenderMode::Cpu) releaseGpuPolar();
    if (effectivePolarMode_!=PolarRenderMode::Cpu) {
        std::map<std::tuple<std::uint16_t,std::uint32_t,std::uint32_t>,std::size_t> groups;
        const auto& populationRecipes=polarPopulations.recipes();
        std::vector<std::int32_t> glowRecipeByNode(scene.nodes.size(),-1);
        std::vector<std::int32_t> glowPrototypeGroups(
            populationRecipes.size(),-1
        );
        for (std::size_t recipeIndex=0;
                recipeIndex<populationRecipes.size();++recipeIndex) {
            const auto& recipe=populationRecipes[recipeIndex];
            if (recipe.glow && recipe.prototypeSceneNode<glowRecipeByNode.size())
                glowRecipeByNode[recipe.prototypeSceneNode]=
                    static_cast<std::int32_t>(recipeIndex);
        }
        for (std::size_t componentIndex=0;componentIndex<components.size();++componentIndex) {
            const auto& component=components[componentIndex];
            if (transformAnimations.owns(component.sceneNode)) {
                ++animationFallbacks;
                continue;
            }
            // A polar root is logically valid, but GPU interpolation would
            // detach it from ordinary children composed at current fixed TRS.
            if (transformHierarchy.isLinked(component.sceneNode)) {
                ++hierarchyFallbacks;
                continue;
            }
            if (component.sceneNode>=scene.nodes.size()) {
                ++referenceFallbacks;
                continue;
            }
            const auto& node=scene.nodes[component.sceneNode];
            if (node.meshIndex>=scene.meshes.size()||node.materialIndex>=scene.materials.size()) {
                ++referenceFallbacks;
                continue;
            }
            const auto glowRecipeIndex=glowRecipeByNode[component.sceneNode];
            if (glowRecipeIndex>=0) {
                GpuPolarGroup group;
                group.profile=component.profile;
                group.mesh=node.meshIndex;
                group.material=node.materialIndex;
                group.glowRecipeIndex=static_cast<std::uint16_t>(
                    glowRecipeIndex
                );
                group.componentIndices.push_back(
                    static_cast<std::uint32_t>(componentIndex)
                );
                polarGroups_.push_back(std::move(group));
                glowPrototypeGroups[static_cast<std::size_t>(glowRecipeIndex)]=
                    static_cast<std::int32_t>(polarGroups_.size()-1u);
                continue;
            }
            const auto key=std::make_tuple(component.profile,node.meshIndex,node.materialIndex);
            auto found=groups.find(key);
            if (found==groups.end()) {
                GpuPolarGroup group;
                group.profile=component.profile;
                group.mesh=node.meshIndex;
                group.material=node.materialIndex;
                polarGroups_.push_back(std::move(group));
                found=groups.emplace(key,polarGroups_.size()-1u).first;
            }
            polarGroups_[found->second].componentIndices.push_back(
                static_cast<std::uint32_t>(componentIndex)
            );
        }
        for (std::size_t recipeIndex=0;
                recipeIndex<populationRecipes.size();++recipeIndex) {
            const auto& recipe=populationRecipes[recipeIndex];
            const auto prototypeSceneNode=recipe.prototypeSceneNode;
            const auto copyProfile=recipe.profile;
            if (transformAnimations.owns(prototypeSceneNode)) {
                animationFallbacks+=recipe.generatedCount;
                continue;
            }
            if (transformHierarchy.isLinked(prototypeSceneNode)) {
                hierarchyFallbacks+=recipe.generatedCount;
                continue;
            }
            if (prototypeSceneNode>=scene.nodes.size() ||
                copyProfile>=profiles.size()) {
                referenceFallbacks+=recipe.generatedCount;
                continue;
            }
            const auto& node=scene.nodes[prototypeSceneNode];
            if (node.meshIndex>=scene.meshes.size()||
                node.materialIndex>=scene.materials.size()) {
                referenceFallbacks+=recipe.generatedCount;
                continue;
            }
            if (recipe.preset==4u) {
                GpuPolarGroup group;
                group.profile=copyProfile;
                group.mesh=node.meshIndex;
                group.material=node.materialIndex;
                group.burstRecipeIndex=static_cast<std::uint16_t>(recipeIndex);
                if (recipe.glow)
                    group.glowRecipeIndex=static_cast<std::uint16_t>(recipeIndex);
                group.populationRecipeIndices.push_back(
                    static_cast<std::uint16_t>(recipeIndex)
                );
                polarGroups_.push_back(std::move(group));
                continue;
            }
            if (recipe.glow) {
                const auto groupIndex=glowPrototypeGroups[recipeIndex];
                if (groupIndex<0 ||
                    static_cast<std::size_t>(groupIndex)>=polarGroups_.size()) {
                    referenceFallbacks+=recipe.generatedCount;
                    continue;
                }
                polarGroups_[static_cast<std::size_t>(groupIndex)].
                    populationRecipeIndices.push_back(
                        static_cast<std::uint16_t>(recipeIndex)
                    );
                continue;
            }
            const auto key=std::make_tuple(
                copyProfile,node.meshIndex,node.materialIndex
            );
            auto found=groups.find(key);
            if (found==groups.end()) {
                GpuPolarGroup group;
                group.profile=copyProfile;
                group.mesh=node.meshIndex;
                group.material=node.materialIndex;
                polarGroups_.push_back(std::move(group));
                found=groups.emplace(key,polarGroups_.size()-1u).first;
            }
            polarGroups_[found->second].populationRecipeIndices.push_back(
                static_cast<std::uint16_t>(recipeIndex)
            );
        }
        bool buffersReady=true;
        std::size_t maximumVisibleCapacity=0;
        for (const auto& quality:scene.qualities)
            maximumVisibleCapacity=std::max<std::size_t>(
                maximumVisibleCapacity,quality.maxVisibleNodes
            );
        maximumVisibleCapacity=std::max<std::size_t>(1u,maximumVisibleCapacity);
        for (auto& group:polarGroups_) {
            std::size_t possibleGeneratedInstances=0;
            for (const auto recipeIndex:group.populationRecipeIndices) {
                possibleGeneratedInstances+=populationRecipes[recipeIndex].generatedCount;
            }
            const auto possibleInstances=group.componentIndices.size()+
                possibleGeneratedInstances;
            const auto instanceCapacity=std::min(
                possibleInstances,maximumVisibleCapacity
            );
            group.staging.reserve(instanceCapacity);
            group.visiblePopulationCopies.reserve(std::min(
                possibleGeneratedInstances,maximumVisibleCapacity
            ));
            group.capacityBytes=static_cast<GLsizeiptr>(
                instanceCapacity*sizeof(PolarInstance)
            );
            while (glGetError()!=GL_NO_ERROR) {}
            glGenBuffers(1,&group.instanceBuffer);
            if (!group.instanceBuffer || glGetError()!=GL_NO_ERROR) {
                buffersReady=false;
                break;
            }
            glBindBuffer(GL_ARRAY_BUFFER,group.instanceBuffer);
            if (glGetError()!=GL_NO_ERROR) { buffersReady=false; break; }
            glBufferData(GL_ARRAY_BUFFER,group.capacityBytes,nullptr,GL_DYNAMIC_DRAW);
            if (glGetError()!=GL_NO_ERROR) { buffersReady=false; break; }
        }
        glBindBuffer(GL_ARRAY_BUFFER,0);
        if (!buffersReady) {
            effectivePolarMode_=PolarRenderMode::Cpu;
            polarReason_="instance_buffer_allocation_failed";
        } else {
            for (std::size_t groupIndex=0;groupIndex<polarGroups_.size();++groupIndex) {
                const auto& group=polarGroups_[groupIndex];
                for (const auto componentIndex:group.componentIndices) {
                    const auto nodeIndex=components[componentIndex].sceneNode;
                    gpuPolarNodeMask_[nodeIndex]=1u;
                    ++gpuPolarInstanceCount_;
                }
                for (const auto recipeIndex:group.populationRecipeIndices) {
                    gpuPolarRecipeGroup_[recipeIndex]=static_cast<std::int32_t>(groupIndex);
                    const auto recipeGenerated=populationRecipes[recipeIndex].generatedCount;
                    gpuPolarInstanceCount_+=recipeGenerated;
                    gpuPolarGeneratedCount_+=recipeGenerated;
                }
            }
            if (polarGroups_.empty()) {
                effectivePolarMode_=PolarRenderMode::Cpu;
                polarReason_=animationFallbacks?"animation_owned":
                    (hierarchyFallbacks?"hierarchy_linked":"invalid_render_reference");
            } else if (animationFallbacks) polarReason_="animation_owned";
            else if (hierarchyFallbacks) polarReason_="hierarchy_linked";
            else if (referenceFallbacks) polarReason_="invalid_render_reference";
        }
    }
    if (effectivePolarMode_==PolarRenderMode::Cpu) releaseGpuPolar();
    gpuPolarFallbackCount_=static_cast<std::uint32_t>(totalPolarInstances)-
        gpuPolarInstanceCount_;
    cpuPolarGeneratedCount_=static_cast<std::uint32_t>(generatedCount)-
        gpuPolarGeneratedCount_;
    std::vector<std::uint8_t> usedProfiles(profiles.size(),0u);
    for (const auto& group:polarGroups_) usedProfiles[group.profile]=1u;
    const auto gpuProfiles=static_cast<unsigned>(std::count(usedProfiles.begin(),usedProfiles.end(),1u));
    KC_LOGI("render substrate polar_requested=%s polar_effective=%s gpu_instances=%u gpu_profiles=%u gpu_batches=%u cpu_fallbacks=%u animation_fallbacks=%u polar_recipes=%u generated=%u generated_gpu=%u generated_cpu=%u reason=%s polar_material=%s material_bands=%u material_strength=%.3f bayer=%s levels=%u strength=%.3f",
        polarRenderModeName(substrate_.polarMode),polarRenderModeName(effectivePolarMode_),
        static_cast<unsigned>(gpuPolarInstanceCount_),gpuProfiles,
        static_cast<unsigned>(polarGroups_.size()),static_cast<unsigned>(gpuPolarFallbackCount_),
        static_cast<unsigned>(animationFallbacks),
        static_cast<unsigned>(polarPopulations.recipeCount()),
        static_cast<unsigned>(generatedCount),
        static_cast<unsigned>(gpuPolarGeneratedCount_),
        static_cast<unsigned>(cpuPolarGeneratedCount_),
        polarReason_.c_str(),polarMaterialModeName(substrate_.polarMaterialMode),
        static_cast<unsigned>(substrate_.polarMaterialBands),
        substrate_.polarMaterialStrength,bayerRenderModeName(substrate_.bayerMode),
        static_cast<unsigned>(substrate_.levels),substrate_.strength);
    return true;
}

bool RendererGles3::initialize(
    ANativeWindow* window,
    AAssetManager* assets,
    const ScenePack& scene,
    const ScatterPopulations& scatterPopulations,
    const PackedPolarKinematics& polarKinematics,
    const PolarPopulations& polarPopulations,
    const TransformHierarchy& transformHierarchy,
    const TransformAnimations& transformAnimations,
    const ChronoVideoLut& chronoVideoLut,
    const RenderSubstrateConfig& substrate
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
    gpuTimerInitiallySupported_=gpuTimer_.initialize();
    const auto initialTimer=gpuTimer_.stats();
    KC_LOGI(
        "gpu timer supported=%s bits=%u extension=GL_EXT_disjoint_timer_query "
        "nonblocking=true reason=%s",
        gpuTimerInitiallySupported_?"true":"false",
        static_cast<unsigned>(initialTimer.counterBits),
        gpuTimerInitiallySupported_?"ready":"extension_or_counter_bits_unavailable"
    );
    substrate_=substrate;
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
    if (!configurePolar(
            scene,polarKinematics,polarPopulations,
            transformHierarchy,transformAnimations
        )) return rollback();
    if (!uploadChronoVideoLut(chronoVideoLut)) return rollback();
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

void RendererGles3::render(
    const ScenePack& scene,const std::vector<NodeData>& nodes,
    const PackedPolarKinematics& polarKinematics,
    const PolarPopulations& polarPopulations,float polarAlpha,
    Vec3 target,float yaw,float pitch,float distance,float scale,
    std::uint32_t maxNodes,std::uint32_t particleBudget,
    std::uint64_t fixedTick,float time,const GroveJuiceFrame& juice,
    bool postProcessing
) {
    if (!ready()) return;
    gpuTimer_.beginFrame();
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
    glUniform1i(
        uPolarMaterialMode_,static_cast<GLint>(substrate_.polarMaterialMode)
    );
    glUniform1i(
        uPolarMaterialBands_,static_cast<GLint>(substrate_.polarMaterialBands)
    );
    glUniform1f(uPolarMaterialStrength_,substrate_.polarMaterialStrength);
    glUniform4f(uPolarMaterialCoord_,0.0f,0.0f,0.0f,-1.0f);

    polarPopulations.beginFrame();
    for (auto& group:polarGroups_) group.visiblePopulationCopies.clear();
    if (gpuPolarNodeQueued_.size()!=gpuPolarNodeMask_.size())
        gpuPolarNodeQueued_.assign(gpuPolarNodeMask_.size(),0u);
    else std::fill(gpuPolarNodeQueued_.begin(),gpuPolarNodeQueued_.end(),0u);
    const auto& populationRecipes=polarPopulations.recipes();
    std::vector<std::int32_t> glowRecipeByNode(nodes.size(),-1);
    std::vector<std::int32_t> populationRecipeByNode(nodes.size(),-1);
    for (std::size_t recipeIndex=0;
            recipeIndex<populationRecipes.size();++recipeIndex) {
        const auto& recipe=populationRecipes[recipeIndex];
        if (recipe.prototypeSceneNode<populationRecipeByNode.size())
            populationRecipeByNode[recipe.prototypeSceneNode]=
                static_cast<std::int32_t>(recipeIndex);
        if (recipe.glow && recipe.prototypeSceneNode<glowRecipeByNode.size())
            glowRecipeByNode[recipe.prototypeSceneNode]=
                static_cast<std::int32_t>(recipeIndex);
    }
    const auto cpuGlow=[&](
        std::size_t recipeIndex,std::uint32_t instanceIndex,
        std::uint64_t previousPose,std::uint64_t currentPose
    ) {
        // CPU fallback geometry is composed at the current fixed endpoint,
        // so its authored-LUT material reference must sample that same pose.
        return polarPopulations.evaluateGlow(
            recipeIndex,instanceIndex,previousPose,currentPose,1.0f,
            polarKinematics,PolarPopulations::GlowDirectionMode::Lut
        );
    };
    const auto cpuMaterialCoordinate=[&](
        std::size_t recipeIndex,std::uint32_t instanceIndex,std::uint64_t pose
    ) {
        const auto& recipe=populationRecipes[recipeIndex];
        return polarPopulations.materialCoordinate(
            recipeIndex,instanceIndex,
            polarKinematics.samplePoseChart(recipe.profile,pose)
        );
    };
    const auto drawOrdinaryNode=[this,&scene](
        const NodeData& node,float glowField,
        const PolarPopulations::MaterialCoordinate& materialCoordinate
    ) {
        const auto& gpu=meshes_[node.meshIndex];
        const auto& material=scene.materials[node.materialIndex];
        const auto model=trs(node.translation,node.rotation,node.scale);
        glUniformMatrix4fv(uModel_,1,GL_FALSE,model.data());
        glUniform4fv(uBaseColor_,1,material.baseColor.data());
        glUniform1f(uMetallic_,material.metallic);
        glUniform1f(uRoughness_,material.roughness);
        glUniform3f(uEmissive_,material.emissive.x,material.emissive.y,material.emissive.z);
        glUniform1f(uPolarGlowField_,glowField);
        glUniform4f(
            uPolarMaterialCoord_,materialCoordinate.normalizedRho,
            materialCoordinate.directionX,materialCoordinate.directionY,
            materialCoordinate.phase
        );
        if (material.doubleSided) glDisable(GL_CULL_FACE); else glEnable(GL_CULL_FACE);
        glBindBuffer(GL_ARRAY_BUFFER,gpu.vbo);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(Vertex),
            reinterpret_cast<void*>(offsetof(Vertex,position)));
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1,3,GL_FLOAT,GL_FALSE,sizeof(Vertex),
            reinterpret_cast<void*>(offsetof(Vertex,normal)));
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,gpu.ibo);
        glDrawElements(GL_TRIANGLES,gpu.indexCount,GL_UNSIGNED_INT,nullptr);
    };

    std::uint32_t drawn=0;
    glUniform1i(uInstanced_,GL_FALSE);
    for (const auto& node:nodes) {
        if (drawn>=maxNodes) break;
        const auto nodeIndex=static_cast<std::size_t>(&node-nodes.data());
        if (!node.alive || !node.active || node.meshIndex>=meshes_.size() || node.materialIndex>=scene.materials.size()) continue;
        if (nodeIndex<gpuPolarNodeMask_.size() && gpuPolarNodeMask_[nodeIndex]) {
            gpuPolarNodeQueued_[nodeIndex]=1u;
            ++drawn;
            continue;
        }
        float glowField=0.0f;
        PolarPopulations::MaterialCoordinate materialCoordinate;
        if (nodeIndex<glowRecipeByNode.size() &&
            glowRecipeByNode[nodeIndex]>=0) {
            const auto* component=polarKinematics.componentForSceneNode(
                static_cast<std::uint32_t>(nodeIndex)
            );
            if (component) glowField=cpuGlow(
                static_cast<std::size_t>(glowRecipeByNode[nodeIndex]),0u,
                component->previousPose,component->pose
            );
        }
        if (nodeIndex<populationRecipeByNode.size() &&
            populationRecipeByNode[nodeIndex]>=0) {
            const auto* component=polarKinematics.componentForSceneNode(
                static_cast<std::uint32_t>(nodeIndex)
            );
            if (component) materialCoordinate=cpuMaterialCoordinate(
                static_cast<std::size_t>(populationRecipeByNode[nodeIndex]),0u,
                component->pose
            );
        }
        drawOrdinaryNode(node,glowField,materialCoordinate);
        ++drawn;
    }
    std::uint32_t visibleGenerated=0,visibleGeneratedGpu=0,visibleGeneratedCpu=0;
    std::uint32_t remainingBurstBudget=particleBudget;
    for (std::size_t recipeIndex=0;
            recipeIndex<populationRecipes.size() && drawn<maxNodes;
            ++recipeIndex) {
        if (!polarPopulations.copiesVisible(recipeIndex)) continue;
        const auto& recipe=populationRecipes[recipeIndex];
        if (recipe.preset==4u && remainingBurstBudget==0u) continue;
        const auto prototypeIndex=recipe.prototypeSceneNode;
        if (prototypeIndex>=nodes.size()) continue;
        const auto& prototype=nodes[prototypeIndex];
        if (!prototype.alive || !prototype.active ||
            prototype.meshIndex>=meshes_.size() ||
            prototype.materialIndex>=scene.materials.size()) continue;
        const auto groupIndex=recipeIndex<gpuPolarRecipeGroup_.size()
            ?gpuPolarRecipeGroup_[recipeIndex]:-1;
        const bool gpuCopy=groupIndex>=0 &&
            static_cast<std::size_t>(groupIndex)<polarGroups_.size() &&
            !polarGroups_[static_cast<std::size_t>(groupIndex)].runtimeDisabled &&
            polarGroups_[static_cast<std::size_t>(groupIndex)].mesh==prototype.meshIndex &&
            polarGroups_[static_cast<std::size_t>(groupIndex)].material==prototype.materialIndex;
        for (std::uint32_t localIndex=0;
                localIndex<recipe.generatedCount && drawn<maxNodes &&
                (recipe.preset!=4u || remainingBurstBudget>0u);
                ++localIndex) {
            const auto copyIndex=static_cast<std::size_t>(
                recipe.firstGenerated+localIndex
            );
            if (gpuCopy) {
                polarGroups_[static_cast<std::size_t>(groupIndex)].visiblePopulationCopies.push_back(
                    polarPopulations.materialize(
                        copyIndex,polarKinematics,nodes,fixedTick,false
                    )
                );
                if (recipe.preset==4u) --remainingBurstBudget;
                ++drawn;
                ++visibleGenerated;
                ++visibleGeneratedGpu;
                continue;
            }
            const auto copy=polarPopulations.materialize(
                copyIndex,polarKinematics,nodes,fixedTick,true
            );
            if (recipe.preset==4u) --remainingBurstBudget;
            drawOrdinaryNode(
                copy.node,copy.glowField,copy.materialCoordinate
            );
            ++drawn;
            ++visibleGenerated;
            ++visibleGeneratedCpu;
        }
    }
    if (!polarGroups_.empty() && effectivePolarMode_!=PolarRenderMode::Cpu) {
        const bool lutMode=effectivePolarMode_==PolarRenderMode::Lut;
        const auto polarProgram=lutMode?polarLutProgram_:polarDirectProgram_;
        const auto& uniforms=lutMode?lutPolarUniforms_:directPolarUniforms_;
        glUseProgram(polarProgram);
        glUniformMatrix4fv(uniforms.viewProjection,1,GL_FALSE,vp.data());
        glUniform3f(uniforms.cameraPosition,eye.x,eye.y,eye.z);
        glUniform3f(uniforms.lightDirection,
            scene.lightDirection.x,scene.lightDirection.y,scene.lightDirection.z);
        glUniform3f(uniforms.lightColor,
            scene.lightColor.x,scene.lightColor.y,scene.lightColor.z);
        glUniform1f(uniforms.lightIntensity,scene.lightIntensity);
        glUniform1f(uniforms.ambient,scene.ambient);
        glUniform1f(uniforms.pulse,std::sin(time*2.0f));
        glUniform1f(uniforms.alpha,clamp(polarAlpha,0.0f,1.0f));
        glUniform1i(
            uniforms.polarMaterialMode,
            static_cast<GLint>(substrate_.polarMaterialMode)
        );
        glUniform1i(
            uniforms.polarMaterialBands,
            static_cast<GLint>(substrate_.polarMaterialBands)
        );
        glUniform1f(
            uniforms.polarMaterialStrength,substrate_.polarMaterialStrength
        );
        const auto& components=polarKinematics.components();
        for (auto& group:polarGroups_) {
            if (group.runtimeDisabled) continue;
            if (group.profile>=polarProfiles_.size() || group.mesh>=meshes_.size() ||
                group.material>=scene.materials.size()) continue;
            auto& instances=group.staging;
            instances.clear();
            for (const auto componentIndex:group.componentIndices) {
                if (componentIndex>=components.size()) continue;
                const auto& component=components[componentIndex];
                if (component.sceneNode>=nodes.size() ||
                    component.sceneNode>=gpuPolarNodeQueued_.size() ||
                    !gpuPolarNodeQueued_[component.sceneNode]) continue;
                const auto& node=nodes[component.sceneNode];
                std::uint32_t materialPhaseFlags=0u;
                if (component.sceneNode<populationRecipeByNode.size() &&
                    populationRecipeByNode[component.sceneNode]>=0) {
                    materialPhaseFlags=static_cast<std::uint32_t>(
                        polarPopulations.materialPhase12(
                            static_cast<std::size_t>(
                                populationRecipeByNode[component.sceneNode]
                            ),0u
                        )
                    )|PolarMaterialValidFlag;
                }
                instances.push_back({
                    static_cast<std::uint32_t>(component.previousPose),
                    static_cast<std::uint32_t>(component.previousPose>>32),
                    static_cast<std::uint32_t>(component.pose),
                    static_cast<std::uint32_t>(component.pose>>32),
                    node.translation.y,node.scale.x,node.scale.y,node.scale.z,
                    materialPhaseFlags,
                });
            }
            for (const auto& copy:group.visiblePopulationCopies) {
                if (copy.burst) {
                    instances.push_back({
                        static_cast<std::uint32_t>(copy.previousPose),
                        static_cast<std::uint32_t>(copy.previousPose>>32),
                        static_cast<std::uint32_t>(copy.pose),
                        static_cast<std::uint32_t>(copy.pose>>32),
                        copy.burstHeightFactor,
                        copy.burstScaleScalar,1.0f,1.0f,
                        static_cast<std::uint32_t>(copy.glowPhase12)|
                            PolarMaterialValidFlag|
                            (copy.recipeIndex<populationRecipes.size() &&
                                populationRecipes[copy.recipeIndex].growCopies
                                ?PolarGeneratedCopyFlag:0u),
                    });
                } else {
                    instances.push_back({
                        static_cast<std::uint32_t>(copy.previousPose),
                        static_cast<std::uint32_t>(copy.previousPose>>32),
                        static_cast<std::uint32_t>(copy.pose),
                        static_cast<std::uint32_t>(copy.pose>>32),
                        copy.node.translation.y,
                        copy.node.scale.x,copy.node.scale.y,copy.node.scale.z,
                        static_cast<std::uint32_t>(copy.glowPhase12)|
                            PolarMaterialValidFlag|
                            (copy.recipeIndex<populationRecipes.size() &&
                                populationRecipes[copy.recipeIndex].growCopies
                                ?PolarGeneratedCopyFlag:0u),
                    });
                }
            }
            if (instances.empty()) continue;
            const auto& gpu=meshes_[group.mesh];
            const auto& material=scene.materials[group.material];
            const auto& profile=polarProfiles_[group.profile];
            glUniform4fv(uniforms.baseColor,1,material.baseColor.data());
            glUniform1f(uniforms.metallic,material.metallic);
            glUniform1f(uniforms.roughness,material.roughness);
            glUniform3f(uniforms.emissive,
                material.emissive.x,material.emissive.y,material.emissive.z);
            glUniform4f(uniforms.profile,
                profile.rhoMin,profile.rhoMax,profile.logR0,profile.radiusScale);
            const bool burstGroup=group.burstRecipeIndex!=
                std::numeric_limits<std::uint16_t>::max();
            if (burstGroup) {
                const auto recipeIndex=static_cast<std::size_t>(
                    group.burstRecipeIndex
                );
                if (recipeIndex>=populationRecipes.size()) continue;
                const auto& recipe=populationRecipes[recipeIndex];
                const auto* anchor=polarKinematics.componentForSceneNode(
                    recipe.prototypeSceneNode
                );
                if (!anchor || recipe.prototypeSceneNode>=nodes.size()) continue;
                glUniform1i(uniforms.burstMode,1);
                glUniform4ui(
                    uniforms.burstAnchorPose,
                    static_cast<std::uint32_t>(anchor->previousPose),
                    static_cast<std::uint32_t>(anchor->previousPose>>32),
                    static_cast<std::uint32_t>(anchor->pose),
                    static_cast<std::uint32_t>(anchor->pose>>32)
                );
                glUniform4f(
                    uniforms.burstRecipe,
                    nodes[recipe.prototypeSceneNode].translation.y,
                    recipe.parameters[2]-1.0f,recipe.parameters[5],0.0f
                );
                const auto& anchorNode=nodes[recipe.prototypeSceneNode];
                glUniform3f(
                    uniforms.burstScale,
                    anchorNode.scale.x,anchorNode.scale.y,anchorNode.scale.z
                );
            } else {
                glUniform1i(uniforms.burstMode,0);
            }
            const bool glowGroup=group.glowRecipeIndex!=
                std::numeric_limits<std::uint16_t>::max();
            if (glowGroup) {
                const auto recipeIndex=static_cast<std::size_t>(
                    group.glowRecipeIndex
                );
                if (recipeIndex>=populationRecipes.size() ||
                    !populationRecipes[recipeIndex].glow) continue;
                const auto& recipe=populationRecipes[recipeIndex];
                glUniform1i(
                    uniforms.glowMode,recipe.growCopies?3:1
                );
                glUniform3f(
                    uniforms.glowRecipe,recipe.glowCenterRho,
                    recipe.glowInvHalfWidth,recipe.glowStrength
                );
            } else {
                glUniform1i(uniforms.glowMode,0);
            }
            if (lutMode) {
                glActiveTexture(GL_TEXTURE0);
                glBindTexture(GL_TEXTURE_2D,profile.lutTexture);
                glUniform1i(uniforms.lut,0);
                glUniform1i(uniforms.lutSize,profile.lutSize);
            }
            if (material.doubleSided) glDisable(GL_CULL_FACE); else glEnable(GL_CULL_FACE);
            glBindBuffer(GL_ARRAY_BUFFER,gpu.vbo);
            glEnableVertexAttribArray(0);
            glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(Vertex),
                reinterpret_cast<void*>(offsetof(Vertex,position)));
            glEnableVertexAttribArray(1);
            glVertexAttribPointer(1,3,GL_FLOAT,GL_FALSE,sizeof(Vertex),
                reinterpret_cast<void*>(offsetof(Vertex,normal)));
            const auto uploadBytes=static_cast<GLsizeiptr>(
                instances.size()*sizeof(PolarInstance)
            );
            while (glGetError()!=GL_NO_ERROR) {}
            GLenum uploadError=uploadBytes<=group.capacityBytes
                ?GL_NO_ERROR:GL_OUT_OF_MEMORY;
            if (uploadError==GL_NO_ERROR) {
                glBindBuffer(GL_ARRAY_BUFFER,group.instanceBuffer);
                uploadError=glGetError();
            }
            if (uploadError==GL_NO_ERROR) {
                glBufferSubData(GL_ARRAY_BUFFER,0,
                    uploadBytes,instances.data());
                uploadError=glGetError();
            }
            if (uploadError!=GL_NO_ERROR) {
                group.runtimeDisabled=true;
                for (const auto componentIndex:group.componentIndices)
                    if (componentIndex<components.size() &&
                        components[componentIndex].sceneNode<gpuPolarNodeMask_.size())
                        gpuPolarNodeMask_[components[componentIndex].sceneNode]=0u;
                std::uint32_t disabledGenerated=0;
                for (const auto recipeIndex:group.populationRecipeIndices) {
                    if (recipeIndex<gpuPolarRecipeGroup_.size())
                        gpuPolarRecipeGroup_[recipeIndex]=-1;
                    disabledGenerated+=polarPopulations.recipes()[recipeIndex].generatedCount;
                }
                const auto disabledInstances=group.componentIndices.size()+
                    static_cast<std::size_t>(disabledGenerated);
                gpuPolarInstanceCount_-=static_cast<std::uint32_t>(
                    std::min<std::size_t>(gpuPolarInstanceCount_,disabledInstances)
                );
                gpuPolarFallbackCount_=static_cast<std::uint32_t>(
                    components.size()+polarPopulations.generatedCount()
                )-gpuPolarInstanceCount_;
                gpuPolarGeneratedCount_-=std::min(
                    gpuPolarGeneratedCount_,disabledGenerated
                );
                cpuPolarGeneratedCount_=static_cast<std::uint32_t>(
                    polarPopulations.generatedCount()
                )-gpuPolarGeneratedCount_;
                if (!group.uploadFailureLogged) {
                    KC_LOGE("render substrate polar runtime fallback reason=instance_upload_failed profile=%u mesh=%u material=%u instances=%u generated_gpu=%u generated_cpu=%u",
                        static_cast<unsigned>(group.profile),static_cast<unsigned>(group.mesh),
                        static_cast<unsigned>(group.material),static_cast<unsigned>(instances.size()),
                        static_cast<unsigned>(gpuPolarGeneratedCount_),
                        static_cast<unsigned>(cpuPolarGeneratedCount_));
                    group.uploadFailureLogged=true;
                }
                // The ordinary pass already reserved these visible slots. Draw
                // them from authoritative NodeData this frame; subsequent
                // frames see the cleared GPU mask in the ordinary pass.
                glUseProgram(program_);
                glUniform1i(uInstanced_,GL_FALSE);
                for (const auto componentIndex:group.componentIndices) {
                    if (componentIndex>=components.size()) continue;
                    const auto nodeIndex=components[componentIndex].sceneNode;
                    if (nodeIndex>=nodes.size()||
                        nodeIndex>=gpuPolarNodeQueued_.size()||
                        !gpuPolarNodeQueued_[nodeIndex])
                        continue;
                    const auto& fallbackNode=nodes[nodeIndex];
                    if (!fallbackNode.alive||!fallbackNode.active||
                        fallbackNode.meshIndex>=meshes_.size()||
                        fallbackNode.materialIndex>=scene.materials.size()) continue;
                    float fallbackGlow=0.0f;
                    if (nodeIndex<glowRecipeByNode.size() &&
                        glowRecipeByNode[nodeIndex]>=0) {
                        const auto* fallbackComponent=
                            polarKinematics.componentForSceneNode(nodeIndex);
                        if (fallbackComponent) fallbackGlow=cpuGlow(
                            static_cast<std::size_t>(
                                glowRecipeByNode[nodeIndex]
                            ),0u,fallbackComponent->previousPose,
                            fallbackComponent->pose
                        );
                    }
                    PolarPopulations::MaterialCoordinate fallbackMaterial;
                    if (nodeIndex<populationRecipeByNode.size() &&
                        populationRecipeByNode[nodeIndex]>=0) {
                        const auto* fallbackComponent=
                            polarKinematics.componentForSceneNode(nodeIndex);
                        if (fallbackComponent) fallbackMaterial=
                            cpuMaterialCoordinate(
                                static_cast<std::size_t>(
                                    populationRecipeByNode[nodeIndex]
                                ),0u,fallbackComponent->pose
                            );
                    }
                    drawOrdinaryNode(
                        fallbackNode,fallbackGlow,fallbackMaterial
                    );
                }
                for (const auto& copy:group.visiblePopulationCopies) {
                    auto fallbackCopy=copy;
                    polarPopulations.composeCartesian(
                        fallbackCopy,polarKinematics
                    );
                    const auto& fallbackNode=fallbackCopy.node;
                    if (!fallbackNode.alive||!fallbackNode.active||
                        fallbackNode.meshIndex>=meshes_.size()||
                        fallbackNode.materialIndex>=scene.materials.size()) continue;
                    drawOrdinaryNode(
                        fallbackNode,fallbackCopy.glowField,
                        fallbackCopy.materialCoordinate
                    );
                }
                const auto visibleFallbacks=static_cast<std::uint32_t>(
                    group.visiblePopulationCopies.size()
                );
                visibleGeneratedGpu-=std::min(
                    visibleGeneratedGpu,visibleFallbacks
                );
                visibleGeneratedCpu+=visibleFallbacks;
                loggedGeneratedVisible_=std::numeric_limits<std::uint32_t>::max();
                glUseProgram(polarProgram);
                continue;
            }
            glEnableVertexAttribArray(2);
            glVertexAttribIPointer(2,4,GL_UNSIGNED_INT,sizeof(PolarInstance),nullptr);
            glVertexAttribDivisor(2,1);
            glEnableVertexAttribArray(3);
            glVertexAttribPointer(3,4,GL_FLOAT,GL_FALSE,sizeof(PolarInstance),
                reinterpret_cast<void*>(static_cast<std::uintptr_t>(offsetof(PolarInstance,baseY))));
            glVertexAttribDivisor(3,1);
            glEnableVertexAttribArray(4);
            glVertexAttribIPointer(4,1,GL_UNSIGNED_INT,sizeof(PolarInstance),
                reinterpret_cast<void*>(static_cast<std::uintptr_t>(offsetof(PolarInstance,glowPhase12))));
            glVertexAttribDivisor(4,1);
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,gpu.ibo);
            glDrawElementsInstanced(GL_TRIANGLES,gpu.indexCount,GL_UNSIGNED_INT,nullptr,
                static_cast<GLsizei>(instances.size()));
        }
        for (GLuint location=2;location<=4;++location) {
            glVertexAttribDivisor(location,0);
            glDisableVertexAttribArray(location);
        }
        if (lutMode) glBindTexture(GL_TEXTURE_2D,0);
        glUseProgram(program_);
    }
    if (visibleGenerated!=loggedGeneratedVisible_) {
        KC_LOGI("polar population generated_total=%u generated_visible=%u visible_gpu=%u visible_cpu=%u materialized=%u cartesian_composed=%u",
            static_cast<unsigned>(polarPopulations.generatedCount()),
            static_cast<unsigned>(visibleGenerated),
            static_cast<unsigned>(visibleGeneratedGpu),
            static_cast<unsigned>(visibleGeneratedCpu),
            static_cast<unsigned>(polarPopulations.lastMaterializedCount()),
            static_cast<unsigned>(polarPopulations.lastCartesianComposeCount()));
        loggedGeneratedVisible_=visibleGenerated;
    }
    if (drawn<maxNodes && !scatterGroups_.empty()) {
        glUniform1f(uPolarGlowField_,0.0f);
        glUniform4f(uPolarMaterialCoord_,0.0f,0.0f,0.0f,-1.0f);
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
    const bool finalPass=postProcessing||substrate_.bayerEnabled();
    if (finalPass && postProgram_ && colorTexture_) {
        glDisable(GL_DEPTH_TEST);
        glDisable(GL_CULL_FACE);
        glUseProgram(postProgram_);
        glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D,colorTexture_);
        glUniform1i(pColor_,0);
        glUniform1f(pTime_,time);
        glUniform1f(pBloom_,postProcessing?juice.bloom:0.0f);
        glUniform1f(pFlash_,postProcessing?juice.flash:0.0f);
        glUniform1f(pAberration_,postProcessing?juice.aberration:0.0f);
        glUniform1f(pVignette_,postProcessing?juice.vignette:0.0f);
        glUniform1f(pSaturation_,postProcessing?juice.saturation:1.0f);
        glUniform1f(pContrast_,postProcessing?juice.contrast:1.0f);
        glUniform1f(pShock_,postProcessing?juice.shock:0.0f);
        glUniform2f(pShockCenter_,juice.shockX,juice.shockY);
        glUniform1f(pJuicePulse_,postProcessing?juice.pulse:0.0f);
        glUniform1i(pBayerMode_,static_cast<GLint>(substrate_.bayerMode));
        glUniform1i(pBayerLevels_,static_cast<GLint>(substrate_.levels));
        glUniform1f(pBayerStrength_,substrate_.strength);
        glUniform1i(pOutputHeight_,height_);
        glDrawArrays(GL_TRIANGLES,0,3);
        glBindTexture(GL_TEXTURE_2D,0);
        glUseProgram(program_);
    } else {
        glBindFramebuffer(GL_READ_FRAMEBUFFER,framebuffer_);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER,0);
        glBlitFramebuffer(0,0,internalWidth_,internalHeight_,0,0,width_,height_,GL_COLOR_BUFFER_BIT,GL_LINEAR);
    }
    glEnable(GL_DEPTH_TEST);
    gpuTimer_.endFrame();
    const auto timer=gpuTimer_.stats();
    if (
        gpuTimerInitiallySupported_ && !timer.supported &&
        !gpuTimerRuntimeFailureLogged_
    ) {
        KC_LOGI(
            "gpu timer supported=false bits=0 extension=GL_EXT_disjoint_timer_query "
            "nonblocking=true reason=runtime_error"
        );
        gpuTimerRuntimeFailureLogged_=true;
    } else if (
        timer.supported && timer.samples>0u &&
        (loggedGpuTimerSamples_==0u || timer.samples>=loggedGpuTimerSamples_+120u)
    ) {
        KC_LOGI(
            "gpu timer supported=true bits=%u scope=renderer_start samples=%llu total_ms=%.4f "
            "mean_ms=%.4f max_ms=%.4f last_ms=%.4f disjoint=%u pending=%u",
            static_cast<unsigned>(timer.counterBits),
            static_cast<unsigned long long>(timer.samples),timer.totalMilliseconds,
            timer.meanMilliseconds,timer.maximumMilliseconds,timer.lastMilliseconds,
            static_cast<unsigned>(timer.disjointIntervals),
            static_cast<unsigned>(timer.pendingQueries)
        );
        loggedGpuTimerSamples_=timer.samples;
    }
    eglSwapBuffers(display_,surface_);
}

void RendererGles3::shutdown() {
    if (display_!=EGL_NO_DISPLAY) {
        const bool current=context_!=EGL_NO_CONTEXT && surface_!=EGL_NO_SURFACE &&
            eglMakeCurrent(display_,surface_,surface_,context_)==EGL_TRUE;
        if (current) {
            gpuTimer_.shutdown();
            for (auto& mesh:meshes_) {
                if (mesh.vbo) glDeleteBuffers(1,&mesh.vbo);
                if (mesh.ibo) glDeleteBuffers(1,&mesh.ibo);
            }
            for (auto& group:scatterGroups_) {
                if (group.matrixBuffer) glDeleteBuffers(1,&group.matrixBuffer);
            }
            for (auto& group:polarGroups_) {
                if (group.instanceBuffer) glDeleteBuffers(1,&group.instanceBuffer);
            }
            for (auto& profile:polarProfiles_) {
                if (profile.lutTexture) glDeleteTextures(1,&profile.lutTexture);
            }
            if (chronoVideoLutTexture_) glDeleteTextures(1,&chronoVideoLutTexture_);
            destroyFramebuffer();
            if (program_) glDeleteProgram(program_);
            if (polarDirectProgram_) glDeleteProgram(polarDirectProgram_);
            if (polarLutProgram_) glDeleteProgram(polarLutProgram_);
            if (postProgram_) glDeleteProgram(postProgram_);
        } else gpuTimer_.abandon();
        meshes_.clear();
        scatterGroups_.clear();
        polarGroups_.clear();
        polarProfiles_.clear();
        chronoVideoLutTexture_=0;
        framebuffer_=colorTexture_=depthBuffer_=0;
        internalWidth_=internalHeight_=0;
        eglMakeCurrent(display_,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);
        if (context_!=EGL_NO_CONTEXT) eglDestroyContext(display_,context_);
        if (surface_!=EGL_NO_SURFACE) eglDestroySurface(display_,surface_);
        eglTerminate(display_);
    } else {
        gpuTimer_.abandon();
        meshes_.clear();
        scatterGroups_.clear();
        polarGroups_.clear();
        polarProfiles_.clear();
        chronoVideoLutTexture_=0;
    }
    display_=EGL_NO_DISPLAY; surface_=EGL_NO_SURFACE; context_=EGL_NO_CONTEXT;
    config_=nullptr;
    program_=polarDirectProgram_=polarLutProgram_=postProgram_=0;
    chronoVideoLutTexture_=0;
    uViewProjection_=uModel_=uInstanced_=uBaseColor_=-1;
    uMetallic_=uRoughness_=uEmissive_=uCameraPosition_=-1;
    uLightDirection_=uLightColor_=uLightIntensity_=uAmbient_=uPulse_=-1;
    uPolarGlowField_=uPolarMaterialCoord_=uPolarMaterialMode_=-1;
    uPolarMaterialBands_=uPolarMaterialStrength_=-1;
    directPolarUniforms_={}; lutPolarUniforms_={};
    pColor_=pTime_=pBloom_=pFlash_=pAberration_=pVignette_=pSaturation_=pContrast_=-1;
    pShock_=pShockCenter_=pJuicePulse_=-1;
    pBayerMode_=pBayerLevels_=pBayerStrength_=pOutputHeight_=-1;
    gpuPolarNodeMask_.clear();
    gpuPolarRecipeGroup_.clear();
    gpuPolarNodeQueued_.clear();
    substrate_={}; effectivePolarMode_=PolarRenderMode::Cpu;
    polarReason_="asset_absent";
    gpuPolarInstanceCount_=gpuPolarFallbackCount_=0;
    gpuPolarGeneratedCount_=cpuPolarGeneratedCount_=0;
    loggedGeneratedVisible_=std::numeric_limits<std::uint32_t>::max();
    loggedGpuTimerSamples_=0;
    gpuTimerInitiallySupported_=gpuTimerRuntimeFailureLogged_=false;
    width_=height_=internalWidth_=internalHeight_=0;
    currentScale_=0.0f;
    gpuRenderer_.clear();
}

} // namespace kc
