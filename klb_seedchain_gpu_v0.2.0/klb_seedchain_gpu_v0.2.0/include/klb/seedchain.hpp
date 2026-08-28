#pragma once

#include "klb/format.hpp"

#include <cstdint>
#include <filesystem>
#include <vector>

namespace klb {

constexpr std::uint32_t kSeedChainVersion = 1u;
constexpr std::uint32_t kSeedChainMaxCheckpointStride = 64u;
constexpr std::uint32_t kNoParentNode = 0xffffffffu;

constexpr std::uint32_t kSeedChainFlagEmbeddedBase = 1u << 0u;
constexpr std::uint32_t kSeedChainFlagHashLinked = 1u << 1u;
constexpr std::uint32_t kSeedChainFlagSparseNovelty = 1u << 2u;
constexpr std::uint32_t kSeedChainFlagNodePredictor = 1u << 3u;
constexpr std::uint32_t kSeedChainFlagCheckpointSnapshots = 1u << 4u;

constexpr std::uint32_t kSeedNodeCheckpoint = 1u << 0u;
constexpr std::uint32_t kSeedNodeHasNovelty = 1u << 1u;
constexpr std::uint32_t kSeedNodeExternalFit = 1u << 2u;

constexpr std::uint16_t kNoveltyFlagSnapshot = 1u << 0u;
constexpr std::uint16_t kNoveltyFlagDelta = 1u << 1u;

#pragma pack(push, 1)
struct SeedChainNodeDisk {
    std::uint32_t parent_index;
    std::uint32_t frame_index;
    std::uint32_t chain_seed;
    std::uint32_t flags;

    float time_seconds;
    float angle;
    float angular_velocity;
    float angular_acceleration;

    float log2_scale;
    float translate_x;
    float translate_y;
    float translate_z;

    float cone_phase;
    float branch_amplitude;
    std::uint32_t novelty_begin;
    std::uint32_t novelty_count;

    std::uint32_t checkpoint_index;
    std::uint32_t depth_from_checkpoint;
    std::uint64_t parent_hash;
    std::uint64_t self_hash;

    std::uint32_t reserved[2];
};

struct SeedNoveltyDisk {
    std::uint32_t point_index;
    std::int16_t dx;
    std::int16_t dy;
    std::int16_t dz;
    std::uint16_t flags;
    std::uint32_t event_seed;
};

struct SeedChainHeaderDisk {
    char magic[8];
    std::uint32_t version;
    std::uint32_t header_bytes;

    std::uint64_t node_count;
    std::uint64_t novelty_count;
    std::uint64_t nodes_offset;
    std::uint64_t novelty_offset;
    std::uint64_t base_words_offset;

    std::uint32_t node_bytes;
    std::uint32_t novelty_bytes;
    std::uint32_t checkpoint_stride;
    std::uint32_t flags;

    float novelty_quantum;
    float frames_per_second;
    float default_guard_epsilon;
    float reserved_float;

    std::uint64_t chain_hash;
    std::uint64_t source_sequence_bytes;

