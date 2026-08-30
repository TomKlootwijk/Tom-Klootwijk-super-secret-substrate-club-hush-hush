#include "gpu_timer_query.hpp"

#include <EGL/egl.h>
#include <algorithm>
#include <cstring>

namespace kc {
namespace {

bool hasExtension(const char* extensions,const char* wanted) {
    if (!extensions || !wanted || !*wanted || std::strchr(wanted,' ')) return false;
    const auto wantedLength=std::strlen(wanted);
    const char* cursor=extensions;
    while ((cursor=std::strstr(cursor,wanted))!=nullptr) {
        const bool startsToken=cursor==extensions || cursor[-1]==' ';
        const char following=cursor[wantedLength];
        if (startsToken && (following=='\0' || following==' ')) return true;
        cursor+=wantedLength;
    }
    return false;
}

template<class Function>
Function extensionFunction(const char* name) {
    return reinterpret_cast<Function>(eglGetProcAddress(name));
}

void clearErrors() {
    while (glGetError()!=GL_NO_ERROR) {}
}

bool callFailed() {
    bool failed=false;
    while (glGetError()!=GL_NO_ERROR) failed=true;
    return failed;
}

} // namespace

bool GpuTimerQuery::initialize() {
    shutdown();
    const auto* extensions=reinterpret_cast<const char*>(glGetString(GL_EXTENSIONS));
    if (!hasExtension(extensions,"GL_EXT_disjoint_timer_query")) return false;

    genQueries_=extensionFunction<PFNGLGENQUERIESEXTPROC>("glGenQueriesEXT");
    deleteQueries_=extensionFunction<PFNGLDELETEQUERIESEXTPROC>("glDeleteQueriesEXT");
    beginQuery_=extensionFunction<PFNGLBEGINQUERYEXTPROC>("glBeginQueryEXT");
    endQuery_=extensionFunction<PFNGLENDQUERYEXTPROC>("glEndQueryEXT");
    getQueryiv_=extensionFunction<PFNGLGETQUERYIVEXTPROC>("glGetQueryivEXT");
    getQueryObjectUiv_=extensionFunction<PFNGLGETQUERYOBJECTUIVEXTPROC>(
        "glGetQueryObjectuivEXT"
    );
    getQueryObjectUi64v_=extensionFunction<PFNGLGETQUERYOBJECTUI64VEXTPROC>(
        "glGetQueryObjectui64vEXT"
    );
    if (!genQueries_ || !deleteQueries_ || !beginQuery_ || !endQuery_ || !getQueryiv_ ||
        !getQueryObjectUiv_ || !getQueryObjectUi64v_) {
        shutdown();
        return false;
    }

    clearErrors();
    GLint counterBits=0;
    getQueryiv_(GL_TIME_ELAPSED_EXT,GL_QUERY_COUNTER_BITS_EXT,&counterBits);
    if (callFailed() || counterBits<30) {
        shutdown();
        return false;
    }
    counterBits_=static_cast<std::uint32_t>(counterBits);

    clearErrors();
    std::array<GLuint,QueryCount> identifiers{};
    genQueries_(static_cast<GLsizei>(identifiers.size()),identifiers.data());
    if (callFailed() ||
        std::any_of(identifiers.begin(),identifiers.end(),[](GLuint id) { return id==0u; })) {
        if (deleteQueries_)
            deleteQueries_(static_cast<GLsizei>(identifiers.size()),identifiers.data());
        shutdown();
        return false;
    }
    for (std::size_t index=0;index<slots_.size();++index)
        slots_[index].id=identifiers[index];
    supported_=true;
    return true;
}

void GpuTimerQuery::shutdown() {
    if (activeSlot_>=0 && endQuery_) endQuery_(GL_TIME_ELAPSED_EXT);
    activeSlot_=-1;
    if (deleteQueries_) {
        std::array<GLuint,QueryCount> identifiers{};
        for (std::size_t index=0;index<slots_.size();++index)
            identifiers[index]=slots_[index].id;
        if (std::any_of(
                identifiers.begin(),identifiers.end(),[](GLuint id) { return id!=0u; }
            )) {
            deleteQueries_(static_cast<GLsizei>(identifiers.size()),identifiers.data());
        }
    }
    abandon();
}

void GpuTimerQuery::abandon() {
    activeSlot_=-1;
    slots_={};
    genQueries_=nullptr;
    deleteQueries_=nullptr;
    beginQuery_=nullptr;
    endQuery_=nullptr;
    getQueryiv_=nullptr;
    getQueryObjectUiv_=nullptr;
    getQueryObjectUi64v_=nullptr;
    supported_=false;
    discardPending_=false;
    counterBits_=0;
    sampleCount_=0;
    totalNanoseconds_=0;
    disjointIntervals_=0;
    maximumNanoseconds_=0;
    lastNanoseconds_=0;
}

bool GpuTimerQuery::anyPending() const {
    return std::any_of(slots_.begin(),slots_.end(),[](const Slot& slot) {
        return slot.pending;
    });
}

void GpuTimerQuery::poll() {
    if (!supported_) return;
    std::array<bool,QueryCount> availableSlots{};
    for (std::size_t index=0;index<slots_.size();++index) {
        const auto& slot=slots_[index];
        if (!slot.pending) continue;
        GLuint available=GL_FALSE;
        clearErrors();
        getQueryObjectUiv_(slot.id,GL_QUERY_RESULT_AVAILABLE_EXT,&available);
        if (callFailed()) {
            supported_=false;
            return;
        }
        availableSlots[index]=available==GL_TRUE;
    }

    // Read the disjoint flag immediately after discovering ready results and
    // before accepting any of them. A true value invalidates every outstanding
    // query, including results that are not ready until a later poll.
    clearErrors();
    GLint disjoint=GL_FALSE;
    glGetIntegerv(GL_GPU_DISJOINT_EXT,&disjoint);
    if (callFailed()) {
        supported_=false;
        return;
    }
    if (disjoint==GL_TRUE) {
        discardPending_=true;
        // The extension exposes a boolean, not an exact event counter. Count
        // only the polling intervals in which one-or-more disjoints appeared.
        ++disjointIntervals_;
    }

    for (std::size_t index=0;index<slots_.size();++index) {
        auto& slot=slots_[index];
        if (!availableSlots[index]) continue;
        GLuint64 nanoseconds=0;
        clearErrors();
        getQueryObjectUi64v_(slot.id,GL_QUERY_RESULT_EXT,&nanoseconds);
        if (callFailed()) {
            supported_=false;
            return;
        }
        slot.pending=false;
        if (discardPending_) continue;
        lastNanoseconds_=nanoseconds;
        maximumNanoseconds_=std::max(maximumNanoseconds_,nanoseconds);
        totalNanoseconds_+=nanoseconds;
        ++sampleCount_;
    }
    if (discardPending_ && !anyPending()) discardPending_=false;
}

void GpuTimerQuery::beginFrame() {
    if (!supported_ || activeSlot_>=0) return;
    poll();
    if (discardPending_) return;
    for (std::size_t index=0;index<slots_.size();++index) {
        if (slots_[index].pending) continue;
        clearErrors();
        beginQuery_(GL_TIME_ELAPSED_EXT,slots_[index].id);
        if (callFailed()) {
            supported_=false;
            return;
        }
        activeSlot_=static_cast<int>(index);
        return;
    }
}

void GpuTimerQuery::endFrame() {
    if (!supported_ || activeSlot_<0) return;
    clearErrors();
    endQuery_(GL_TIME_ELAPSED_EXT);
    if (callFailed()) {
        activeSlot_=-1;
        supported_=false;
        return;
    }
    slots_[static_cast<std::size_t>(activeSlot_)].pending=true;
    activeSlot_=-1;
}

GpuTimerQuery::Stats GpuTimerQuery::stats() const {
    const auto pending=static_cast<std::uint32_t>(std::count_if(
        slots_.begin(),slots_.end(),[](const Slot& slot) { return slot.pending; }
    ));
    constexpr double NanosecondsPerMillisecond=1000000.0;
    return {
        supported_,counterBits_,sampleCount_,disjointIntervals_,pending,
        sampleCount_?static_cast<double>(totalNanoseconds_)/
            static_cast<double>(sampleCount_)/NanosecondsPerMillisecond:0.0,
        static_cast<double>(maximumNanoseconds_)/NanosecondsPerMillisecond,
        static_cast<double>(lastNanoseconds_)/NanosecondsPerMillisecond,
        static_cast<double>(totalNanoseconds_)/NanosecondsPerMillisecond,
    };
}

} // namespace kc
