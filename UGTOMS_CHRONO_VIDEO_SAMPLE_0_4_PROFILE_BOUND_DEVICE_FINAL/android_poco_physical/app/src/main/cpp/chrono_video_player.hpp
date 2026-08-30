#pragma once

#include "chrono_video_lut.hpp"
#include "chrono_video_timeline.hpp"

#include <GLES3/gl3.h>
#include <android/asset_manager.h>
#include <android/native_activity.h>
#include <android/native_window.h>
#include <media/NdkMediaCodec.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <string>
#include <vector>

struct AMediaExtractor;

namespace kc {

enum class ChronoVideoRuntimeMode {
    Disabled,
    AuthoritativeSourceLut,
    DerivedPolarPreview,
    Failed,
};

class ChronoVideoPlayer {
public:
    ChronoVideoPlayer() = default;
    ~ChronoVideoPlayer();
    ChronoVideoPlayer(const ChronoVideoPlayer&)=delete;
    ChronoVideoPlayer& operator=(const ChronoVideoPlayer&)=delete;

    bool initialize(
        ANativeActivity* activity,AAssetManager* assets,
        const ChronoVideoLut& lut,GLuint lutTexture
    );
    void shutdown();
    void setFocused(bool focused,std::int64_t steadyNowNanoseconds);
    void updateAndStage(std::int64_t steadyNowNanoseconds);
    void drawBackground(int width,int height) const;

    ChronoVideoRuntimeMode mode() const { return mode_; }
    bool active() const {
        return mode_==ChronoVideoRuntimeMode::AuthoritativeSourceLut ||
            mode_==ChronoVideoRuntimeMode::DerivedPolarPreview;
    }
    bool failed() const { return mode_==ChronoVideoRuntimeMode::Failed; }

private:
    struct HeldOutput {
        bool valid=false;
        std::size_t codecIndex=0;
        std::int64_t presentationTimeUs=0;
        std::uint32_t flags=0;
        std::size_t ordinal=0;
    };

    std::vector<std::uint8_t> readAsset(const char* path) const;
    bool assetExists(const char* path) const;
    void verifyAssetBinding(const char* path,const std::vector<std::uint8_t>& bytes) const;
    GLuint compile(GLenum type,const std::string& source) const;
    GLuint link(GLuint vertex,GLuint fragment,const char* label) const;
    bool createGlResources(const ChronoVideoLut& lut,GLuint lutTexture);
    bool createDecoderSurface();
    bool openDecoder();
    void closeDecoder();
    bool consumeSurfaceFrame();
    void stageExternalFrame(const std::array<float,16>& transform,int slot);
    void feedDecoder();
    void dequeueDecoder(std::size_t desiredOrdinal);
    void releaseHeldOutput(std::size_t desiredOrdinal);
    bool validateOutputFormat();
    void resetForLoop();
    int slotForOrdinal(std::size_t ordinal) const;
    int freeStagingSlot() const;
    bool publishForTarget(std::size_t targetOrdinal);
    std::size_t desiredDecodeOrdinal(std::size_t targetOrdinal) const;
    void logOnceCompletionReceipt(std::size_t targetOrdinal);
    void fail(const char* message);
    void fail(const std::string& message) { fail(message.c_str()); }
    std::uint64_t elapsedNanoseconds(std::int64_t steadyNowNanoseconds) const;

    ANativeActivity* activity_=nullptr;
    AAssetManager* assets_=nullptr;
    ChronoVideoRuntimeMode mode_=ChronoVideoRuntimeMode::Disabled;
    ChronoVideoTimeline timeline_;
    std::string timelineAssetPath_;
    std::string mediaAssetPath_;
    std::vector<std::uint8_t> mediaBytes_;

    AMediaExtractor* extractor_=nullptr;
    AMediaCodec* codec_=nullptr;
    ANativeWindow* decoderWindow_=nullptr;
    int mediaFileDescriptor_=-1;
    std::size_t inputOrdinal_=0;
    std::size_t outputOrdinal_=0;
    std::vector<std::int64_t> queuedPresentationTimesUs_;
    std::int64_t lastPreviewInputPtsUs_=-1;
    bool inputEos_=false;
    bool outputEos_=false;
    HeldOutput heldOutput_{};

    GLuint externalTexture_=0;
    std::array<GLuint,2> stagingTextures_{};
    std::array<GLuint,2> stagingFramebuffers_{};
    GLuint stageProgram_=0;
    GLuint backgroundProgram_=0;
    GLuint lutTexture_=0;
    GLint stageVideoUniform_=-1;
    GLint stageTransformUniform_=-1;
    GLint stageSourceSizeUniform_=-1;
    GLint stageOutputSizeUniform_=-1;
    GLint stageLutUniform_=-1;
    GLint backgroundTextureUniform_=-1;
    std::uint32_t outputWidth_=0;
    std::uint32_t outputHeight_=0;

    bool surfaceFrameAwaited_=false;
    std::size_t releasedOrdinal_=0;
    std::size_t stagedOrdinal_=std::numeric_limits<std::size_t>::max();
    std::array<std::size_t,2> stagingOrdinals_{
        std::numeric_limits<std::size_t>::max(),
        std::numeric_limits<std::size_t>::max()
    };
    int publishedSlot_=-1;
    std::uint64_t stagedFrameCount_=0;
    std::uint64_t decoderCatchupDropCount_=0;
    std::uint64_t lateBoundaryCount_=0;
    bool completionReceiptLogged_=false;
    std::size_t lastLateTarget_=std::numeric_limits<std::size_t>::max();
    std::uint64_t decoderLoopCount_=0;
    std::int64_t lastSurfaceTimestampNs_=-1;

    bool focused_=false;
    bool playbackClockStarted_=false;
    std::int64_t playbackStartNs_=0;
    std::int64_t pauseStartNs_=0;
    bool loopResetPending_=false;
    std::uint64_t previousLoopCycle_=0;
    bool havePreviousLoopCycle_=false;
};

const char* chronoVideoRuntimeModeName(ChronoVideoRuntimeMode mode);

} // namespace kc
