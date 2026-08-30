#pragma once

#include <GLES3/gl3.h>
#include <GLES2/gl2ext.h>
#include <array>
#include <cstddef>
#include <cstdint>

namespace kc {

// Non-blocking GL_EXT_disjoint_timer_query sampler. Query results are polled
// on later frames; this class never waits for the GPU merely to collect proof.
class GpuTimerQuery {
public:
    struct Stats {
        bool supported=false;
        std::uint32_t counterBits=0;
        std::uint64_t samples=0;
        std::uint32_t disjointIntervals=0;
        std::uint32_t pendingQueries=0;
        double meanMilliseconds=0.0;
        double maximumMilliseconds=0.0;
        double lastMilliseconds=0.0;
        double totalMilliseconds=0.0;
    };

    GpuTimerQuery()=default;
    GpuTimerQuery(const GpuTimerQuery&)=delete;
    GpuTimerQuery& operator=(const GpuTimerQuery&)=delete;

    bool initialize();
    void shutdown();
    // Forget handles without issuing GL calls when their owning context can no
    // longer be made current. This prevents cross-context name deletion.
    void abandon();
    void beginFrame();
    void endFrame();
    Stats stats() const;

private:
    static constexpr std::size_t QueryCount=4u;
    struct Slot {
        GLuint id=0;
        bool pending=false;
    };

    void poll();
    bool anyPending() const;

    PFNGLGENQUERIESEXTPROC genQueries_=nullptr;
    PFNGLDELETEQUERIESEXTPROC deleteQueries_=nullptr;
    PFNGLBEGINQUERYEXTPROC beginQuery_=nullptr;
    PFNGLENDQUERYEXTPROC endQuery_=nullptr;
    PFNGLGETQUERYIVEXTPROC getQueryiv_=nullptr;
    PFNGLGETQUERYOBJECTUIVEXTPROC getQueryObjectUiv_=nullptr;
    PFNGLGETQUERYOBJECTUI64VEXTPROC getQueryObjectUi64v_=nullptr;
    std::array<Slot,QueryCount> slots_{};
    int activeSlot_=-1;
    bool supported_=false,discardPending_=false;
    std::uint32_t counterBits_=0;
    std::uint64_t sampleCount_=0,totalNanoseconds_=0;
    std::uint32_t disjointIntervals_=0;
    GLuint64 maximumNanoseconds_=0,lastNanoseconds_=0;
};

} // namespace kc
