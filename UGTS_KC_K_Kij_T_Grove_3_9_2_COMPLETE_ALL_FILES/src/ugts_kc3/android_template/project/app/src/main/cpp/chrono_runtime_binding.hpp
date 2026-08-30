#pragma once

// The exporter replaces this template fallback with a generated, immutable
// APK-asset ledger. Keeping the same interface makes the editable Android
// template independently buildable without weakening exported verification.

#include <array>
#include <cstdint>
#include <string_view>

namespace kc::chrono_runtime_binding {

struct AssetBinding {
    std::string_view path;
    std::uint64_t bytes;
    std::array<std::uint8_t,32> sha256;
};

inline constexpr bool kPresent=false;
inline constexpr std::string_view kManifestAssetPath{};
inline constexpr std::string_view kManifestSha256Hex{};
inline constexpr std::array<std::uint8_t,32> kManifestSha256{};
inline constexpr std::array<AssetBinding,0> kAssets{};

constexpr const AssetBinding* find(std::string_view path) {
    for (const auto& asset:kAssets) if (asset.path==path) return &asset;
    return nullptr;
}

} // namespace kc::chrono_runtime_binding
