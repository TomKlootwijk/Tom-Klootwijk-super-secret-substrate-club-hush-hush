#pragma once
#include "kc_math.hpp"
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace kc {

struct QualityTier {
    std::string id;
    std::uint16_t targetFps = 60;
    float renderScale = 1.0f;
    std::uint32_t maxVisibleNodes = 256;
    std::uint8_t msaaSamples = 0;
    bool postProcessing = false;
    std::uint8_t shadowQuality = 0;
};

struct TargetProfile {
    std::string id;
    std::string label;
    std::uint16_t minSdk = 26, targetSdk = 36, compileSdk = 36, targetRefreshHz = 60;
    std::uint32_t memoryFloorMb = 3072;
    std::uint8_t glesMajor = 3, glesMinor = 0;
    bool vulkanOptional = true;
    std::vector<std::string> abis;
    std::string defaultQuality;
    std::vector<std::string> deviceHints;
    std::vector<std::string> gpuHints;
};

struct Vertex {
    Vec3 position;
    Vec3 normal;
};

struct MeshData {
    std::string id;
    std::vector<Vertex> vertices;
    std::vector<std::uint32_t> indices;
};

struct MaterialData {
    std::string id;
    std::array<float,4> baseColor{0.8f,0.8f,0.8f,1.0f};
    float metallic = 0.0f;
    float roughness = 0.5f;
    Vec3 emissive{};
    bool doubleSided = false;
};

struct ColliderData {
    std::uint8_t type = 0;
    bool sensor = false;
    float radius = 0.5f;
    Vec3 halfExtents{0.5f,0.5f,0.5f};
};

struct NodeData {
    std::string id;
    std::uint32_t meshIndex = 0;
    std::uint32_t materialIndex = 0;
    Vec3 translation{};
    Quat rotation{};
    Vec3 scale{1.0f,1.0f,1.0f};
    Vec3 velocity{};
    Vec3 angularVelocity{};
    ColliderData collider{};
    bool dynamic = false;
    float mass = 1.0f;
    float restitution = 0.35f;
    std::uint32_t tagMask = 0;
    bool alive = true;
};

struct ScenePack {
    std::array<float,4> background{};
    Vec3 cameraPosition{}, cameraTarget{}, cameraUp{0,1,0};
    float cameraFovDegrees = 55, cameraNear = 0.05f, cameraFar = 250;
    Vec3 lightDirection{}, lightColor{1,1,1};
    float lightIntensity = 1, ambient = 0.18f;
    float fixedDt = 1.0f/120.0f;
    Vec3 gravity{0,-9.81f,0};
    float floorY = 0;
    Vec3 boundsMin{-24,-8,-24}, boundsMax{24,28,24};
    float playerSpeed = 6, jumpSpeed = 7.5f;
    std::string projectHash, projectId, title, author, startQuality;
    std::vector<QualityTier> qualities;
    std::vector<TargetProfile> targets;
    std::vector<MeshData> meshes;
    std::vector<MaterialData> materials;
    std::vector<NodeData> nodes;
};

ScenePack parseScenePack(const std::uint8_t* data, std::size_t size);
ScenePack parseScenePack(const std::vector<std::uint8_t>& data);

constexpr std::uint32_t TagPlayer = 1u << 0;
constexpr std::uint32_t TagCollectible = 1u << 1;
constexpr std::uint32_t TagGoal = 1u << 2;
constexpr std::uint32_t TagDecorative = 1u << 3;
constexpr std::uint32_t TagHazard = 1u << 4;

} // namespace kc
