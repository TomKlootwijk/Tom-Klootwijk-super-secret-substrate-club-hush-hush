#include "polar_kinematics.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string_view>

namespace kc {
namespace {

constexpr std::uint32_t MaxProfiles=64;
constexpr std::uint32_t MaxComponents=65535;
constexpr std::uint32_t MaxLutResolution=4096;
constexpr std::size_t MaxPackBytes=2u*1024u*1024u;
constexpr double Tau=6.283185307179586476925286766559;

class Reader {
public:
    Reader(const std::uint8_t* data,std::size_t size):data_(data),size_(size) {}
    std::size_t remaining() const { return size_-offset_; }
    const std::uint8_t* raw(std::size_t count) {
        if (count>remaining()) throw std::runtime_error("truncated KCPK packed-kinematic asset");
        const auto* result=data_+offset_; offset_+=count; return result;
    }
    std::uint16_t u16() {
        const auto* p=raw(2);
        return static_cast<std::uint16_t>(p[0]|(static_cast<std::uint16_t>(p[1])<<8));
    }
    std::uint32_t u32() {
        const auto* p=raw(4);
        return static_cast<std::uint32_t>(p[0])|
            (static_cast<std::uint32_t>(p[1])<<8)|
            (static_cast<std::uint32_t>(p[2])<<16)|
            (static_cast<std::uint32_t>(p[3])<<24);
    }
    std::uint64_t u64() {
        const auto lo=static_cast<std::uint64_t>(u32());
        return lo|(static_cast<std::uint64_t>(u32())<<32);
    }
    double f64() {
        const auto bits=u64(); double result=0; std::memcpy(&result,&bits,sizeof(result)); return result;
    }
    std::string string() {
        const auto length=u16();
        if (length==0) throw std::runtime_error("KCPK profile id is empty");
        const auto* bytes=raw(length);
        return {reinterpret_cast<const char*>(bytes),length};
    }
private:
    const std::uint8_t* data_;
    std::size_t size_=0,offset_=0;
};

void require(bool condition,const char* message) {
    if (!condition) throw std::runtime_error(message);
}

bool validUtf8(std::string_view text) {
    std::size_t index=0;
    while (index<text.size()) {
        const auto first=static_cast<unsigned char>(text[index++]);
        if (first<0x80) continue;
        unsigned count=0; std::uint32_t value=0;
        if ((first&0xE0)==0xC0) { count=1; value=first&0x1F; if (value<2) return false; }
        else if ((first&0xF0)==0xE0) { count=2; value=first&0x0F; }
        else if ((first&0xF8)==0xF0) { count=3; value=first&0x07; }
        else return false;
        if (index+count>text.size()) return false;
        for (unsigned item=0;item<count;++item) {
            const auto next=static_cast<unsigned char>(text[index++]);
            if ((next&0xC0)!=0x80) return false;
            value=(value<<6)|(next&0x3F);
        }
        if ((count==2 && value<0x800)||(count==3 && value<0x10000) ||
            (value>=0xD800 && value<=0xDFFF)||value>0x10FFFF) return false;
    }
    return true;
}

bool byteLess(std::string_view left,std::string_view right) {
    return std::lexicographical_compare(left.begin(),left.end(),right.begin(),right.end(),
        [](char a,char b){ return static_cast<unsigned char>(a)<static_cast<unsigned char>(b); });
}

float halfToFloat(std::uint16_t bits) {
    const std::uint32_t sign=static_cast<std::uint32_t>(bits&0x8000u)<<16;
    std::uint32_t exponent=(bits>>10)&0x1Fu;
    std::uint32_t fraction=bits&0x03FFu;
    std::uint32_t output=0;
    if (exponent==0) {
        if (fraction==0) output=sign;
        else {
            int shift=0;
            while ((fraction&0x0400u)==0) { fraction<<=1; ++shift; }
            fraction&=0x03FFu;
            output=sign|static_cast<std::uint32_t>((127-14-shift)<<23)|(fraction<<13);
        }
    } else if (exponent==0x1Fu) output=sign|0x7F800000u|(fraction<<13);
    else output=sign|((exponent+112u)<<23)|(fraction<<13);
    float value=0; std::memcpy(&value,&output,sizeof(value)); return value;
}

void parseLut(const std::uint8_t* data,std::size_t size,PackedPolarKinematics::Profile& profile) {
    Reader reader(data,size);
    require(size>=48,"KCPK UGLUT2 is truncated");
    require(std::memcmp(reader.raw(6),"UGLUT2",6)==0,"KCPK LUT magic is not UGLUT2");
    const auto resolution=reader.u16();
    require(resolution>=16 && resolution<=MaxLutResolution,"KCPK LUT resolution limit exceeded");
    profile.r0=reader.f64(); profile.rhoMin=reader.f64(); profile.rhoMax=reader.f64();
    profile.coreRadius=reader.f64(); const double radiusScale=reader.f64();
    require(std::isfinite(profile.r0)&&profile.r0>0.0 &&
        std::isfinite(profile.rhoMin)&&std::isfinite(profile.rhoMax)&&profile.rhoMin<profile.rhoMax &&
        std::isfinite(profile.coreRadius)&&profile.coreRadius>0.0 &&
        std::isfinite(radiusScale)&&radiusScale>0.0,"KCPK LUT profile is invalid");
    require(reader.remaining()==static_cast<std::size_t>(resolution)*6u,"KCPK UGLUT2 length mismatch");
    profile.sine.resize(resolution); profile.cosine.resize(resolution); profile.radii.resize(resolution);
    for (auto& value:profile.sine) value=halfToFloat(reader.u16());
    for (auto& value:profile.cosine) value=halfToFloat(reader.u16());
    for (auto& value:profile.radii) value=static_cast<float>(halfToFloat(reader.u16())*radiusScale);
    for (std::size_t index=0;index<resolution;++index) {
        require(std::isfinite(profile.sine[index])&&std::isfinite(profile.cosine[index])&&
            std::hypot(profile.sine[index],profile.cosine[index])>1.0e-9f,
            "KCPK LUT direction sample is invalid");
        require(std::isfinite(profile.radii[index])&&profile.radii[index]>0.0f,
            "KCPK LUT radius sample is invalid");
    }
}

double wrap(double value) {
    value=std::fmod(value,Tau); return value<0.0?value+Tau:value;
}

double decodeClosed(std::uint64_t code,double minimum,double maximum,unsigned bits) {
    const auto maxCode=(std::uint64_t{1}<<bits)-1u;
    return minimum+(maximum-minimum)*(static_cast<double>(code)/static_cast<double>(maxCode));
}

double decodePeriodic(std::uint64_t code,unsigned bits) {
    return Tau*static_cast<double>(code)/static_cast<double>(std::uint64_t{1}<<bits);
}

std::uint64_t encodeClosed(double value,double minimum,double maximum,unsigned bits) {
    value=std::max(minimum,std::min(maximum,value));
    const auto maxCode=(std::uint64_t{1}<<bits)-1u;
    return static_cast<std::uint64_t>(std::nearbyint((value-minimum)/(maximum-minimum)*static_cast<double>(maxCode)));
}

std::uint64_t encodePeriodic(double value,unsigned bits) {
    const auto count=std::uint64_t{1}<<bits;
    return static_cast<std::uint64_t>(std::floor(wrap(value)/Tau*static_cast<double>(count)))&(count-1u);
}

double decodeSigned(std::uint16_t code,double maximum) {
    require(code!=0x8000u,"KCPK motion contains reserved signed code 0x8000");
    const auto signedCode=code&0x8000u?static_cast<int>(code)-0x10000:static_cast<int>(code);
    return static_cast<double>(signedCode)/32767.0*maximum;
}

std::uint16_t encodeSigned(double value,double maximum) {
    value=std::max(-1.0,std::min(1.0,value/maximum));
    const auto signedCode=static_cast<int>(std::nearbyint(value*32767.0));
    return static_cast<std::uint16_t>(signedCode&0xFFFF);
}

struct Pose { double rho=0,theta=0,heading=0; std::uint16_t tick=0; };
struct Motion { double rhoVelocity=0,thetaVelocity=0,rhoAcceleration=0,thetaAcceleration=0; };

Pose decodePose(std::uint64_t word,const PackedPolarKinematics::Profile& profile) {
    const auto heading=word&0xFFFu;
    const auto tick=(word>>12)&0x3FFFu;
    const auto theta=(word>>26)&0x3FFFFu;
    const auto rho=word>>44;
    return {decodeClosed(rho,profile.rhoMin,profile.rhoMax,20),decodePeriodic(theta,18),
        decodePeriodic(heading,12),static_cast<std::uint16_t>(tick)};
}

std::uint64_t encodePose(const Pose& pose,const PackedPolarKinematics::Profile& profile) {
    return (encodeClosed(pose.rho,profile.rhoMin,profile.rhoMax,20)<<44)|
        (encodePeriodic(pose.theta,18)<<26)|
        ((static_cast<std::uint64_t>(pose.tick)&0x3FFFu)<<12)|encodePeriodic(pose.heading,12);
}

Motion decodeMotion(std::uint64_t word,const PackedPolarKinematics::Profile& profile) {
    return {decodeSigned(static_cast<std::uint16_t>(word>>48),profile.rhoVelocity),
        decodeSigned(static_cast<std::uint16_t>(word>>32),profile.thetaVelocity),
        decodeSigned(static_cast<std::uint16_t>(word>>16),profile.rhoAcceleration),
        decodeSigned(static_cast<std::uint16_t>(word),profile.thetaAcceleration)};
}

std::uint64_t encodeMotion(const Motion& motion,const PackedPolarKinematics::Profile& profile) {
    return (static_cast<std::uint64_t>(encodeSigned(motion.rhoVelocity,profile.rhoVelocity))<<48)|
        (static_cast<std::uint64_t>(encodeSigned(motion.thetaVelocity,profile.thetaVelocity))<<32)|
        (static_cast<std::uint64_t>(encodeSigned(motion.rhoAcceleration,profile.rhoAcceleration))<<16)|
        encodeSigned(motion.thetaAcceleration,profile.thetaAcceleration);
}

std::pair<double,double> direction(const PackedPolarKinematics::Profile& profile,double theta) {
    const auto count=profile.sine.size();
    const double coordinate=wrap(theta)*static_cast<double>(count)/Tau;
    const auto low=static_cast<std::size_t>(std::floor(coordinate))%count;
    const auto high=(low+1u)%count;
    const double fraction=coordinate-std::floor(coordinate);
    double sine=profile.sine[low]+(profile.sine[high]-profile.sine[low])*fraction;
    double cosine=profile.cosine[low]+(profile.cosine[high]-profile.cosine[low])*fraction;
    const double magnitude=std::hypot(sine,cosine); sine/=magnitude; cosine/=magnitude;
    return {sine,cosine};
}

double radius(const PackedPolarKinematics::Profile& profile,double rho) {
    rho=std::max(profile.rhoMin,std::min(profile.rhoMax,rho));
    const auto count=profile.radii.size();
    const double coordinate=(rho-profile.rhoMin)*static_cast<double>(count-1u)/(profile.rhoMax-profile.rhoMin);
    const auto low=static_cast<std::size_t>(std::floor(coordinate));
    const auto high=std::min(count-1u,low+1u); const double fraction=coordinate-static_cast<double>(low);
    return profile.radii[low]+(profile.radii[high]-profile.radii[low])*fraction;
}

} // namespace

void PackedPolarKinematics::clear() { profiles_.clear(); components_.clear(); }

void PackedPolarKinematics::load(const std::vector<std::uint8_t>& bytes,const std::vector<NodeData>& nodes) {
    clear();
    if (bytes.empty()) return;
    try {
        require(bytes.size()<=MaxPackBytes,"KCPK asset exceeds its byte limit");
        Reader reader(bytes.data(),bytes.size());
        require(std::memcmp(reader.raw(8),"KCPK392\0",8)==0,"KCPK magic mismatch");
        require(reader.u32()==0x01020304u,"KCPK endian marker mismatch");
        require(reader.u32()==1u,"unsupported KCPK version");
        const auto profileCount=reader.u16(); require(reader.u16()==0,"KCPK header reserved field is nonzero");
        const auto componentCount=reader.u32();
        require(profileCount>=1&&profileCount<=MaxProfiles,"KCPK profile count limit exceeded");
        require(componentCount>=1&&componentCount<=MaxComponents,"KCPK component count limit exceeded");
        profiles_.reserve(profileCount);
        std::string previous;
        for (std::uint16_t index=0;index<profileCount;++index) {
            Profile profile; profile.id=reader.string();
            require(validUtf8(profile.id),"KCPK profile id is not valid UTF-8");
            if (index>0) require(byteLess(previous,profile.id),"KCPK profiles are not canonical");
            previous=profile.id;
            profile.rhoVelocity=reader.f64(); profile.thetaVelocity=reader.f64();
            profile.rhoAcceleration=reader.f64(); profile.thetaAcceleration=reader.f64();
            require(std::isfinite(profile.rhoVelocity)&&profile.rhoVelocity>0.0&&
                std::isfinite(profile.thetaVelocity)&&profile.thetaVelocity>0.0&&
                std::isfinite(profile.rhoAcceleration)&&profile.rhoAcceleration>0.0&&
                std::isfinite(profile.thetaAcceleration)&&profile.thetaAcceleration>0.0,
                "KCPK motion ranges are invalid");
            const auto lutBytes=reader.u32(); const auto* lut=reader.raw(lutBytes);
            parseLut(lut,lutBytes,profile); profiles_.push_back(std::move(profile));
        }
        components_.reserve(componentCount); std::uint32_t previousNode=0;
        for (std::uint32_t index=0;index<componentCount;++index) {
            Component component; component.sceneNode=reader.u32(); component.profile=reader.u16();
            require(reader.u16()==0,"KCPK component reserved field is nonzero");
            component.pose=reader.u64(); component.motion=reader.u64();
            require(component.sceneNode<nodes.size(),"KCPK component node index is invalid");
            require(!nodes[component.sceneNode].dynamic,"KCPK component cannot bind a dynamic physics node");
            require(component.profile<profiles_.size(),"KCPK component profile index is invalid");
            if (index>0) require(component.sceneNode>previousNode,"KCPK components are not sparse-canonical");
            previousNode=component.sceneNode;
            for (unsigned shift:{48u,32u,16u,0u})
                require(((component.motion>>shift)&0xFFFFu)!=0x8000u,"KCPK motion contains reserved signed code 0x8000");
            components_.push_back(component);
        }
        require(reader.remaining()==0,"KCPK trailing bytes");
    } catch (...) {
        clear(); throw;
    }
}

void PackedPolarKinematics::compose(Component const& component,std::vector<NodeData>& nodes) const {
    auto& node=nodes[component.sceneNode];
    if (!node.alive||!node.active) return;
    const auto& profile=profiles_[component.profile]; const auto pose=decodePose(component.pose,profile);
    const auto [sine,cosine]=direction(profile,pose.theta); const auto distance=radius(profile,pose.rho);
    node.translation.x=static_cast<float>(distance*cosine);
    node.translation.z=static_cast<float>(distance*sine);
    node.rotation=axisAngle({0.0f,1.0f,0.0f},static_cast<float>(pose.heading));
}

void PackedPolarKinematics::compose(std::vector<NodeData>& nodes) const {
    for (const auto& component:components_) compose(component,nodes);
}

void PackedPolarKinematics::tick(float dt,std::vector<NodeData>& nodes) {
    require(std::isfinite(dt)&&dt>0.0f&&dt<=0.25f,"packed polar time step is invalid");
    for (auto& component:components_) {
        const auto& node=nodes[component.sceneNode];
        if (!node.alive||!node.active) continue;
        const auto& profile=profiles_[component.profile]; auto pose=decodePose(component.pose,profile);
        auto motion=decodeMotion(component.motion,profile);
        motion.rhoVelocity+=motion.rhoAcceleration*dt;
        motion.thetaVelocity+=motion.thetaAcceleration*dt;
        pose.rho=std::max(profile.rhoMin,std::min(profile.rhoMax,pose.rho+motion.rhoVelocity*dt));
        pose.theta=wrap(pose.theta+motion.thetaVelocity*dt);
        pose.heading=wrap(pose.heading+motion.thetaVelocity*dt);
        pose.tick=static_cast<std::uint16_t>((pose.tick+1u)&0x3FFFu);
        component.motion=encodeMotion(motion,profile); component.pose=encodePose(pose,profile);
        compose(component,nodes);
    }
}

} // namespace kc
