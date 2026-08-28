#include "device_profile.hpp"
#include <algorithm>
#include <cctype>
#include <limits>

namespace kc {
namespace {
std::string lower(std::string value) {
    std::transform(value.begin(),value.end(),value.begin(),[](unsigned char c){return static_cast<char>(std::tolower(c));});
    return value;
}
bool contains(const std::string& haystack,const std::string& needle) {
    return lower(haystack).find(lower(needle))!=std::string::npos;
}
const QualityTier* quality(const ScenePack& scene,const std::string& id) {
    for (const auto& q:scene.qualities) if (q.id==id) return &q;
    return nullptr;
}
} // namespace

ProfileSelection selectProfile(const ScenePack& scene, const DeviceInfo& device, const std::string& requested) {
    if (scene.targets.empty() || scene.qualities.empty()) return {};
    const TargetProfile* selected=nullptr;
    std::string reason;
    if (!requested.empty() && requested!="auto") {
        for (const auto& profile:scene.targets) if (profile.id==requested) selected=&profile;
        if (selected) reason="explicit profile request";
    }
    if (!selected) {
        int best=std::numeric_limits<int>::min();
        const std::string deviceText=device.manufacturer+" "+device.model;
        for (const auto& profile:scene.targets) {
            int score=0;
            if (device.ramMb>=profile.memoryFloorMb) score+=10; else score-=60;
            if (device.glesMajor>profile.glesMajor || (device.glesMajor==profile.glesMajor && device.glesMinor>=profile.glesMinor)) score+=10; else score-=100;
            if (device.refreshHz+1.0f>=profile.targetRefreshHz) score+=5;
            if (profile.id=="poco_x7_pro_12gb") {
                if (contains(deviceText,"poco x7 pro") || contains(deviceText,"2412dpc0") || contains(deviceText,"rodin")) score+=100;
                if (contains(device.gpu,"mali-g720")) score+=25;
            }
            for (const auto& hint:profile.deviceHints) if (contains(deviceText,hint)) score+=30;
            for (const auto& hint:profile.gpuHints) if (contains(device.gpu,hint)) score+=15;
            if (score>best) { best=score; selected=&profile; reason="runtime capability score "+std::to_string(score); }
        }
    }
    if (!selected) selected=&scene.targets.back();
    const QualityTier* q=quality(scene,selected->defaultQuality);
    if (!q) q=&scene.qualities.back();
    ProfileSelection result;
    result.profileId=selected->id; result.qualityId=q->id;
    result.targetFps=static_cast<std::uint16_t>(std::min<float>({static_cast<float>(q->targetFps),static_cast<float>(selected->targetRefreshHz),std::max(30.0f,device.refreshHz)}));
    result.renderScale=q->renderScale; result.maxVisibleNodes=q->maxVisibleNodes; result.reason=reason;
    return result;
}

} // namespace kc
