#include "chrono_video_player.hpp"

#include "chrono_runtime_binding.hpp"

#include <EGL/egl.h>
#include <GLES2/gl2ext.h>
#include <android/log.h>
#include <android/native_window_jni.h>
#include <jni.h>
#include <media/NdkMediaExtractor.h>
#include <media/NdkMediaFormat.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <cstring>
#include <stdexcept>
#include <string_view>

#define KC_LOGI(...) __android_log_print(ANDROID_LOG_INFO,"UGTS-KC392",__VA_ARGS__)
#define KC_LOGE(...) __android_log_print(ANDROID_LOG_ERROR,"UGTS-KC392",__VA_ARGS__)

namespace kc {
namespace {

constexpr std::int64_t NoJavaVideoFrame=std::numeric_limits<std::int64_t>::min();
constexpr std::int64_t NoQueuedPts=std::numeric_limits<std::int64_t>::min();

void require(bool condition,const char* message) {
    if (!condition) throw std::runtime_error(message);
}

class JniEnvironment {
public:
    explicit JniEnvironment(ANativeActivity* activity):vm_(activity?activity->vm:nullptr) {
        if (!vm_) throw std::runtime_error("chrono Java VM is unavailable");
        if (vm_->GetEnv(reinterpret_cast<void**>(&env_),JNI_VERSION_1_6)!=JNI_OK) {
            if (vm_->AttachCurrentThread(&env_,nullptr)!=JNI_OK)
                throw std::runtime_error("chrono could not attach the GL thread to Java");
            detach_=true;
        }
    }
    ~JniEnvironment() { if (detach_) vm_->DetachCurrentThread(); }
    JNIEnv* get() const { return env_; }
    void throwIfException(const char* message) const {
        if (!env_->ExceptionCheck()) return;
        env_->ExceptionDescribe();
        env_->ExceptionClear();
        throw std::runtime_error(message);
    }
private:
    JavaVM* vm_=nullptr;
    JNIEnv* env_=nullptr;
    bool detach_=false;
};

bool isVideoMime(const char* mime) {
    return mime && std::string_view(mime).starts_with("video/");
}

} // namespace

const char* chronoVideoRuntimeModeName(ChronoVideoRuntimeMode mode) {
    switch (mode) {
        case ChronoVideoRuntimeMode::Disabled: return "DISABLED";
        case ChronoVideoRuntimeMode::AuthoritativeSourceLut: return "AUTHORITATIVE_SOURCE_LUT";
        case ChronoVideoRuntimeMode::DerivedPolarPreview: return "DERIVED_POLAR_PREVIEW";
        case ChronoVideoRuntimeMode::Failed: return "FAILED_CLOSED";
    }
    return "FAILED_CLOSED";
}

ChronoVideoPlayer::~ChronoVideoPlayer() { shutdown(); }

std::vector<std::uint8_t> ChronoVideoPlayer::readAsset(const char* path) const {
    AAsset* asset=AAssetManager_open(assets_,path,AASSET_MODE_RANDOM);
    if (!asset) return {};
    const auto length=AAsset_getLength64(asset);
    if (length<0 || static_cast<std::uint64_t>(length)>
            static_cast<std::uint64_t>(std::numeric_limits<std::size_t>::max())) {
        AAsset_close(asset);
        throw std::runtime_error(std::string("chrono asset length is invalid: ")+path);
    }
    std::vector<std::uint8_t> result(static_cast<std::size_t>(length));
    std::size_t offset=0;
    while (offset<result.size()) {
        const auto count=AAsset_read(asset,result.data()+offset,result.size()-offset);
        if (count<=0) {
            AAsset_close(asset);
            throw std::runtime_error(std::string("chrono asset read was truncated: ")+path);
        }
        offset+=static_cast<std::size_t>(count);
    }
    AAsset_close(asset);
    return result;
}

bool ChronoVideoPlayer::assetExists(const char* path) const {
    AAsset* asset=AAssetManager_open(assets_,path,AASSET_MODE_UNKNOWN);
    if (!asset) return false;
    AAsset_close(asset);
    return true;
}

void ChronoVideoPlayer::verifyAssetBinding(
    const char* path,const std::vector<std::uint8_t>& bytes
) const {
    if (!chrono_runtime_binding::kPresent) return;
    const auto* binding=chrono_runtime_binding::find(path);
    require(binding!=nullptr,"chrono asset is absent from the generated immutable binding");
    require(binding->bytes==bytes.size(),"chrono asset byte length disagrees with its immutable binding");
    require(chronoSha256(bytes)==binding->sha256,"chrono asset SHA-256 disagrees with its immutable binding");
}

GLuint ChronoVideoPlayer::compile(GLenum type,const std::string& source) const {
    const auto shader=glCreateShader(type);
    const char* text=source.c_str();
    glShaderSource(shader,1,&text,nullptr);
    glCompileShader(shader);
    GLint ok=GL_FALSE;
    glGetShaderiv(shader,GL_COMPILE_STATUS,&ok);
    if (ok) return shader;
    char log[2048]{};
    glGetShaderInfoLog(shader,sizeof(log),nullptr,log);
    KC_LOGE("chrono shader compile failed: %s",log);
    glDeleteShader(shader);
    return 0;
}

GLuint ChronoVideoPlayer::link(GLuint vertex,GLuint fragment,const char* label) const {
    const auto program=glCreateProgram();
    glAttachShader(program,vertex); glAttachShader(program,fragment); glLinkProgram(program);
    GLint ok=GL_FALSE;
    glGetProgramiv(program,GL_LINK_STATUS,&ok);
    if (ok) return program;
    char log[2048]{};
    glGetProgramInfoLog(program,sizeof(log),nullptr,log);
    KC_LOGE("chrono %s program link failed: %s",label,log);
    glDeleteProgram(program);
    return 0;
}

bool ChronoVideoPlayer::createGlResources(
    const ChronoVideoLut& lut,GLuint lutTexture
) {
    const auto readText=[this](const char* path) {
        const auto bytes=readAsset(path);
        return std::string(bytes.begin(),bytes.end());
    };
    const auto vertex=compile(GL_VERTEX_SHADER,readText("shaders/chrono_video.vert"));
    const char* stageFragmentPath=mode_==ChronoVideoRuntimeMode::AuthoritativeSourceLut
        ?"shaders/chrono_video_source.frag":"shaders/chrono_video_preview.frag";
    const auto stageFragment=compile(GL_FRAGMENT_SHADER,readText(stageFragmentPath));
    const auto backgroundFragment=compile(
        GL_FRAGMENT_SHADER,readText("shaders/chrono_video_background.frag"));
    if (!vertex || !stageFragment || !backgroundFragment) {
        if (vertex) glDeleteShader(vertex);
        if (stageFragment) glDeleteShader(stageFragment);
        if (backgroundFragment) glDeleteShader(backgroundFragment);
        return false;
    }
    stageProgram_=link(vertex,stageFragment,"stage");
    backgroundProgram_=link(vertex,backgroundFragment,"background");
    glDeleteShader(vertex); glDeleteShader(stageFragment); glDeleteShader(backgroundFragment);
    if (!stageProgram_ || !backgroundProgram_) return false;

    stageVideoUniform_=glGetUniformLocation(stageProgram_,"uVideo");
    stageTransformUniform_=glGetUniformLocation(stageProgram_,"uSurfaceTransform");
    stageSourceSizeUniform_=glGetUniformLocation(stageProgram_,"uSourceSize");
    stageOutputSizeUniform_=glGetUniformLocation(stageProgram_,"uOutputSize");
    stageLutUniform_=glGetUniformLocation(stageProgram_,"uLut");
    backgroundTextureUniform_=glGetUniformLocation(backgroundProgram_,"uColor");
    require(stageVideoUniform_>=0 && stageTransformUniform_>=0 &&
        stageSourceSizeUniform_>=0 && stageOutputSizeUniform_>=0,
        "chrono staging shader interface mismatch");
    if (mode_==ChronoVideoRuntimeMode::AuthoritativeSourceLut)
        require(stageLutUniform_>=0,"chrono source shader has no UGCVLUT1 binding");
    require(backgroundTextureUniform_>=0,"chrono background shader interface mismatch");

    lutTexture_=lutTexture;
    outputWidth_=mode_==ChronoVideoRuntimeMode::AuthoritativeSourceLut
        ?lut.thetaBins:timeline_.mediaWidth;
    outputHeight_=mode_==ChronoVideoRuntimeMode::AuthoritativeSourceLut
        ?lut.rhoBins:timeline_.mediaHeight;
    require(outputWidth_>0u && outputHeight_>0u,"chrono output dimensions are zero");

    while (glGetError()!=GL_NO_ERROR) {}
    glGenTextures(1,&externalTexture_);
    glBindTexture(GL_TEXTURE_EXTERNAL_OES,externalTexture_);
    glTexParameteri(GL_TEXTURE_EXTERNAL_OES,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
    glTexParameteri(GL_TEXTURE_EXTERNAL_OES,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    glTexParameteri(GL_TEXTURE_EXTERNAL_OES,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_EXTERNAL_OES,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
    glBindTexture(GL_TEXTURE_EXTERNAL_OES,0);

    glGenTextures(static_cast<GLsizei>(stagingTextures_.size()),stagingTextures_.data());
    glGenFramebuffers(
        static_cast<GLsizei>(stagingFramebuffers_.size()),stagingFramebuffers_.data());
    bool complete=true;
    for (std::size_t slot=0;slot<stagingTextures_.size();++slot) {
        glBindTexture(GL_TEXTURE_2D,stagingTextures_[slot]);
        glTexImage2D(
            GL_TEXTURE_2D,0,GL_RGBA8,static_cast<GLsizei>(outputWidth_),
            static_cast<GLsizei>(outputHeight_),0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
        glBindFramebuffer(GL_FRAMEBUFFER,stagingFramebuffers_[slot]);
        glFramebufferTexture2D(
            GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,stagingTextures_[slot],0);
        complete=complete &&
            glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE;
    }
    const auto error=glGetError();
    glBindFramebuffer(GL_FRAMEBUFFER,0);
    glBindTexture(GL_TEXTURE_2D,0);
    if (!externalTexture_ || !stagingTextures_[0] || !stagingTextures_[1] ||
            !stagingFramebuffers_[0] || !stagingFramebuffers_[1] ||
            !complete || error!=GL_NO_ERROR) {
        KC_LOGE("chrono GL resource creation failed: complete=%s error=0x%x",
            complete?"true":"false",error);
        return false;
    }
    KC_LOGI("chrono owned staging rasters=2 size=%ux%u format=RGBA8 "
        "prefetch=exactly_one_verified_ordinal external_filter=NEAREST",
        outputWidth_,outputHeight_);
    return true;
}

bool ChronoVideoPlayer::createDecoderSurface() {
    JniEnvironment attached(activity_);
    JNIEnv* env=attached.get();
    const auto activityClass=env->GetObjectClass(activity_->clazz);
    require(activityClass!=nullptr,"chrono activity class is unavailable");
    const auto create=env->GetMethodID(
        activityClass,"createVideoSurface","(I)Landroid/view/Surface;");
    require(create!=nullptr,"chrono activity does not expose createVideoSurface");
    const auto surface=env->CallObjectMethod(
        activity_->clazz,create,static_cast<jint>(externalTexture_));
    attached.throwIfException("chrono createVideoSurface failed");
    require(surface!=nullptr,"chrono Java decoder surface is null");
    decoderWindow_=ANativeWindow_fromSurface(env,surface);
    env->DeleteLocalRef(surface);
    env->DeleteLocalRef(activityClass);
    require(decoderWindow_!=nullptr,"chrono could not obtain an ANativeWindow for the decoder");
    return true;
}

bool ChronoVideoPlayer::openDecoder() {
    AAsset* mediaAsset=AAssetManager_open(
        assets_,mediaAssetPath_.c_str(),AASSET_MODE_RANDOM);
    require(mediaAsset!=nullptr,"chrono media asset disappeared after verification");
    off64_t start=0,length=0;
    mediaFileDescriptor_=AAsset_openFileDescriptor64(mediaAsset,&start,&length);
    AAsset_close(mediaAsset);
    require(mediaFileDescriptor_>=0,
        "chrono MP4 is compressed in the APK; androidResources.noCompress mp4 is required");

    extractor_=AMediaExtractor_new();
    require(extractor_!=nullptr,"chrono could not allocate AMediaExtractor");
    require(AMediaExtractor_setDataSourceFd(
        extractor_,mediaFileDescriptor_,start,length)==AMEDIA_OK,
        "chrono AMediaExtractor rejected the MP4 asset range");

    AMediaFormat* videoFormat=nullptr;
    std::string mime;
    for (std::size_t track=0;track<AMediaExtractor_getTrackCount(extractor_);++track) {
        auto* format=AMediaExtractor_getTrackFormat(extractor_,track);
        const char* candidate=nullptr;
        if (format && AMediaFormat_getString(format,AMEDIAFORMAT_KEY_MIME,&candidate) &&
                isVideoMime(candidate)) {
            require(AMediaExtractor_selectTrack(extractor_,track)==AMEDIA_OK,
                "chrono could not select the video track");
            videoFormat=format;
            mime=candidate;
            break;
        }
        if (format) AMediaFormat_delete(format);
    }
    require(videoFormat!=nullptr,"chrono MP4 has no decodable video track");
    std::int32_t width=0,height=0;
    require(AMediaFormat_getInt32(videoFormat,AMEDIAFORMAT_KEY_WIDTH,&width) &&
        AMediaFormat_getInt32(videoFormat,AMEDIAFORMAT_KEY_HEIGHT,&height),
        "chrono video track has no dimensions");
    require(width==static_cast<std::int32_t>(timeline_.mediaWidth) &&
        height==static_cast<std::int32_t>(timeline_.mediaHeight),
        "chrono video dimensions disagree with UGCVPTS1");

    codec_=AMediaCodec_createDecoderByType(mime.c_str());
    require(codec_!=nullptr,"chrono could not create a MediaCodec decoder");
    const auto configured=AMediaCodec_configure(
        codec_,videoFormat,decoderWindow_,nullptr,0u)==AMEDIA_OK;
    AMediaFormat_delete(videoFormat);
    require(configured,"chrono MediaCodec configuration failed");
    require(AMediaCodec_start(codec_)==AMEDIA_OK,"chrono MediaCodec start failed");
    queuedPresentationTimesUs_.assign(timeline_.entries.size(),NoQueuedPts);
    mediaBytes_.clear(); mediaBytes_.shrink_to_fit();
    KC_LOGI(
        "chrono decoder initialized mode=%s mime=%s media=%ux%u entries=%zu "
        "clock=UGCVPTS1_half_open output_gate=one_SurfaceTexture_frame",
        chronoVideoRuntimeModeName(mode_),mime.c_str(),timeline_.mediaWidth,
        timeline_.mediaHeight,timeline_.entries.size());
    return true;
}

bool ChronoVideoPlayer::initialize(
    ANativeActivity* activity,AAssetManager* assets,
    const ChronoVideoLut& lut,GLuint lutTexture
) {
    shutdown();
    activity_=activity; assets_=assets;
    if (!activity_ || !assets_) return false;
    try {
        constexpr const char* sourceTimeline="chrono/source_timeline.ugcvpts1";
        constexpr const char* sourceMedia="chrono/source_media.mp4";
        constexpr const char* previewTimeline="chrono/preview_timeline.ugcvpts1";
        constexpr const char* previewMedia="chrono/polar_preview.mp4";
        const bool sourceTimelineDeclared=assetExists(sourceTimeline) ||
            (chrono_runtime_binding::kPresent && chrono_runtime_binding::find(sourceTimeline));
        const bool sourceMediaDeclared=assetExists(sourceMedia) ||
            (chrono_runtime_binding::kPresent && chrono_runtime_binding::find(sourceMedia));
        if (sourceTimelineDeclared || sourceMediaDeclared) {
            require(sourceTimelineDeclared && sourceMediaDeclared,
                "declared AUTHORITATIVE_SOURCE_LUT asset set is incomplete");
            mode_=ChronoVideoRuntimeMode::AuthoritativeSourceLut;
            timelineAssetPath_=sourceTimeline;
            mediaAssetPath_=sourceMedia;
        } else {
            const bool previewTimelineDeclared=assetExists(previewTimeline) ||
                (chrono_runtime_binding::kPresent && chrono_runtime_binding::find(previewTimeline));
            const bool previewMediaDeclared=assetExists(previewMedia) ||
                (chrono_runtime_binding::kPresent && chrono_runtime_binding::find(previewMedia));
            if (!previewTimelineDeclared && !previewMediaDeclared) {
                mode_=ChronoVideoRuntimeMode::Disabled;
                KC_LOGI("chrono runtime mode=DISABLED reason=no_UGCVPTS1_media_pair");
                return true;
            }
            require(previewTimelineDeclared && previewMediaDeclared,
                "declared DERIVED_POLAR_PREVIEW asset set is incomplete");
            mode_=ChronoVideoRuntimeMode::DerivedPolarPreview;
            timelineAssetPath_=previewTimeline;
            mediaAssetPath_=previewMedia;
        }

        const auto timelineBytes=readAsset(timelineAssetPath_.c_str());
        require(!timelineBytes.empty(),"declared UGCVPTS1 asset cannot be read");
        verifyAssetBinding(timelineAssetPath_.c_str(),timelineBytes);
        timeline_.load(timelineBytes);
        mediaBytes_=readAsset(mediaAssetPath_.c_str());
        require(!mediaBytes_.empty(),"declared chrono MP4 asset cannot be read");
        verifyAssetBinding(mediaAssetPath_.c_str(),mediaBytes_);
        const auto actualMediaSha=chronoSha256(mediaBytes_);
        require(actualMediaSha==timeline_.mediaSha256,
            "chrono MP4 SHA-256 disagrees with UGCVPTS1");

        if (mode_==ChronoVideoRuntimeMode::AuthoritativeSourceLut) {
            require(timeline_.originalSource() && timeline_.applyLut() &&
                !timeline_.derivedPreview() && !timeline_.alreadyLogPolar(),
                "source timeline does not declare AUTHORITATIVE_SOURCE_LUT");
            require(actualMediaSha==timeline_.sourceSha256,
                "source MP4 SHA-256 disagrees with UGCVPTS1 source authority");
            require(lut.present && lutTexture!=0u,"source mode requires a verified UGCVLUT1 texture");
            require(timeline_.mediaWidth==lut.sourceWidth &&
                timeline_.mediaHeight==lut.sourceHeight,
                "source media dimensions disagree with UGCVLUT1");
            const auto lutBytes=readAsset("chrono/polar_lut.ugcv1");
            require(!lutBytes.empty(),"source mode UGCVLUT1 asset cannot be read");
            verifyAssetBinding("chrono/polar_lut.ugcv1",lutBytes);
            // Fail initialization, rather than discovering a lossy time-clock
            // conversion only after playback has already begun.
            for (const auto& entry:timeline_.entries)
                static_cast<void>(timeline_.exactMediaTimeUs(entry.sourcePts));
        } else {
            require(timeline_.derivedPreview() && timeline_.alreadyLogPolar() &&
                !timeline_.originalSource() && !timeline_.applyLut(),
                "preview timeline does not declare DERIVED_POLAR_PREVIEW");
        }
        require(createGlResources(lut,lutTexture),"chrono GLES staging initialization failed");
        require(createDecoderSurface(),"chrono SurfaceTexture initialization failed");
        require(openDecoder(),"chrono decoder initialization failed");
        KC_LOGI(
            "chrono runtime mode=%s playback=%s authority=%s LUT_reapplication=%s "
            "orientation=canonical_top_left_to_GL_then_SurfaceTexture_matrix "
            "color=device_MediaCodec_YUV_to_RGB_not_byte_authoritative",
            chronoVideoRuntimeModeName(mode_),timeline_.loop()?"LOOP_EXPLICIT":"ONCE_HOLD_LAST",
            mode_==ChronoVideoRuntimeMode::AuthoritativeSourceLut?"source_observation":"derived_preview",
            mode_==ChronoVideoRuntimeMode::AuthoritativeSourceLut?"Q8_EXACT_ADDRESS_MATH":"FORBIDDEN");
        return true;
    } catch (const std::exception& error) {
        KC_LOGE(
            "chrono initialization failed closed mode=%s reason=%s; preview_promotion=false",
            chronoVideoRuntimeModeName(mode_),error.what());
        shutdown();
        mode_=ChronoVideoRuntimeMode::Failed;
        return false;
    }
}

void ChronoVideoPlayer::closeDecoder() {
    if (heldOutput_.valid && codec_)
        static_cast<void>(AMediaCodec_releaseOutputBuffer(codec_,heldOutput_.codecIndex,false));
    heldOutput_={};
    if (codec_) {
        static_cast<void>(AMediaCodec_stop(codec_));
        AMediaCodec_delete(codec_);
        codec_=nullptr;
    }
    if (extractor_) {
        AMediaExtractor_delete(extractor_);
        extractor_=nullptr;
    }
    if (mediaFileDescriptor_>=0) {
        close(mediaFileDescriptor_);
        mediaFileDescriptor_=-1;
    }
    if (decoderWindow_) {
        ANativeWindow_release(decoderWindow_);
        decoderWindow_=nullptr;
    }
    if (activity_) {
        try {
            JniEnvironment attached(activity_);
            JNIEnv* env=attached.get();
            const auto activityClass=env->GetObjectClass(activity_->clazz);
            if (activityClass) {
                const auto release=env->GetMethodID(activityClass,"releaseVideoSurface","()V");
                if (release) env->CallVoidMethod(activity_->clazz,release);
                env->DeleteLocalRef(activityClass);
                attached.throwIfException("chrono releaseVideoSurface failed");
            }
        } catch (const std::exception& error) {
            KC_LOGE("chrono Java surface release error: %s",error.what());
        }
    }
    surfaceFrameAwaited_=false;
}

void ChronoVideoPlayer::shutdown() {
    const auto previousMode=mode_;
    closeDecoder();
    if (eglGetCurrentContext()!=EGL_NO_CONTEXT) {
        glDeleteFramebuffers(
            static_cast<GLsizei>(stagingFramebuffers_.size()),stagingFramebuffers_.data());
        glDeleteTextures(
            static_cast<GLsizei>(stagingTextures_.size()),stagingTextures_.data());
        if (externalTexture_) glDeleteTextures(1,&externalTexture_);
        if (stageProgram_) glDeleteProgram(stageProgram_);
        if (backgroundProgram_) glDeleteProgram(backgroundProgram_);
    }
    stagingFramebuffers_.fill(0u); stagingTextures_.fill(0u); externalTexture_=0;
    stageProgram_=backgroundProgram_=0;
    lutTexture_=0;
    activity_=nullptr; assets_=nullptr;
    timeline_={}; timelineAssetPath_.clear(); mediaAssetPath_.clear(); mediaBytes_.clear();
    queuedPresentationTimesUs_.clear();
    inputOrdinal_=outputOrdinal_=0;
    inputEos_=outputEos_=false;
    focused_=playbackClockStarted_=false;
    loopResetPending_=false;
    stagedFrameCount_=decoderCatchupDropCount_=decoderLoopCount_=0;
    lateBoundaryCount_=0;
    stagedOrdinal_=std::numeric_limits<std::size_t>::max();
    stagingOrdinals_.fill(std::numeric_limits<std::size_t>::max());
    publishedSlot_=-1;
    lastLateTarget_=std::numeric_limits<std::size_t>::max();
    previousLoopCycle_=0u;
    havePreviousLoopCycle_=false;
    mode_=ChronoVideoRuntimeMode::Disabled;
    if (previousMode!=ChronoVideoRuntimeMode::Disabled)
        KC_LOGI("chrono runtime shutdown previous_mode=%s",chronoVideoRuntimeModeName(previousMode));
}

void ChronoVideoPlayer::setFocused(bool focused,std::int64_t steadyNowNanoseconds) {
    if (!active() || focused_==focused) return;
    focused_=focused;
    if (focused_) {
        if (playbackClockStarted_ && pauseStartNs_>0 && steadyNowNanoseconds>pauseStartNs_) {
            playbackStartNs_+=steadyNowNanoseconds-pauseStartNs_;
        }
        pauseStartNs_=0;
    } else if (playbackClockStarted_) pauseStartNs_=steadyNowNanoseconds;
    KC_LOGI("chrono focus=%s playback_clock=%s",
        focused_?"gained":"lost",focused_?"running":"paused");
}

std::uint64_t ChronoVideoPlayer::elapsedNanoseconds(
    std::int64_t steadyNowNanoseconds
) const {
    if (!playbackClockStarted_ || steadyNowNanoseconds<=playbackStartNs_) return 0u;
    return static_cast<std::uint64_t>(steadyNowNanoseconds-playbackStartNs_);
}

bool ChronoVideoPlayer::consumeSurfaceFrame() {
    if (!surfaceFrameAwaited_) return false;
    JniEnvironment attached(activity_);
    JNIEnv* env=attached.get();
    const auto activityClass=env->GetObjectClass(activity_->clazz);
    require(activityClass!=nullptr,"chrono activity class vanished");
    const auto consume=env->GetMethodID(activityClass,"consumeVideoFrame","([F)J");
    require(consume!=nullptr,"chrono activity does not expose consumeVideoFrame");
    const auto matrix=env->NewFloatArray(16);
    require(matrix!=nullptr,"chrono could not allocate SurfaceTexture transform array");
    const auto timestamp=env->CallLongMethod(activity_->clazz,consume,matrix);
    attached.throwIfException("chrono updateTexImage failed on the GL thread");
    if (timestamp==NoJavaVideoFrame) {
        env->DeleteLocalRef(matrix);
        env->DeleteLocalRef(activityClass);
        return false;
    }
    std::array<float,16> transform{};
    env->GetFloatArrayRegion(matrix,0,16,transform.data());
    attached.throwIfException("chrono could not read the SurfaceTexture transform");
    env->DeleteLocalRef(matrix);
    env->DeleteLocalRef(activityClass);
    surfaceFrameAwaited_=false;
    lastSurfaceTimestampNs_=timestamp;
    const int slot=freeStagingSlot();
    require(slot>=0,"chrono decoded frame arrived without a free owned staging slot");
    stageExternalFrame(transform,slot);
    stagingOrdinals_[static_cast<std::size_t>(slot)]=releasedOrdinal_;
    stagedOrdinal_=releasedOrdinal_;
    ++stagedFrameCount_;
    if (stagedFrameCount_==1u || (stagedFrameCount_%60u)==0u) {
        const auto& entry=timeline_.entries[stagedOrdinal_];
        KC_LOGI(
            "chrono staged frame count=%llu media_ordinal=%zu source_frame=%u "
            "source_pts=%lld surface_timestamp_ns=%lld mode=%s",
            static_cast<unsigned long long>(stagedFrameCount_),stagedOrdinal_,
            entry.sourceFrameIndex,static_cast<long long>(entry.sourcePts),
            static_cast<long long>(lastSurfaceTimestampNs_),chronoVideoRuntimeModeName(mode_));
    }
    return true;
}

int ChronoVideoPlayer::slotForOrdinal(std::size_t ordinal) const {
    for (std::size_t slot=0;slot<stagingOrdinals_.size();++slot)
        if (stagingOrdinals_[slot]==ordinal) return static_cast<int>(slot);
    return -1;
}

int ChronoVideoPlayer::freeStagingSlot() const {
    const auto empty=std::numeric_limits<std::size_t>::max();
    for (std::size_t slot=0;slot<stagingOrdinals_.size();++slot) {
        if (static_cast<int>(slot)!=publishedSlot_ && stagingOrdinals_[slot]==empty)
            return static_cast<int>(slot);
    }
    return -1;
}

bool ChronoVideoPlayer::publishForTarget(std::size_t targetOrdinal) {
    const int exact=slotForOrdinal(targetOrdinal);
    if (exact>=0) {
        if (publishedSlot_!=exact) {
            const int previous=publishedSlot_;
            publishedSlot_=exact;
            if (previous>=0 && previous!=exact)
                stagingOrdinals_[static_cast<std::size_t>(previous)]=
                    std::numeric_limits<std::size_t>::max();
            KC_LOGI("chrono half-open publish target=%zu slot=%d previous_slot=%d",
                targetOrdinal,publishedSlot_,previous);
        }
        lastLateTarget_=std::numeric_limits<std::size_t>::max();
        return true;
    }
    // A stall may jump over the one prefetched ordinal. It is observation data,
    // but no longer the selected display interval, so free only the unpublished
    // slot and decode the exact current target next.
    for (std::size_t slot=0;slot<stagingOrdinals_.size();++slot) {
        if (static_cast<int>(slot)!=publishedSlot_ &&
                stagingOrdinals_[slot]!=std::numeric_limits<std::size_t>::max() &&
                stagingOrdinals_[slot]<targetOrdinal)
            stagingOrdinals_[slot]=std::numeric_limits<std::size_t>::max();
    }
    if (lastLateTarget_!=targetOrdinal) {
        lastLateTarget_=targetOrdinal;
        ++lateBoundaryCount_;
        const auto publishedOrdinal=publishedSlot_>=0
            ?stagingOrdinals_[static_cast<std::size_t>(publishedSlot_)]
            :std::numeric_limits<std::size_t>::max();
        KC_LOGE("chrono late half-open boundary count=%llu target=%zu published=%zu "
            "physical_exact_timing=false",
            static_cast<unsigned long long>(lateBoundaryCount_),targetOrdinal,publishedOrdinal);
    }
    return false;
}

std::size_t ChronoVideoPlayer::desiredDecodeOrdinal(std::size_t targetOrdinal) const {
    if (slotForOrdinal(targetOrdinal)<0) return targetOrdinal;
    if (targetOrdinal+1u<timeline_.entries.size() &&
            slotForOrdinal(targetOrdinal+1u)<0)
        return targetOrdinal+1u;
    return timeline_.entries.size();
}

void ChronoVideoPlayer::stageExternalFrame(
    const std::array<float,16>& transform,int slot
) {
    require(slot>=0 && slot<static_cast<int>(stagingFramebuffers_.size()),
        "chrono staging slot is out of range");
    const GLboolean depthWasEnabled=glIsEnabled(GL_DEPTH_TEST);
    const GLboolean cullWasEnabled=glIsEnabled(GL_CULL_FACE);
    const GLboolean blendWasEnabled=glIsEnabled(GL_BLEND);
    const GLboolean ditherWasEnabled=glIsEnabled(GL_DITHER);
    while (glGetError()!=GL_NO_ERROR) {}
    glBindFramebuffer(
        GL_FRAMEBUFFER,stagingFramebuffers_[static_cast<std::size_t>(slot)]);
    glViewport(0,0,static_cast<GLsizei>(outputWidth_),static_cast<GLsizei>(outputHeight_));
    glDisable(GL_DEPTH_TEST); glDisable(GL_CULL_FACE);
    glDisable(GL_BLEND); glDisable(GL_DITHER);
    glUseProgram(stageProgram_);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_EXTERNAL_OES,externalTexture_);
    glUniform1i(stageVideoUniform_,0);
    glUniformMatrix4fv(stageTransformUniform_,1,GL_FALSE,transform.data());
    glUniform2i(stageSourceSizeUniform_,
        static_cast<GLint>(timeline_.mediaWidth),static_cast<GLint>(timeline_.mediaHeight));
    glUniform2i(stageOutputSizeUniform_,
        static_cast<GLint>(outputWidth_),static_cast<GLint>(outputHeight_));
    if (mode_==ChronoVideoRuntimeMode::AuthoritativeSourceLut) {
        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_2D,lutTexture_);
        glUniform1i(stageLutUniform_,1);
    }
    glDrawArrays(GL_TRIANGLES,0,3);
    const auto error=glGetError();
    glActiveTexture(GL_TEXTURE1); glBindTexture(GL_TEXTURE_2D,0);
    glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_EXTERNAL_OES,0);
    glBindFramebuffer(GL_FRAMEBUFFER,0);
    if (depthWasEnabled) glEnable(GL_DEPTH_TEST); else glDisable(GL_DEPTH_TEST);
    if (cullWasEnabled) glEnable(GL_CULL_FACE); else glDisable(GL_CULL_FACE);
    if (blendWasEnabled) glEnable(GL_BLEND); else glDisable(GL_BLEND);
    if (ditherWasEnabled) glEnable(GL_DITHER); else glDisable(GL_DITHER);
    if (error!=GL_NO_ERROR)
        throw std::runtime_error("chrono external-to-owned-texture staging produced a GL error");
}

void ChronoVideoPlayer::feedDecoder() {
    if (inputEos_ || !codec_ || !extractor_) return;
    for (int attempt=0;attempt<8 && !inputEos_;++attempt) {
        const auto inputIndex=AMediaCodec_dequeueInputBuffer(codec_,0);
        if (inputIndex==AMEDIACODEC_INFO_TRY_AGAIN_LATER) return;
        require(inputIndex>=0,"chrono MediaCodec input dequeue failed");
        std::size_t capacity=0;
        auto* buffer=AMediaCodec_getInputBuffer(
            codec_,static_cast<std::size_t>(inputIndex),&capacity);
        require(buffer!=nullptr,"chrono MediaCodec returned a null input buffer");
        const auto sampleTrack=AMediaExtractor_getSampleTrackIndex(extractor_);
        if (sampleTrack<0) {
            require(inputOrdinal_==timeline_.entries.size(),
                "chrono MP4 ended before all UGCVPTS1 ordinals were decoded");
            require(AMediaCodec_queueInputBuffer(
                codec_,static_cast<std::size_t>(inputIndex),0u,0u,0u,
                AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM)==AMEDIA_OK,
                "chrono could not queue decoder EOS");
            inputEos_=true;
            KC_LOGI("chrono decoder input EOS ordinals=%zu",inputOrdinal_);
            return;
        }
        require(inputOrdinal_<timeline_.entries.size(),
            "chrono MP4 contains more frames than UGCVPTS1");
        const auto sampleTimeUs=AMediaExtractor_getSampleTime(extractor_);
        require(sampleTimeUs>=0,"chrono extractor returned a negative sample PTS");
        std::int64_t queuedTimeUs=sampleTimeUs;
        if (mode_==ChronoVideoRuntimeMode::AuthoritativeSourceLut) {
            const auto expected=timeline_.exactMediaTimeUs(
                timeline_.entries[inputOrdinal_].sourcePts);
            require(sampleTimeUs==expected,
                "source MP4 sample PTS disagrees with exact UGCVPTS1 ordinal PTS");
            queuedTimeUs=expected;
        } else {
            require(inputOrdinal_==0u || sampleTimeUs>lastPreviewInputPtsUs_,
                "preview MP4 sample PTS is not strictly increasing");
            lastPreviewInputPtsUs_=sampleTimeUs;
        }
        const auto sampleSize=AMediaExtractor_readSampleData(extractor_,buffer,capacity);
        require(sampleSize>=0,"chrono extractor could not read a declared video sample");
        queuedPresentationTimesUs_[inputOrdinal_]=queuedTimeUs;
        require(AMediaCodec_queueInputBuffer(
            codec_,static_cast<std::size_t>(inputIndex),0u,
            static_cast<std::size_t>(sampleSize),static_cast<std::uint64_t>(queuedTimeUs),0u
        )==AMEDIA_OK,"chrono MediaCodec rejected an input sample");
        ++inputOrdinal_;
        static_cast<void>(AMediaExtractor_advance(extractor_));
    }
}

bool ChronoVideoPlayer::validateOutputFormat() {
    auto* format=AMediaCodec_getOutputFormat(codec_);
    if (!format) return false;
    std::int32_t width=0,height=0;
    const bool valid=AMediaFormat_getInt32(format,AMEDIAFORMAT_KEY_WIDTH,&width) &&
        AMediaFormat_getInt32(format,AMEDIAFORMAT_KEY_HEIGHT,&height) &&
        width==static_cast<std::int32_t>(timeline_.mediaWidth) &&
        height==static_cast<std::int32_t>(timeline_.mediaHeight);
    KC_LOGI("chrono decoder output format width=%d height=%d expected=%ux%u valid=%s",
        width,height,timeline_.mediaWidth,timeline_.mediaHeight,valid?"true":"false");
    AMediaFormat_delete(format);
    return valid;
}

void ChronoVideoPlayer::releaseHeldOutput(std::size_t desiredOrdinal) {
    if (!heldOutput_.valid || surfaceFrameAwaited_ || heldOutput_.ordinal>desiredOrdinal) return;
    if (heldOutput_.ordinal==desiredOrdinal &&
            desiredOrdinal<timeline_.entries.size() && freeStagingSlot()<0)
        return;
    const auto held=heldOutput_;
    heldOutput_={};
    ++outputOrdinal_;
    if (held.ordinal<desiredOrdinal || desiredOrdinal>=timeline_.entries.size()) {
        require(AMediaCodec_releaseOutputBuffer(codec_,held.codecIndex,false)==AMEDIA_OK,
            "chrono MediaCodec could not discard a stale decoded output");
        ++decoderCatchupDropCount_;
        if (decoderCatchupDropCount_==1u || (decoderCatchupDropCount_%60u)==0u)
            KC_LOGI("chrono presentation catchup discarded=%llu last_ordinal=%zu target=%zu",
                static_cast<unsigned long long>(decoderCatchupDropCount_),held.ordinal,desiredOrdinal);
    } else {
        require(AMediaCodec_releaseOutputBuffer(codec_,held.codecIndex,true)==AMEDIA_OK,
            "chrono MediaCodec could not release an output to SurfaceTexture");
        surfaceFrameAwaited_=true;
        releasedOrdinal_=held.ordinal;
    }
    if ((held.flags&AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM)!=0u) {
        outputEos_=true;
        KC_LOGI("chrono decoder output EOS accompanied final ordinal=%zu",held.ordinal);
    }
}

void ChronoVideoPlayer::dequeueDecoder(std::size_t desiredOrdinal) {
    releaseHeldOutput(desiredOrdinal);
    if (heldOutput_.valid || surfaceFrameAwaited_ || outputEos_) return;
    for (int attempt=0;attempt<8;++attempt) {
        AMediaCodecBufferInfo info{};
        const auto outputIndex=AMediaCodec_dequeueOutputBuffer(codec_,&info,0);
        if (outputIndex==AMEDIACODEC_INFO_TRY_AGAIN_LATER) return;
        if (outputIndex==AMEDIACODEC_INFO_OUTPUT_FORMAT_CHANGED) {
            require(validateOutputFormat(),"chrono decoder output format disagrees with UGCVPTS1");
            continue;
        }
        if (outputIndex==AMEDIACODEC_INFO_OUTPUT_BUFFERS_CHANGED) continue;
        require(outputIndex>=0,"chrono MediaCodec output dequeue failed");
        if ((info.flags&AMEDIACODEC_BUFFER_FLAG_CODEC_CONFIG)!=0u) {
            require(AMediaCodec_releaseOutputBuffer(
                codec_,static_cast<std::size_t>(outputIndex),false)==AMEDIA_OK,
                "chrono could not release codec configuration output");
            continue;
        }
        if (outputOrdinal_>=timeline_.entries.size()) {
            require((info.flags&AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM)!=0u,
                "chrono decoder produced more frame ordinals than UGCVPTS1");
            require(AMediaCodec_releaseOutputBuffer(
                codec_,static_cast<std::size_t>(outputIndex),false)==AMEDIA_OK,
                "chrono could not release terminal decoder output");
            outputEos_=true;
            KC_LOGI("chrono decoder output EOS validated_frames=%zu",outputOrdinal_);
            return;
        }
        const auto expected=queuedPresentationTimesUs_[outputOrdinal_];
        require(expected!=NoQueuedPts,"chrono decoder produced output before its ordinal was queued");
        require(info.presentationTimeUs==expected,
            mode_==ChronoVideoRuntimeMode::AuthoritativeSourceLut
                ?"source decoder output PTS disagrees with exact UGCVPTS1 PTS"
                :"preview decoder output PTS disagrees with its queued diagnostic media PTS");
        heldOutput_={
            true,static_cast<std::size_t>(outputIndex),info.presentationTimeUs,
            info.flags,outputOrdinal_
        };
        releaseHeldOutput(desiredOrdinal);
        if (heldOutput_.valid || surfaceFrameAwaited_ || outputEos_) return;
    }
}

void ChronoVideoPlayer::resetForLoop() {
    require(timeline_.loop(),"chrono decoder loop reset requested for ONCE_HOLD_LAST");
    require(!surfaceFrameAwaited_,"chrono loop reset attempted before SurfaceTexture consumption");
    if (heldOutput_.valid) {
        static_cast<void>(AMediaCodec_releaseOutputBuffer(
            codec_,heldOutput_.codecIndex,false));
        heldOutput_={};
    }
    require(AMediaCodec_flush(codec_)==AMEDIA_OK,"chrono MediaCodec flush failed at loop boundary");
    const auto seekTimeUs=mode_==ChronoVideoRuntimeMode::AuthoritativeSourceLut
        ?timeline_.exactMediaTimeUs(timeline_.firstSourcePts):0;
    require(AMediaExtractor_seekTo(
        extractor_,seekTimeUs,
        AMEDIAEXTRACTOR_SEEK_CLOSEST_SYNC)==AMEDIA_OK,
        "chrono extractor seek failed at loop boundary");
    inputOrdinal_=outputOrdinal_=0u;
    inputEos_=outputEos_=false;
    lastPreviewInputPtsUs_=-1;
    std::fill(queuedPresentationTimesUs_.begin(),queuedPresentationTimesUs_.end(),NoQueuedPts);
    loopResetPending_=false;
    ++decoderLoopCount_;
    KC_LOGI("chrono explicit integer loop reset count=%llu",
        static_cast<unsigned long long>(decoderLoopCount_));
}

void ChronoVideoPlayer::fail(const char* message) {
    if (mode_==ChronoVideoRuntimeMode::Failed) return;
    KC_LOGE("chrono runtime failed closed mode=%s reason=%s preview_promotion=false",
        chronoVideoRuntimeModeName(mode_),message);
    mode_=ChronoVideoRuntimeMode::Failed;
    closeDecoder();
}

void ChronoVideoPlayer::updateAndStage(std::int64_t steadyNowNanoseconds) {
    if (!active() || !focused_) return;
    try {
        static_cast<void>(consumeSurfaceFrame());
        if (!playbackClockStarted_) {
            // Decode and stage ordinal zero before starting the source clock.
            // Startup latency therefore cannot erase its first half-open
            // observation interval.
            if (slotForOrdinal(0u)<0) {
                feedDecoder();
                dequeueDecoder(0u);
                return;
            }
            require(publishForTarget(0u),"chrono could not publish primed ordinal zero");
            playbackStartNs_=steadyNowNanoseconds;
            playbackClockStarted_=true;
            KC_LOGI("chrono exact playback clock anchored after staged ordinal zero");
        }
        const auto elapsed=elapsedNanoseconds(steadyNowNanoseconds);
        const auto target=timeline_.selectForElapsedNanoseconds(elapsed);
        const auto loopCycle=timeline_.completedCyclesForElapsedNanoseconds(elapsed);
        if (timeline_.loop() && havePreviousLoopCycle_ && loopCycle>previousLoopCycle_) {
            loopResetPending_=true;
            KC_LOGI("chrono loop cycle advanced previous=%llu current=%llu",
                static_cast<unsigned long long>(previousLoopCycle_),
                static_cast<unsigned long long>(loopCycle));
        }
        previousLoopCycle_=loopCycle;
        havePreviousLoopCycle_=true;
        if (loopResetPending_) {
            if (surfaceFrameAwaited_) return;
            resetForLoop();
            for (std::size_t slot=0;slot<stagingOrdinals_.size();++slot)
                if (static_cast<int>(slot)!=publishedSlot_)
                    stagingOrdinals_[slot]=std::numeric_limits<std::size_t>::max();
        }
        static_cast<void>(publishForTarget(target));
        const auto desired=desiredDecodeOrdinal(target);
        feedDecoder();
        if (desired<timeline_.entries.size() || outputOrdinal_>=timeline_.entries.size())
            dequeueDecoder(desired);
    } catch (const std::exception& error) {
        fail(error.what());
    }
}

void ChronoVideoPlayer::drawBackground(int width,int height) const {
    if (!active() || publishedSlot_<0 || width<=0 || height<=0) return;
    glViewport(0,0,width,height);
    glDisable(GL_DEPTH_TEST); glDisable(GL_CULL_FACE);
    glUseProgram(backgroundProgram_);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(
        GL_TEXTURE_2D,stagingTextures_[static_cast<std::size_t>(publishedSlot_)]);
    glUniform1i(backgroundTextureUniform_,0);
    glDrawArrays(GL_TRIANGLES,0,3);
    glBindTexture(GL_TEXTURE_2D,0);
    glEnable(GL_DEPTH_TEST); glEnable(GL_CULL_FACE);
}

} // namespace kc