    FileHeaderDisk base_header;
    std::uint8_t reserved[24];
};
#pragma pack(pop)

static_assert(sizeof(SeedChainNodeDisk) == 96u, "seed-chain nodes must stay 96 bytes");
static_assert(sizeof(SeedNoveltyDisk) == 16u, "seed novelty records must stay 16 bytes");
static_assert(sizeof(SeedChainHeaderDisk) == 256u, "seed-chain header must stay 256 bytes");

struct SeedChainData {
    SeedChainHeaderDisk header{};
    std::vector<SeedChainNodeDisk> nodes;
    std::vector<SeedNoveltyDisk> novelties;
    std::vector<std::uint32_t> base_words;
};

struct SeedChainBuildOptions {
    std::uint32_t frames = 240u;
    std::uint32_t checkpoint_stride = 16u;
    std::uint32_t seed = 0x4b4c4237u;
    float frames_per_second = 60.0f;
    float branch_amplitude_ratio = 0.0125f;
    float novelty_rate = 0.001f;
    float novelty_quantum_ratio = 0.0001f;
    float novelty_impulse_ratio = 0.004f;
    std::uint32_t novelty_lifetime = 8u;
};

struct SeedChainSequenceOptions {
    std::uint32_t checkpoint_stride = 16u;
    std::uint32_t seed = 0x53455131u;
    float frames_per_second = 60.0f;
    float log_k = 15.0f;
    float novelty_quantum_ratio = 0.0001f;
    float residual_threshold_ratio = 0.002f;
};

struct SeedChainStats {
    std::uint64_t points{};
    std::uint64_t frames{};
    std::uint64_t base_bytes{};
    std::uint64_t node_bytes{};
    std::uint64_t novelty_bytes{};
    std::uint64_t file_bytes{};
    std::uint64_t dense_float3_sequence_bytes{};
    std::uint64_t dense_float4_sequence_bytes{};
    double bytes_per_point_frame{};
    double ratio_vs_float3_sequence{};
    double ratio_vs_float4_sequence{};
    double novelty_records_per_frame{};
    double novelty_record_density{};
    std::uint32_t maximum_chain_depth{};
};


struct SeedChainErrorStats {
    std::uint64_t points{};
    std::uint64_t frames{};
    double rms_error{};
    double maximum_error{};
    double rms_error_over_radius{};
    double maximum_error_over_radius{};
    std::uint32_t worst_frame{};
    std::uint32_t worst_point{};
};

struct SeedChainView {
    const std::uint32_t* base_words{};
    const SeedChainNodeDisk* nodes{};
    const SeedNoveltyDisk* novelties{};
    DecodeParams decode{};
    std::uint64_t record_count{};
    std::uint64_t padded_count{};
    std::uint32_t grid_width{};
    std::uint32_t grid_height{};
    std::uint32_t checkpoint_stride{};
    std::uint32_t base_swizzled{};
    float novelty_quantum{};
};

struct SeedDecodedRecord {
    Vec3 position{};
    std::uint32_t lineage{};
    std::uint32_t route{};
    std::uint32_t symbol{};
};

SeedChainData build_seedchain(const PackedData& base, const SeedChainBuildOptions& options = {});
SeedChainData build_seedchain_sequence(
    const std::vector<std::vector<Vec3>>& frames,
    std::uint64_t source_sequence_bytes,
    const SeedChainSequenceOptions& options = {});
void validate_seedchain(const SeedChainData& chain, bool verify_hashes = true);
void save_seedchain(const std::filesystem::path& path, const SeedChainData& chain);
SeedChainData load_seedchain(const std::filesystem::path& path);
SeedChainStats inspect_seedchain(const SeedChainData& chain, std::uint64_t actual_file_bytes = 0u);
SeedChainView make_seedchain_view(const SeedChainData& chain);
SeedChainErrorStats compare_seedchain_sequence(
    const SeedChainData& chain,
    const std::vector<std::vector<Vec3>>& reference_frames);

std::vector<Vec3> reconstruct_seedchain_frame(
    const SeedChainData& chain,
    std::uint32_t frame_index,
    bool include_padding = false);

KLB_HD KLB_INLINE std::uint64_t seedchain_base_code(const SeedChainView& view, std::uint64_t logical_index) {
    const std::uint64_t physical = view.base_swizzled != 0u ? xor_swizzle_16x16(logical_index) : logical_index;
    return read_bits37(view.base_words, physical);
}

KLB_HD KLB_INLINE Vec3 seedchain_lookup_novelty(
    const SeedChainView& view,
    const SeedChainNodeDisk& node,
    std::uint32_t point_index) {
    std::uint32_t begin = node.novelty_begin;
    std::uint32_t end = begin + node.novelty_count;
    while (begin < end) {
        const std::uint32_t middle = begin + ((end - begin) >> 1u);
        const SeedNoveltyDisk patch = view.novelties[middle];
        if (patch.point_index < point_index) {
            begin = middle + 1u;
        } else {
            end = middle;
        }
    }
    if (begin < node.novelty_begin + node.novelty_count) {
        const SeedNoveltyDisk patch = view.novelties[begin];
        if (patch.point_index == point_index) {
            return {
                static_cast<float>(patch.dx) * view.novelty_quantum,
                static_cast<float>(patch.dy) * view.novelty_quantum,
                static_cast<float>(patch.dz) * view.novelty_quantum,
            };
        }
    }
    return {};
}

KLB_HD KLB_INLINE Vec3 seedchain_accumulate_novelty(
    const SeedChainView& view,
    std::uint32_t node_index,
    std::uint32_t point_index) {
    Vec3 accumulated{};
    std::uint32_t current = node_index;
    for (std::uint32_t step = 0u; step <= kSeedChainMaxCheckpointStride; ++step) {
        const SeedChainNodeDisk node = view.nodes[current];
        accumulated = accumulated + seedchain_lookup_novelty(view, node, point_index);
        if ((node.flags & kSeedNodeCheckpoint) != 0u || node.parent_index == kNoParentNode) {
            break;
        }
        current = node.parent_index;
    }
    return accumulated;
}

KLB_HD KLB_INLINE SeedDecodedRecord reconstruct_seedchain_point(
    const SeedChainView& view,
    std::uint32_t node_index,
    std::uint32_t point_index) {
    constexpr float kTwoPi = 6.28318530717958647692f;
    const SeedChainNodeDisk node = view.nodes[node_index];
    const std::uint64_t code = seedchain_base_code(view, point_index);
    const DecodedRecord decoded = decode_record(code, view.decode);

    const std::uint32_t stored_symbol = record_symbol(code);
    const std::uint32_t stored_parity = record_stored_parity(code);
    std::uint32_t route_key = mix32(node.chain_seed ^ point_index ^ decoded.meta);
    std::uint32_t symbol = stored_symbol;
    std::uint32_t route = stored_parity;

    // A flat, pointer-free grammar/BST walk. The number of productions is fixed,
    // while the bits are lineage- and frame-seed-dependent.
    for (std::uint32_t level = 0u; level < 4u; ++level) {
        const std::uint32_t branch =
            (parity32(route_key ^ (level * 0x9e3779b9u) ^ symbol) ^ route) & 1u;
        symbol = (symbol * 5u + branch + level + (route_key >> (level * 3u))) & 7u;
        route = branch;
        route_key = mix32(route_key ^ symbol ^ (branch * 0x85ebca6bu));
    }

    const std::uint32_t q_theta =
        static_cast<std::uint32_t>((code >> kThetaShift) & kThetaMask);
    const std::uint32_t q_phi =
        static_cast<std::uint32_t>((code >> kPhiShift) & kPhiMask);
    const std::int32_t signed_theta_shift =
        static_cast<std::int32_t>((node.chain_seed >> 5u) & 127u) - 63 +
        static_cast<std::int32_t>(node.frame_index * (route != 0u ? 3u : 2u));
    const std::int32_t signed_phi_shift =
        static_cast<std::int32_t>((node.chain_seed >> 17u) & 31u) - 15 +
        static_cast<std::int32_t>(symbol) - 3;
    const KleinCoordinate klein = klein_coordinate(
        static_cast<std::int64_t>(q_theta) + signed_theta_shift,
        static_cast<std::int64_t>(q_phi) + signed_phi_shift,
        static_cast<std::uint32_t>(std::uint32_t{1} << kThetaBits),
        static_cast<std::uint32_t>(std::uint32_t{1} << kPhiBits));

    const float topology_phase =
        static_cast<float>(klein.x) * (kTwoPi / static_cast<float>(std::uint32_t{1} << kThetaBits));
    const float orientation = klein.reflected != 0u ? -1.0f : 1.0f;
    const float branch_sign = route != 0u ? 1.0f : -1.0f;

    Vec3 local{
        decoded.position.x - view.decode.center_x,
        decoded.position.y - view.decode.center_y,
        decoded.position.z - view.decode.center_z,
    };
    const float radial = ::sqrtf(local.x * local.x + local.z * local.z);
    const float inv_radial = radial > 1.0e-20f ? 1.0f / radial : 0.0f;
    const Vec3 outward{local.x * inv_radial, 0.0f, local.z * inv_radial};

    const float cone_phi =
        0.42f + 0.16f * ::sinf(node.cone_phase + topology_phase + 0.17f * static_cast<float>(symbol));
    const float cone_field = radial * ::cosf(cone_phi) - local.y * ::sinf(cone_phi);
    const float grammar_wave =
        ::sinf(topology_phase + node.cone_phase + 0.71f * static_cast<float>(symbol));
    const float deformation =
        node.branch_amplitude * branch_sign * orientation * grammar_wave *
        (1.0f + 0.25f * ::tanhf(cone_field));

    local = local + outward * deformation;
    local.y += 0.45f * deformation * ::cosf(topology_phase + 0.23f * static_cast<float>(symbol));

    float angle = node.angle;
    if ((node.flags & kSeedNodeExternalFit) == 0u) {
        angle += branch_sign * 0.013f * static_cast<float>(symbol) +
                 orientation * 0.006f * static_cast<float>(node.depth_from_checkpoint);
    }
    const float sin_angle = ::sinf(angle);
    const float cos_angle = ::cosf(angle);
    const float scale = ::exp2f(node.log2_scale);
    const Vec3 rotated{
        scale * (cos_angle * local.x - sin_angle * local.z),
        scale * local.y,
        scale * (sin_angle * local.x + cos_angle * local.z),
    };

    const Vec3 novelty = seedchain_accumulate_novelty(view, node_index, point_index);
    const Vec3 position{
        view.decode.center_x + rotated.x + node.translate_x + novelty.x,
        view.decode.center_y + rotated.y + node.translate_y + novelty.y,
        view.decode.center_z + rotated.z + node.translate_z + novelty.z,
    };
    const std::uint32_t lineage = mix32(
        decoded.meta ^ node.chain_seed ^ point_index ^ (symbol << 24u) ^ (route << 31u));
    return {position, lineage, route, symbol};
}

} // namespace klb
