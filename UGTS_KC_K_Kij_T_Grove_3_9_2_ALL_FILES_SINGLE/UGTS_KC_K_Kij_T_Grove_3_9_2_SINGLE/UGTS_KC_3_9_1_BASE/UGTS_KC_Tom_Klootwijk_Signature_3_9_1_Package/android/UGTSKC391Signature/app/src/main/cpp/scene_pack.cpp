#include "scene_pack.hpp"
#include <cstring>
#include <stdexcept>

namespace kc {
namespace {

class Reader {
public:
    Reader(const std::uint8_t* data, std::size_t size) : data_(data), size_(size) {}
    std::size_t remaining() const { return size_ - offset_; }
    const std::uint8_t* raw(std::size_t count) {
        if (count > remaining()) throw std::runtime_error("truncated KC3D scene pack");
        const auto* result = data_ + offset_;
        offset_ += count;
        return result;
    }
    std::uint8_t u8() { return *raw(1); }
    std::uint16_t u16() {
        const auto* p=raw(2); return static_cast<std::uint16_t>(p[0] | (p[1]<<8));
    }
    std::uint32_t u32() {
        const auto* p=raw(4);
        return static_cast<std::uint32_t>(p[0]) |
               (static_cast<std::uint32_t>(p[1])<<8) |
               (static_cast<std::uint32_t>(p[2])<<16) |
               (static_cast<std::uint32_t>(p[3])<<24);
    }
    float f32() {
        const std::uint32_t bits=u32();
        float value=0;
        std::memcpy(&value,&bits,sizeof(value));
        return value;
    }
    Vec3 vec3() { return {f32(),f32(),f32()}; }
    Quat quat() { return {f32(),f32(),f32(),f32()}; }
    std::string string() {
        const auto length=u16();
        const auto* p=raw(length);
        return {reinterpret_cast<const char*>(p),length};
    }
private:
    const std::uint8_t* data_;
    std::size_t size_;
    std::size_t offset_=0;
};

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

} // namespace

ScenePack parseScenePack(const std::uint8_t* data, std::size_t size) {
    Reader r(data,size);
    const char expected[8]={'K','C','3','D','3','9','1','\0'};
    require(std::memcmp(r.raw(8),expected,8)==0,"KC3D magic mismatch");
    require(r.u32()==0x01020304u,"KC3D endian marker mismatch");
    require(r.u32()==1u,"unsupported KC3D version");
    const auto meshCount=r.u32();
    const auto materialCount=r.u32();
    const auto nodeCount=r.u32();
    const auto qualityCount=r.u32();
    const auto targetCount=r.u32();
    require(meshCount<=4096 && materialCount<=4096 && nodeCount<=100000,"KC3D count limit exceeded");

    ScenePack out;
    for (float& v:out.background) v=r.f32();
    out.cameraPosition=r.vec3(); out.cameraTarget=r.vec3(); out.cameraUp=r.vec3();
    out.cameraFovDegrees=r.f32(); out.cameraNear=r.f32(); out.cameraFar=r.f32();
    out.lightDirection=r.vec3(); out.lightColor=r.vec3();
    out.lightIntensity=r.f32(); out.ambient=r.f32();
    out.fixedDt=r.f32(); out.gravity=r.vec3(); out.floorY=r.f32();
    out.boundsMin=r.vec3(); out.boundsMax=r.vec3();
    out.playerSpeed=r.f32(); out.jumpSpeed=r.f32();
    const auto* hash=r.raw(64);
    out.projectHash.assign(reinterpret_cast<const char*>(hash),64);
    out.projectId=r.string(); out.title=r.string(); out.author=r.string(); out.startQuality=r.string();

    out.qualities.reserve(qualityCount);
    for (std::uint32_t i=0;i<qualityCount;++i) {
        QualityTier q;
        q.id=r.string(); q.targetFps=r.u16(); q.renderScale=r.f32(); q.maxVisibleNodes=r.u32();
        q.msaaSamples=r.u8(); q.postProcessing=r.u8()!=0; q.shadowQuality=r.u8(); r.u8();
        require(q.renderScale>=0.4f && q.renderScale<=1.0f,"KC3D quality scale invalid");
        out.qualities.push_back(std::move(q));
    }
    out.targets.reserve(targetCount);
    for (std::uint32_t i=0;i<targetCount;++i) {
        TargetProfile p;
        p.id=r.string(); p.label=r.string();
        p.minSdk=r.u16(); p.targetSdk=r.u16(); p.compileSdk=r.u16(); p.targetRefreshHz=r.u16();
        p.memoryFloorMb=r.u32(); p.glesMajor=r.u8(); p.glesMinor=r.u8();
        p.vulkanOptional=r.u8()!=0;
        const auto abiCount=r.u8();
        for (std::uint8_t j=0;j<abiCount;++j) p.abis.push_back(r.string());
        p.defaultQuality=r.string();
        const auto deviceCount=r.u8();
        for (std::uint8_t j=0;j<deviceCount;++j) p.deviceHints.push_back(r.string());
        const auto gpuCount=r.u8();
        for (std::uint8_t j=0;j<gpuCount;++j) p.gpuHints.push_back(r.string());
        out.targets.push_back(std::move(p));
    }
    out.meshes.reserve(meshCount);
    for (std::uint32_t i=0;i<meshCount;++i) {
        MeshData mesh;
        mesh.id=r.string();
        const auto vertexCount=r.u32();
        const auto indexCount=r.u32();
        require(vertexCount<=10000000 && indexCount<=30000000,"KC3D mesh limit exceeded");
        mesh.vertices.resize(vertexCount);
        for (auto& vertex:mesh.vertices) {
            vertex.position=r.vec3(); vertex.normal=r.vec3();
        }
        mesh.indices.resize(indexCount);
        for (auto& index:mesh.indices) {
            index=r.u32();
            require(index<vertexCount,"KC3D mesh index out of range");
        }
        out.meshes.push_back(std::move(mesh));
    }
    out.materials.reserve(materialCount);
    for (std::uint32_t i=0;i<materialCount;++i) {
        MaterialData material;
        material.id=r.string();
        for (float& v:material.baseColor) v=r.f32();
        material.metallic=r.f32(); material.roughness=r.f32(); material.emissive=r.vec3();
        material.doubleSided=r.u8()!=0; r.raw(3);
        out.materials.push_back(std::move(material));
    }
    out.nodes.reserve(nodeCount);
    for (std::uint32_t i=0;i<nodeCount;++i) {
        NodeData node;
        node.id=r.string(); node.meshIndex=r.u32(); node.materialIndex=r.u32();
        node.translation=r.vec3(); node.rotation=r.quat(); node.scale=r.vec3();
        node.velocity=r.vec3(); node.angularVelocity=r.vec3();
        node.collider.type=r.u8(); node.collider.sensor=r.u8()!=0; node.dynamic=r.u8()!=0; r.u8();
        node.collider.radius=r.f32(); node.collider.halfExtents=r.vec3();
        node.mass=r.f32(); node.restitution=r.f32(); node.tagMask=r.u32();
        require(node.meshIndex<out.meshes.size() && node.materialIndex<out.materials.size(),"KC3D node reference invalid");
        out.nodes.push_back(std::move(node));
    }
    require(r.remaining()==0,"KC3D trailing bytes");
    return out;
}

ScenePack parseScenePack(const std::vector<std::uint8_t>& data) {
    return parseScenePack(data.data(),data.size());
}

} // namespace kc
