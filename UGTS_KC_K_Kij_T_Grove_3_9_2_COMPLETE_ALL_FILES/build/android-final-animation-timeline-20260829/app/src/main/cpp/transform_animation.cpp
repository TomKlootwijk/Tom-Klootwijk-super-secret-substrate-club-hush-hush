#include "transform_animation.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <stdexcept>

namespace kc {
namespace {

constexpr std::uint32_t MaxBindings=64;
constexpr std::uint32_t MaxKeysPerBinding=128;
constexpr std::uint32_t MaxKeys=4096;
constexpr float MaxTranslation=4096.0f;
constexpr float MinScale=1.0f/1024.0f;
constexpr float MaxScale=64.0f;
constexpr std::size_t MaxPackBytes=128u*1024u;
constexpr std::size_t HeaderBytes=24;
constexpr std::size_t BindingBytes=16;
constexpr std::size_t KeyBytes=24;

class Reader {
public:
    Reader(const std::uint8_t* data,std::size_t size):data_(data),size_(size) {}
    std::size_t remaining() const { return size_-offset_; }
    const std::uint8_t* raw(std::size_t count) {
        if (count>remaining()) throw std::runtime_error("truncated KCAN transform-animation asset");
        const auto* result=data_+offset_; offset_+=count; return result;
    }
    std::uint8_t u8() { return *raw(1); }
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
    float f32() {
        const auto bits=u32(); float result=0.0f;
        std::memcpy(&result,&bits,sizeof(result)); return result;
    }
private:
    const std::uint8_t* data_;
    std::size_t size_=0,offset_=0;
};

void require(bool condition,const char* message) {
    if (!condition) throw std::runtime_error(message);
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
    float value=0.0f; std::memcpy(&value,&output,sizeof(value)); return value;
}

bool finite(Vec3 value) {
    return std::isfinite(value.x)&&std::isfinite(value.y)&&std::isfinite(value.z);
}

bool finite(Quat value) {
    return std::isfinite(value.w)&&std::isfinite(value.x)&&
        std::isfinite(value.y)&&std::isfinite(value.z);
}

float quaternionLengthSquared(Quat value) {
    return value.w*value.w+value.x*value.x+value.y*value.y+value.z*value.z;
}

float quaternionDot(Quat left,Quat right) {
    return left.w*right.w+left.x*right.x+left.y*right.y+left.z*right.z;
}

Quat nlerpShortest(Quat left,Quat right,float amount) {
    if (quaternionDot(left,right)<0.0f)
        right={-right.w,-right.x,-right.y,-right.z};
    return normalize({
        left.w+(right.w-left.w)*amount,
        left.x+(right.x-left.x)*amount,
        left.y+(right.y-left.y)*amount,
        left.z+(right.z-left.z)*amount,
    });
}

double ease(std::uint8_t code,double value) {
    value=std::max(0.0,std::min(1.0,value));
    switch (code) {
        case 0: return value;
        case 1: return 0.0;
        case 2: return value*value;
        case 3: return 1.0-(1.0-value)*(1.0-value);
        case 4: return value<0.5?2.0*value*value:1.0-std::pow(-2.0*value+2.0,2.0)/2.0;
        case 5: return value*value*(3.0-2.0*value);
        case 6: return value*value*value*(value*(value*6.0-15.0)+10.0);
        case 7: {
            constexpr double c1=1.70158;
            constexpr double c3=c1+1.0;
            const double shifted=value-1.0;
            return 1.0+c3*shifted*shifted*shifted+c1*shifted*shifted;
        }
        case 8: {
            if (value==0.0||value==1.0) return value;
            constexpr double c4=6.283185307179586476925286766559/3.0;
            return std::pow(2.0,-10.0*value)*std::sin((value*10.0-0.75)*c4)+1.0;
        }
        default: throw std::runtime_error("KCAN easing code is invalid");
    }
}

Vec3 interpolate(Vec3 left,Vec3 right,float amount) {
    return {
        left.x+(right.x-left.x)*amount,
        left.y+(right.y-left.y)*amount,
        left.z+(right.z-left.z)*amount,
    };
}

bool identity(const TransformAnimations::Pose& pose) {
    return pose.translation.x==0.0f&&pose.translation.y==0.0f&&pose.translation.z==0.0f&&
        pose.rotation.w==1.0f&&pose.rotation.x==0.0f&&
        pose.rotation.y==0.0f&&pose.rotation.z==0.0f&&
        pose.scale.x==1.0f&&pose.scale.y==1.0f&&pose.scale.z==1.0f;
}

double easingUpperBound(std::uint8_t code) {
    if (code==7) return 1.101;
    if (code==8) return 1.374;
    return 1.0;
}

bool scaleSegmentIsSafe(float left,float right,std::uint8_t easing) {
    if (left==0.0f||right==0.0f||std::signbit(left)!=std::signbit(right)) return false;
    const double upper=easingUpperBound(easing);
    const double extreme=static_cast<double>(left)+
        (static_cast<double>(right)-static_cast<double>(left))*upper;
    return std::isfinite(extreme)&&extreme>=MinScale;
}

} // namespace

void TransformAnimations::clear() { bindings_.clear(); keys_.clear(); }

void TransformAnimations::load(
    const std::vector<std::uint8_t>& bytes,const std::vector<NodeData>& nodes
) {
    clear();
    if (bytes.empty()) return;
    try {
        require(bytes.size()<=MaxPackBytes,"KCAN asset exceeds its byte limit");
        Reader reader(bytes.data(),bytes.size());
        require(std::memcmp(reader.raw(8),"KCAN392\0",8)==0,"KCAN magic mismatch");
        require(reader.u32()==0x01020304u,"KCAN endian marker mismatch");
        require(reader.u32()==1u,"unsupported KCAN version");
        const auto bindingCount=reader.u16();
        require(reader.u16()==0,"KCAN header reserved field is nonzero");
        const auto totalKeyCount=reader.u32();
        require(bindingCount>=1&&bindingCount<=MaxBindings,"KCAN binding count limit exceeded");
        require(totalKeyCount>=bindingCount&&totalKeyCount<=MaxKeys,"KCAN key count limit exceeded");
        const auto expectedSize=HeaderBytes+
            static_cast<std::size_t>(bindingCount)*BindingBytes+
            static_cast<std::size_t>(totalKeyCount)*KeyBytes;
        require(bytes.size()==expectedSize,"KCAN byte length does not match its counts");

        bindings_.reserve(bindingCount);
        std::uint32_t previousNode=0,expectedFirstKey=0;
        for (std::uint16_t index=0;index<bindingCount;++index) {
            Binding binding;
            binding.sceneNode=reader.u32(); binding.duration=reader.f32();
            binding.firstKey=reader.u32(); binding.keyCount=reader.u16();
            binding.loop=reader.u8(); require(reader.u8()==0,"KCAN binding reserved field is nonzero");
            require(binding.sceneNode<nodes.size(),"KCAN binding node index is invalid");
            if (index>0) require(binding.sceneNode>previousNode,"KCAN bindings are not sparse-canonical");
            previousNode=binding.sceneNode;
            require(std::isfinite(binding.duration)&&binding.duration>=1.0f/60.0f&&
                binding.duration<=120.0f,"KCAN duration is outside the supported range");
            require(binding.firstKey==expectedFirstKey,"KCAN key ranges are not contiguous");
            require(binding.keyCount>=1&&binding.keyCount<=MaxKeysPerBinding,
                "KCAN binding key count limit exceeded");
            expectedFirstKey+=binding.keyCount;
            require(expectedFirstKey<=totalKeyCount,"KCAN binding key range is invalid");
            require(binding.loop<=2,"KCAN loop mode is invalid");
            const auto& node=nodes[binding.sceneNode];
            require(!node.dynamic,"KCAN cannot bind a dynamic physics node");
            require((node.tagMask&TagPlayer)==0,"KCAN cannot bind the Player node");
            require(finite(node.translation)&&finite(node.rotation)&&finite(node.scale),
                "KCAN base transform is not finite");
            require(quaternionLengthSquared(node.rotation)>1.0e-12f,
                "KCAN base rotation is invalid");
            require(node.scale.x!=0.0f&&node.scale.y!=0.0f&&node.scale.z!=0.0f,
                "KCAN base scale contains zero");
            binding.base={node.translation,normalize(node.rotation),node.scale};
            bindings_.push_back(binding);
        }
        require(expectedFirstKey==totalKeyCount,"KCAN key ranges do not cover the key table");

        keys_.reserve(totalKeyCount);
        for (std::uint32_t index=0;index<totalKeyCount;++index) {
            Key key; key.timeCode=reader.u16(); key.easing=reader.u8();
            require(reader.u8()==0,"KCAN key reserved field is nonzero");
            float values[10]{};
            for (float& value:values) value=halfToFloat(reader.u16());
            key.relative.translation={values[0],values[1],values[2]};
            key.relative.rotation={values[3],values[4],values[5],values[6]};
            key.relative.scale={values[7],values[8],values[9]};
            require(key.easing<=8,"KCAN easing code is invalid");
            require(finite(key.relative.translation)&&finite(key.relative.rotation)&&
                finite(key.relative.scale),"KCAN key pose is not finite");
            require(std::abs(key.relative.translation.x)<=MaxTranslation&&
                std::abs(key.relative.translation.y)<=MaxTranslation&&
                std::abs(key.relative.translation.z)<=MaxTranslation,
                "KCAN key translation exceeds its compact range");
            require(quaternionLengthSquared(key.relative.rotation)>1.0e-12f,
                "KCAN key rotation is invalid");
            require(key.relative.scale.x>=MinScale&&key.relative.scale.x<=MaxScale&&
                key.relative.scale.y>=MinScale&&key.relative.scale.y<=MaxScale&&
                key.relative.scale.z>=MinScale&&key.relative.scale.z<=MaxScale,
                "KCAN key scale exceeds its compact range");
            keys_.push_back(key);
        }
        require(reader.remaining()==0,"KCAN trailing bytes");

        for (const auto& binding:bindings_) {
            const auto begin=static_cast<std::size_t>(binding.firstKey);
            const auto end=begin+binding.keyCount;
            require(keys_[begin].timeCode==0,"KCAN first key must start at time zero");
            require(identity(keys_[begin].relative),"KCAN first key must be the identity pose");
            keys_[begin].relative.rotation=normalize(keys_[begin].relative.rotation);
            for (std::size_t index=begin+1;index<end;++index) {
                const auto& left=keys_[index-1]; auto& right=keys_[index];
                require(right.timeCode>left.timeCode,"KCAN key times must be strictly increasing");
                right.relative.rotation=normalize(right.relative.rotation);
                if (quaternionDot(left.relative.rotation,right.relative.rotation)<0.0f) {
                    auto& value=right.relative.rotation;
                    value={-value.w,-value.x,-value.y,-value.z};
                }
                require(scaleSegmentIsSafe(left.relative.scale.x,right.relative.scale.x,right.easing)&&
                    scaleSegmentIsSafe(left.relative.scale.y,right.relative.scale.y,right.easing)&&
                    scaleSegmentIsSafe(left.relative.scale.z,right.relative.scale.z,right.easing),
                    "KCAN interpolated scale can cross zero");
            }
        }
    } catch (...) {
        clear(); throw;
    }
}

TransformAnimations::Pose TransformAnimations::sample(const Binding& binding) const {
    const auto first=static_cast<std::size_t>(binding.firstKey);
    const auto last=first+binding.keyCount-1u;
    double local=std::max(0.0,binding.elapsed);
    const double duration=binding.duration;
    if (binding.loop==0) local=std::min(duration,local);
    else if (binding.loop==1) local=std::fmod(local,duration);
    else {
        const double period=duration*2.0;
        local=std::fmod(local,period);
        if (local>duration) local=period-local;
    }
    const double coordinate=local/duration*65535.0;
    if (coordinate<=keys_[first].timeCode) return keys_[first].relative;
    if (coordinate>=keys_[last].timeCode) return keys_[last].relative;
    auto right=first+1u;
    while (right<=last&&coordinate>keys_[right].timeCode) ++right;
    if (coordinate==keys_[right].timeCode) return keys_[right].relative;
    const auto& leftKey=keys_[right-1u]; const auto& rightKey=keys_[right];
    const double span=static_cast<double>(rightKey.timeCode-leftKey.timeCode);
    const double linear=(coordinate-leftKey.timeCode)/span;
    const float amount=static_cast<float>(ease(rightKey.easing,linear));
    return {
        interpolate(leftKey.relative.translation,rightKey.relative.translation,amount),
        nlerpShortest(leftKey.relative.rotation,rightKey.relative.rotation,amount),
        interpolate(leftKey.relative.scale,rightKey.relative.scale,amount),
    };
}

void TransformAnimations::compose(
    const Binding& binding,std::vector<NodeData>& nodes
) const {
    auto& node=nodes[binding.sceneNode];
    if (!node.alive||!node.active) return;
    const auto relative=sample(binding);
    const Vec3 scale{
        binding.base.scale.x*relative.scale.x,
        binding.base.scale.y*relative.scale.y,
        binding.base.scale.z*relative.scale.z,
    };
    require(finite(relative.translation)&&finite(relative.rotation)&&finite(scale)&&
        scale.x!=0.0f&&scale.y!=0.0f&&scale.z!=0.0f,
        "KCAN sampled transform is invalid");
    node.translation=binding.base.translation+relative.translation;
    node.rotation=normalize(multiply(binding.base.rotation,relative.rotation));
    node.scale=scale;
}

void TransformAnimations::compose(std::vector<NodeData>& nodes) const {
    for (const auto& binding:bindings_) compose(binding,nodes);
}

void TransformAnimations::tick(float dt,std::vector<NodeData>& nodes) {
    require(std::isfinite(dt)&&dt>0.0f&&dt<=0.25f,"transform animation time step is invalid");
    for (auto& binding:bindings_) {
        binding.elapsed+=static_cast<double>(dt);
        require(std::isfinite(binding.elapsed),"transform animation clock overflowed");
        compose(binding,nodes);
    }
}

} // namespace kc
