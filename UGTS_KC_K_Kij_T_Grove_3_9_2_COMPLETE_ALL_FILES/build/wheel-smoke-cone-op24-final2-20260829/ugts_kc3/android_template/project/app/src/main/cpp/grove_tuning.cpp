#include "grove_tuning.hpp"
#include "device_profile.hpp"
#include <algorithm>
#include <cctype>

namespace kc {
static bool contains(const std::string& s,const std::string& q) {
    auto a=s,b=q;
    for(char& c:a)c=static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    for(char& c:b)c=static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return a.find(b)!=std::string::npos;
}
GroveTuning selectGroveTuning(const DeviceInfo& info) {
    GroveTuning t;
    const bool poco=contains(info.model,"poco x7 pro") || contains(info.model,"2412dpc0");
    const bool mali=contains(info.gpu,"mali-g720") || contains(info.gpu,"mali-g710") || contains(info.gpu,"mali-g715");
    if (poco && mali) {
        t.profileId="grove_g720_mc7_120"; t.juiceIntensity=1.0f; t.bloom=0.70f;
        t.particleBudget=384; t.post=true; t.maliOptimized=true; t.targetFrameMs=8.33f;
    } else if (mali) {
        t.profileId="grove_mali_high_90"; t.juiceIntensity=0.9f; t.bloom=0.60f;
        t.particleBudget=256; t.post=true; t.targetFrameMs=11.11f;
    } else if (info.ramMb>=6144 && info.cpuCores>=6) {
        t.profileId="grove_android_high_90"; t.juiceIntensity=0.85f; t.bloom=0.55f;
        t.particleBudget=220; t.post=true; t.targetFrameMs=11.11f;
    } else if (info.ramMb>=3072) {
        t.profileId="grove_balanced_60"; t.juiceIntensity=0.72f; t.bloom=0.42f;
        t.particleBudget=128; t.post=true; t.targetFrameMs=16.67f;
    } else {
        t.profileId="grove_compat_60"; t.juiceIntensity=0.48f; t.bloom=0.20f;
        t.particleBudget=48; t.post=false; t.targetFrameMs=16.67f;
    }
    return t;
}
} // namespace kc
