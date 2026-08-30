#include "transform_hierarchy.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <utility>

namespace kc {
namespace {

constexpr std::uint32_t MaxHierarchyDepth=8;
constexpr std::uint32_t MaxHierarchyLinks=65535;
constexpr std::size_t HeaderBytes=24;
constexpr std::size_t LinkBytes=8;

class Reader {
public:
    Reader(const std::uint8_t* data,std::size_t size):data_(data),size_(size) {}
    std::size_t remaining() const { return size_-offset_; }
    const std::uint8_t* raw(std::size_t count) {
        if (count>remaining()) throw std::runtime_error("truncated KCHI hierarchy asset");
        const auto* result=data_+offset_; offset_+=count; return result;
    }
    std::uint32_t u32() {
        const auto* p=raw(4);
        return static_cast<std::uint32_t>(p[0])|
            (static_cast<std::uint32_t>(p[1])<<8)|
            (static_cast<std::uint32_t>(p[2])<<16)|
            (static_cast<std::uint32_t>(p[3])<<24);
    }
private:
    const std::uint8_t* data_;
    std::size_t size_=0,offset_=0;
};

void require(bool condition,const char* message) {
    if (!condition) throw std::runtime_error(message);
}

bool uniformPositive(Vec3 scale) {
    if (!std::isfinite(scale.x)||!std::isfinite(scale.y)||!std::isfinite(scale.z)||
        scale.x<=0.0f||scale.y<=0.0f||scale.z<=0.0f) return false;
    const float magnitude=std::max({1.0f,std::abs(scale.x),std::abs(scale.y),std::abs(scale.z)});
    return std::abs(scale.x-scale.y)<=1.0e-5f*magnitude &&
        std::abs(scale.x-scale.z)<=1.0e-5f*magnitude;
}

Vec3 rotateVector(Quat rotation,Vec3 value) {
    rotation=normalize(rotation);
    const Vec3 imaginary{rotation.x,rotation.y,rotation.z};
    const Vec3 twiceCross=cross(imaginary,value)*2.0f;
    return value+twiceCross*rotation.w+cross(imaginary,twiceCross);
}

} // namespace

void TransformHierarchy::load(
    const std::vector<std::uint8_t>& bytes,const std::vector<NodeData>& nodes
) {
    links_.clear(); maxDepth_=0;
    linkedNodes_.assign(nodes.size(),0u);
    childNodes_.assign(nodes.size(),0u);
    if (bytes.empty()) return;
    require(bytes.size()>=HeaderBytes,"KCHI hierarchy header is truncated");
    Reader reader(bytes.data(),bytes.size());
    require(std::memcmp(reader.raw(8),"KCHI392\0",8)==0,"KCHI hierarchy magic mismatch");
    require(reader.u32()==0x01020304u,"KCHI hierarchy endian marker mismatch");
    require(reader.u32()==1u,"unsupported KCHI hierarchy version");
    const auto linkCount=reader.u32();
    require(reader.u32()==0u,"KCHI hierarchy reserved field is nonzero");
    require(linkCount>0,"empty KCHI hierarchy asset must be omitted");
    require(linkCount<=MaxHierarchyLinks,"KCHI hierarchy link limit exceeded");
    require(
        reader.remaining()==static_cast<std::size_t>(linkCount)*LinkBytes,
        "KCHI hierarchy asset size mismatch"
    );

    constexpr auto NoParent=std::numeric_limits<std::uint32_t>::max();
    std::vector<std::uint32_t> parentByChild(nodes.size(),NoParent);
    std::vector<Link> records;
    records.reserve(linkCount);
    std::uint32_t previousChild=0;
    for (std::uint32_t index=0;index<linkCount;++index) {
        const auto childIndex=reader.u32();
        const auto parentIndex=reader.u32();
        require(childIndex<nodes.size()&&parentIndex<nodes.size(),
            "KCHI hierarchy references a missing scene node");
        require(childIndex!=parentIndex,"KCHI hierarchy child cannot parent itself");
        require(index==0||childIndex>previousChild,
            "KCHI hierarchy children are not in canonical order");
        require(parentByChild[childIndex]==NoParent,
            "KCHI hierarchy contains a duplicate child");
        previousChild=childIndex;
        parentByChild[childIndex]=parentIndex;
        childNodes_[childIndex]=1u;
        linkedNodes_[childIndex]=1u;
        linkedNodes_[parentIndex]=1u;
        const auto& local=nodes[childIndex];
        records.push_back({
            childIndex,parentIndex,0,
            local.translation,local.rotation,local.scale,
        });
    }
    require(reader.remaining()==0,"KCHI hierarchy asset has trailing bytes");

    for (auto& record:records) {
        require(uniformPositive(nodes[record.parentIndex].scale),
            "KCHI hierarchy parent scale must be uniform and positive");
        std::uint32_t current=record.childIndex;
        std::uint32_t depth=0;
        std::vector<std::uint32_t> path;
        while (current<nodes.size()&&parentByChild[current]!=NoParent) {
            require(std::find(path.begin(),path.end(),current)==path.end(),
                "KCHI hierarchy contains a cycle");
            path.push_back(current);
            current=parentByChild[current];
            ++depth;
            require(depth<=MaxHierarchyDepth,"KCHI hierarchy depth limit exceeded");
        }
        record.depth=depth;
        maxDepth_=std::max(maxDepth_,depth);
    }
    std::sort(records.begin(),records.end(),[](const Link& left,const Link& right) {
        if (left.depth!=right.depth) return left.depth<right.depth;
        return left.childIndex<right.childIndex;
    });
    links_=std::move(records);
}

void TransformHierarchy::compose(std::vector<NodeData>& nodes) const {
    for (const auto& link:links_) {
        if (link.childIndex>=nodes.size()||link.parentIndex>=nodes.size())
            throw std::runtime_error("KCHI hierarchy node storage changed after load");
        const auto& parent=nodes[link.parentIndex];
        require(uniformPositive(parent.scale),
            "KCHI hierarchy runtime parent scale must stay uniform and positive");
        const float parentScale=parent.scale.x;
        auto& child=nodes[link.childIndex];
        child.translation=parent.translation+
            rotateVector(parent.rotation,link.localTranslation*parentScale);
        child.rotation=normalize(multiply(parent.rotation,link.localRotation));
        child.scale=link.localScale*parentScale;
    }
}

} // namespace kc
