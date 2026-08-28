#include "klb/seedchain.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace klb {
namespace {

constexpr std::array<char, 8> kSeedChainMagic{'K', 'L', 'S', 'C', '3', '7', '0', '1'};
constexpr std::uint64_t kFnvOffset = 1469598103934665603ull;
constexpr std::uint64_t kFnvPrime = 1099511628211ull;

void require_little_endian() {
    if constexpr (std::endian::native != std::endian::little) {
        throw std::runtime_error("KLSC1 currently supports little-endian hosts only");
    }
}

std::uint64_t fnv_append(std::uint64_t hash, const void* data, std::size_t size) {
    const auto* bytes = static_cast<const std::uint8_t*>(data);
    for (std::size_t i = 0; i < size; ++i) {
        hash ^= bytes[i];
        hash *= kFnvPrime;
    }
    return hash;
}

std::uint64_t hash_node(
    const SeedChainNodeDisk& source,
    const std::vector<SeedNoveltyDisk>& novelties) {
    SeedChainNodeDisk node = source;
    node.self_hash = 0u;
    std::uint64_t hash = fnv_append(kFnvOffset, &node, sizeof(node));
    if (node.novelty_count != 0u) {
        const std::size_t begin = node.novelty_begin;
        const std::size_t count = node.novelty_count;
        hash = fnv_append(hash, novelties.data() + begin, count * sizeof(SeedNoveltyDisk));
    }
    return hash;
}

std::int16_t checked_i16(std::int32_t value, const char* field) {
    if (value < std::numeric_limits<std::int16_t>::min() ||
        value > std::numeric_limits<std::int16_t>::max()) {
        throw std::overflow_error(std::string("seed novelty ") + field +
                                  " exceeds int16 range; increase --novelty-quantum");
    }
    return static_cast<std::int16_t>(value);
}

struct QuantizedDelta {
    std::int32_t x{};
    std::int32_t y{};
    std::int32_t z{};
};

QuantizedDelta operator+(const QuantizedDelta& a, const QuantizedDelta& b) {
    return {a.x + b.x, a.y + b.y, a.z + b.z};
}

QuantizedDelta operator-(const QuantizedDelta& a) {
    return {-a.x, -a.y, -a.z};
}

bool is_zero(const QuantizedDelta& value) {
    return value.x == 0 && value.y == 0 && value.z == 0;
}

void add_to_map(
    std::map<std::uint32_t, QuantizedDelta>& values,
    std::uint32_t point_index,
    const QuantizedDelta& delta) {
    QuantizedDelta& destination = values[point_index];
    destination = destination + delta;
    if (is_zero(destination)) {
        values.erase(point_index);
    }
}

std::uint32_t nonzero_component(std::uint32_t value, std::uint32_t span) {
    if (span == 0u) {
        return 1u;
    }
    const std::uint32_t component = value % (2u * span + 1u);
    return component == span ? span + 1u : component;
}

QuantizedDelta make_impulse(std::uint32_t key, std::uint32_t impulse_q) {
    const std::int32_t span = static_cast<std::int32_t>(std::max(impulse_q, 1u));
    auto component = [&](std::uint32_t shift) -> std::int32_t {
        const std::uint32_t mixed = mix32(key ^ (shift * 0x9e3779b9u));
        const std::uint32_t raw = nonzero_component(mixed, static_cast<std::uint32_t>(span));
        return static_cast<std::int32_t>(raw) - span;
    };
    QuantizedDelta result{component(1u), component(2u), component(3u)};
    if (is_zero(result)) {
        result.x = 1;
    }
    return result;
}

void append_patch(
    std::vector<SeedNoveltyDisk>& destination,
    std::uint32_t point_index,
    const QuantizedDelta& value,
    std::uint16_t flags,
    std::uint32_t event_seed) {
    if (is_zero(value)) {
        return;
    }
    SeedNoveltyDisk patch{};
    patch.point_index = point_index;
    patch.dx = checked_i16(value.x, "dx");
    patch.dy = checked_i16(value.y, "dy");
    patch.dz = checked_i16(value.z, "dz");
    patch.flags = flags;
    patch.event_seed = event_seed;
    destination.push_back(patch);
}

std::uint64_t canonical_file_size(const SeedChainData& chain) {
    return static_cast<std::uint64_t>(sizeof(SeedChainHeaderDisk)) +
           static_cast<std::uint64_t>(chain.nodes.size() * sizeof(SeedChainNodeDisk)) +
           static_cast<std::uint64_t>(chain.novelties.size() * sizeof(SeedNoveltyDisk)) +
           static_cast<std::uint64_t>(chain.base_words.size() * sizeof(std::uint32_t));
}

struct SimilarityY {
    float angle{};
    float scale{1.0f};
    Vec3 translation{};
};

SimilarityY fit_similarity_y(
    const std::vector<Vec3>& base,
    const std::vector<Vec3>& target,
    const Vec3& rotation_center) {
    if (base.size() != target.size() || base.empty()) {
        throw std::invalid_argument("similarity fit requires equally sized non-empty point sets");
    }

    Vec3 mean_base{};
    Vec3 mean_target{};
    for (std::size_t i = 0; i < base.size(); ++i) {
        mean_base = mean_base + base[i];
        mean_target = mean_target + target[i];
    }
    const float inv_count = 1.0f / static_cast<float>(base.size());
    mean_base = mean_base * inv_count;
    mean_target = mean_target * inv_count;

    long double a = 0.0L;
    long double b = 0.0L;
    for (std::size_t i = 0; i < base.size(); ++i) {
        const Vec3 source = base[i] - mean_base;
        const Vec3 destination = target[i] - mean_target;
        a += static_cast<long double>(source.x) * destination.x +
             static_cast<long double>(source.z) * destination.z;
        b += static_cast<long double>(source.x) * destination.z -
             static_cast<long double>(source.z) * destination.x;
    }
    const float angle = static_cast<float>(std::atan2(b, a));
    const float sine = std::sinf(angle);
    const float cosine = std::cosf(angle);

    long double numerator = 0.0L;
    long double denominator = 0.0L;
    for (std::size_t i = 0; i < base.size(); ++i) {
        const Vec3 source = base[i] - mean_base;
        const Vec3 destination = target[i] - mean_target;
        const Vec3 rotated{
            cosine * source.x - sine * source.z,
            source.y,
            sine * source.x + cosine * source.z,
        };
        numerator += static_cast<long double>(rotated.x) * destination.x +
                     static_cast<long double>(rotated.y) * destination.y +
                     static_cast<long double>(rotated.z) * destination.z;
        denominator += static_cast<long double>(source.x) * source.x +
                       static_cast<long double>(source.y) * source.y +
                       static_cast<long double>(source.z) * source.z;
    }
    float scale = denominator > 1.0e-30L
        ? static_cast<float>(numerator / denominator)
        : 1.0f;
    if (!(scale > 1.0e-8f) || !std::isfinite(scale)) {
        scale = 1.0f;
    }

    const Vec3 mean_local = mean_base - rotation_center;
    const Vec3 transformed_mean{
        scale * (cosine * mean_local.x - sine * mean_local.z),
        scale * mean_local.y,
        scale * (sine * mean_local.x + cosine * mean_local.z),
    };
    const Vec3 translation{
        mean_target.x - rotation_center.x - transformed_mean.x,
        mean_target.y - rotation_center.y - transformed_mean.y,
        mean_target.z - rotation_center.z - transformed_mean.z,
    };
    return {angle, scale, translation};
}

Vec3 apply_similarity_y(const Vec3& point, const Vec3& center, const SimilarityY& transform) {
    const Vec3 local = point - center;
    const float sine = std::sinf(transform.angle);
    const float cosine = std::cosf(transform.angle);
    return {
        center.x + transform.scale * (cosine * local.x - sine * local.z) + transform.translation.x,
        center.y + transform.scale * local.y + transform.translation.y,
        center.z + transform.scale * (sine * local.x + cosine * local.z) + transform.translation.z,
    };
}

QuantizedDelta quantize_residual(const Vec3& residual, float quantum, float threshold) {
    if (length(residual) <= threshold) {
        return {};
    }
    return {
        static_cast<std::int32_t>(std::llround(static_cast<double>(residual.x / quantum))),
        static_cast<std::int32_t>(std::llround(static_cast<double>(residual.y / quantum))),
        static_cast<std::int32_t>(std::llround(static_cast<double>(residual.z / quantum))),
    };
}

void initialize_header(
    SeedChainData& chain,
    const PackedData& base,
    std::uint32_t checkpoint_stride,
    float fps,
    float novelty_quantum,
    std::uint64_t source_sequence_bytes) {
    std::memcpy(chain.header.magic, kSeedChainMagic.data(), kSeedChainMagic.size());
    chain.header.version = kSeedChainVersion;
    chain.header.header_bytes = sizeof(SeedChainHeaderDisk);
    chain.header.node_bytes = sizeof(SeedChainNodeDisk);
    chain.header.novelty_bytes = sizeof(SeedNoveltyDisk);
    chain.header.checkpoint_stride = checkpoint_stride;
    chain.header.flags =
        kSeedChainFlagEmbeddedBase |
        kSeedChainFlagHashLinked |
        kSeedChainFlagSparseNovelty |
        kSeedChainFlagNodePredictor |
        kSeedChainFlagCheckpointSnapshots;
    chain.header.frames_per_second = fps;
    chain.header.default_guard_epsilon = std::max(base.header.radius_scale * 0.01f, 1.0e-6f);
    chain.header.base_header = base.header;
    chain.header.novelty_quantum = novelty_quantum;
    chain.header.source_sequence_bytes = source_sequence_bytes;
}

void finalize_header(SeedChainData& chain) {
    chain.header.node_count = chain.nodes.size();
    chain.header.novelty_count = chain.novelties.size();
    chain.header.nodes_offset = sizeof(SeedChainHeaderDisk);
    chain.header.novelty_offset =
        chain.header.nodes_offset + chain.nodes.size() * sizeof(SeedChainNodeDisk);
    chain.header.base_words_offset =
        chain.header.novelty_offset + chain.novelties.size() * sizeof(SeedNoveltyDisk);
    chain.header.chain_hash = chain.nodes.back().self_hash;
}

} // namespace

SeedChainData build_seedchain(const PackedData& base, const SeedChainBuildOptions& options) {
    require_little_endian();
    if (base.header.record_count == 0u || base.words.empty()) {
        throw std::invalid_argument("seed-chain base must contain packed records");
    }
    if (base.header.record_count > std::numeric_limits<std::uint32_t>::max()) {
        throw std::invalid_argument("seed-chain base has too many points for 32-bit novelty indices");
    }
    if (base.words.size() != base.header.word_count) {
        throw std::invalid_argument("seed-chain base word count does not match its header");
    }
    if (options.frames == 0u) {
        throw std::invalid_argument("seed-chain frame count must be non-zero");
    }
    if (options.checkpoint_stride == 0u ||
        options.checkpoint_stride > kSeedChainMaxCheckpointStride) {
        throw std::invalid_argument("checkpoint stride must be in the range 1..64");
    }
    if (!(options.frames_per_second > 0.0f) || !std::isfinite(options.frames_per_second)) {
        throw std::invalid_argument("frames per second must be finite and greater than zero");
    }
    if (options.novelty_rate < 0.0f || !std::isfinite(options.novelty_rate)) {
        throw std::invalid_argument("novelty rate must be finite and non-negative");
    }
    if (!(options.novelty_quantum_ratio > 0.0f) || !std::isfinite(options.novelty_quantum_ratio)) {
        throw std::invalid_argument("novelty quantum ratio must be finite and greater than zero");
    }

    SeedChainData chain{};
    chain.nodes.reserve(options.frames);
    chain.base_words = base.words;
    const float novelty_quantum =
        std::max(base.header.radius_scale * options.novelty_quantum_ratio, 1.0e-9f);
    initialize_header(chain, base, options.checkpoint_stride, options.frames_per_second,
                      novelty_quantum, 0u);

    const std::uint32_t point_count = static_cast<std::uint32_t>(base.header.record_count);
    const double requested_events = static_cast<double>(point_count) * options.novelty_rate;
    const std::uint32_t events_per_frame = static_cast<std::uint32_t>(std::llround(requested_events));
    const float impulse_world = base.header.radius_scale * options.novelty_impulse_ratio;
    const std::uint32_t impulse_q = static_cast<std::uint32_t>(std::max(
        1.0,
        std::round(static_cast<double>(impulse_world / novelty_quantum))));
    const std::uint32_t lifetime = std::max(options.novelty_lifetime, 1u);

    std::vector<QuantizedDelta> residuals(point_count);
    std::vector<std::vector<std::pair<std::uint32_t, QuantizedDelta>>> scheduled(
        static_cast<std::size_t>(options.frames) + lifetime + 1u);

    std::uint64_t previous_hash = base.header.payload_hash;
    std::uint32_t previous_seed = options.seed;

    for (std::uint32_t frame = 0u; frame < options.frames; ++frame) {
        std::map<std::uint32_t, QuantizedDelta> frame_deltas;
        for (const auto& [point_index, delta] : scheduled[frame]) {
            residuals[point_index] = residuals[point_index] + delta;
            add_to_map(frame_deltas, point_index, delta);
        }

        if (frame != 0u && events_per_frame != 0u && impulse_world > 0.0f) {
            for (std::uint32_t event = 0u; event < events_per_frame; ++event) {
                const std::uint32_t event_key = mix32(
                    options.seed ^ (frame * 0x9e3779b9u) ^ (event * 0x85ebca6bu));
                const std::uint32_t point_index = event_key % point_count;
                const QuantizedDelta impulse = make_impulse(event_key, impulse_q);
                residuals[point_index] = residuals[point_index] + impulse;
                add_to_map(frame_deltas, point_index, impulse);
                const std::uint32_t removal_frame = frame + lifetime;
                if (removal_frame < scheduled.size()) {
                    scheduled[removal_frame].push_back({point_index, -impulse});
                }
            }
        }

        SeedChainNodeDisk node{};
        node.parent_index = frame == 0u ? kNoParentNode : frame - 1u;
        node.frame_index = frame;
        node.chain_seed = mix32(previous_seed ^ frame ^ 0x53454544u);
        const bool checkpoint = (frame % options.checkpoint_stride) == 0u;
        node.flags = checkpoint ? kSeedNodeCheckpoint : 0u;

        const float time = static_cast<float>(frame) / options.frames_per_second;
        node.time_seconds = time;
        node.angular_acceleration = 0.0040f;
        node.angular_velocity = 0.17f + node.angular_acceleration * time;
        node.angle = 0.17f * time + 0.5f * node.angular_acceleration * time * time;
        node.log2_scale = 0.024f * std::sinf(0.73f * time);
        node.translate_x = base.header.radius_scale * 0.025f * std::sinf(0.41f * time);
        node.translate_y = base.header.radius_scale * 0.018f * std::sinf(0.63f * time + 0.7f);
        node.translate_z = base.header.radius_scale * 0.025f * std::cosf(0.37f * time);
        node.cone_phase = 0.83f * time + 0.12f * std::sinf(0.29f * time);
        node.branch_amplitude =
            base.header.radius_scale * options.branch_amplitude_ratio *
            (0.80f + 0.20f * std::sinf(0.51f * time + 0.3f));
        node.novelty_begin = static_cast<std::uint32_t>(chain.novelties.size());
        node.checkpoint_index = frame - (frame % options.checkpoint_stride);
        node.depth_from_checkpoint = frame % options.checkpoint_stride;
        node.parent_hash = previous_hash;

        if (checkpoint) {
            for (std::uint32_t point_index = 0u; point_index < point_count; ++point_index) {
                append_patch(chain.novelties, point_index, residuals[point_index],
                             kNoveltyFlagSnapshot, mix32(node.chain_seed ^ point_index));
            }
        } else {
            for (const auto& [point_index, delta] : frame_deltas) {
                append_patch(chain.novelties, point_index, delta,
                             kNoveltyFlagDelta, mix32(node.chain_seed ^ point_index));
            }
        }

        node.novelty_count =
            static_cast<std::uint32_t>(chain.novelties.size()) - node.novelty_begin;
        if (node.novelty_count != 0u) {
            node.flags |= kSeedNodeHasNovelty;
        }
        node.self_hash = hash_node(node, chain.novelties);
        previous_hash = node.self_hash;
        previous_seed = node.chain_seed;
        chain.nodes.push_back(node);
    }

    finalize_header(chain);
    validate_seedchain(chain, true);
    return chain;
}

SeedChainData build_seedchain_sequence(
    const std::vector<std::vector<Vec3>>& frames,
    std::uint64_t source_sequence_bytes,
    const SeedChainSequenceOptions& options) {
    require_little_endian();
    if (frames.empty() || frames.front().empty()) {
        throw std::invalid_argument("PLY sequence must contain at least one non-empty frame");
    }
    if (frames.size() > std::numeric_limits<std::uint32_t>::max() ||
        frames.front().size() > std::numeric_limits<std::uint32_t>::max()) {
        throw std::invalid_argument("sequence exceeds KLSC1 32-bit frame or point index limits");
    }
    for (std::size_t frame = 1; frame < frames.size(); ++frame) {
        if (frames[frame].size() != frames.front().size()) {
            throw std::invalid_argument(
                "all PLY sequence frames must have identical vertex counts and stable vertex order");
        }
    }
    if (options.checkpoint_stride == 0u ||
        options.checkpoint_stride > kSeedChainMaxCheckpointStride) {
        throw std::invalid_argument("sequence checkpoint stride must be in the range 1..64");
    }
    if (!(options.frames_per_second > 0.0f) || !std::isfinite(options.frames_per_second) ||
        !(options.log_k > 0.0f) || !std::isfinite(options.log_k) ||
        !(options.novelty_quantum_ratio > 0.0f) || !std::isfinite(options.novelty_quantum_ratio) ||
        options.residual_threshold_ratio < 0.0f || !std::isfinite(options.residual_threshold_ratio)) {
        throw std::invalid_argument("invalid sequence FPS, log-k, novelty quantum or residual threshold");
    }

    const PackedData base = pack_points_ordered(frames.front(), 0u, options.log_k);
    const std::vector<Vec3> decoded_base = unpack_points(base);
    const Vec3 center{base.header.center[0], base.header.center[1], base.header.center[2]};

    SeedChainData chain{};
    chain.nodes.reserve(frames.size());
    chain.base_words = base.words;
    const float novelty_quantum =
        std::max(base.header.radius_scale * options.novelty_quantum_ratio, 1.0e-9f);
    initialize_header(chain, base, options.checkpoint_stride, options.frames_per_second,
                      novelty_quantum, source_sequence_bytes);

    const float residual_threshold =
        base.header.radius_scale * options.residual_threshold_ratio;
    std::vector<QuantizedDelta> previous_residual(decoded_base.size());
    std::uint64_t previous_hash = base.header.payload_hash;
    std::uint32_t previous_seed = options.seed;
    float previous_angle = 0.0f;
    float previous_velocity = 0.0f;

    for (std::uint32_t frame_index = 0u;
         frame_index < static_cast<std::uint32_t>(frames.size());
         ++frame_index) {
        const SimilarityY fit = fit_similarity_y(decoded_base, frames[frame_index], center);
        std::vector<QuantizedDelta> current_residual(decoded_base.size());
        for (std::size_t point = 0; point < decoded_base.size(); ++point) {
            const Vec3 predicted = apply_similarity_y(decoded_base[point], center, fit);
            current_residual[point] = quantize_residual(
                frames[frame_index][point] - predicted,
                novelty_quantum,
                residual_threshold);
        }

        SeedChainNodeDisk node{};
        node.parent_index = frame_index == 0u ? kNoParentNode : frame_index - 1u;
        node.frame_index = frame_index;
        node.chain_seed = mix32(previous_seed ^ frame_index ^ 0x53514555u);
        const bool checkpoint = (frame_index % options.checkpoint_stride) == 0u;
        node.flags = kSeedNodeExternalFit | (checkpoint ? kSeedNodeCheckpoint : 0u);
        node.time_seconds = static_cast<float>(frame_index) / options.frames_per_second;
        node.angle = fit.angle;
        node.angular_velocity = frame_index == 0u
            ? 0.0f
            : (fit.angle - previous_angle) * options.frames_per_second;
        node.angular_acceleration = frame_index <= 1u
            ? 0.0f
            : (node.angular_velocity - previous_velocity) * options.frames_per_second;
        node.log2_scale = std::log2(std::max(fit.scale, 1.0e-8f));
        node.translate_x = fit.translation.x;
        node.translate_y = fit.translation.y;
        node.translate_z = fit.translation.z;
        node.novelty_begin = static_cast<std::uint32_t>(chain.novelties.size());
        node.checkpoint_index = frame_index - (frame_index % options.checkpoint_stride);
        node.depth_from_checkpoint = frame_index % options.checkpoint_stride;
        node.parent_hash = previous_hash;

        for (std::uint32_t point = 0u;
             point < static_cast<std::uint32_t>(current_residual.size());
             ++point) {
            const QuantizedDelta value = checkpoint
                ? current_residual[point]
                : QuantizedDelta{
                    current_residual[point].x - previous_residual[point].x,
                    current_residual[point].y - previous_residual[point].y,
                    current_residual[point].z - previous_residual[point].z,
                };
            append_patch(chain.novelties, point, value,
                         checkpoint ? kNoveltyFlagSnapshot : kNoveltyFlagDelta,
                         mix32(node.chain_seed ^ point));
        }

        node.novelty_count =
            static_cast<std::uint32_t>(chain.novelties.size()) - node.novelty_begin;
        if (node.novelty_count != 0u) {
            node.flags |= kSeedNodeHasNovelty;
        }
        node.self_hash = hash_node(node, chain.novelties);
        chain.nodes.push_back(node);
        previous_residual.swap(current_residual);
        previous_hash = node.self_hash;
        previous_seed = node.chain_seed;
        previous_angle = fit.angle;
        previous_velocity = node.angular_velocity;
    }

    finalize_header(chain);
    validate_seedchain(chain, true);
    return chain;
}

void validate_seedchain(const SeedChainData& chain, bool verify_hashes) {
    require_little_endian();
    if (std::memcmp(chain.header.magic, kSeedChainMagic.data(), kSeedChainMagic.size()) != 0) {
        throw std::runtime_error("not a KLSC37 seed-chain container");
    }
    if (chain.header.version != kSeedChainVersion ||
        chain.header.header_bytes != sizeof(SeedChainHeaderDisk) ||
        chain.header.node_bytes != sizeof(SeedChainNodeDisk) ||
        chain.header.novelty_bytes != sizeof(SeedNoveltyDisk)) {
        throw std::runtime_error("unsupported seed-chain version or record layout");
    }
    if (chain.header.checkpoint_stride == 0u ||
        chain.header.checkpoint_stride > kSeedChainMaxCheckpointStride) {
        throw std::runtime_error("invalid seed-chain checkpoint stride");
    }
    if (chain.nodes.empty() || chain.nodes.size() != chain.header.node_count ||
        chain.novelties.size() != chain.header.novelty_count ||
        chain.base_words.size() != chain.header.base_header.word_count) {
        throw std::runtime_error("seed-chain node, novelty or base word count mismatch");
    }
    if (chain.header.base_header.record_bits != kRecordBits ||
        chain.header.base_header.tile_records != kTileRecords ||
        chain.header.base_header.record_count == 0u ||
        chain.header.base_header.record_count > std::numeric_limits<std::uint32_t>::max() ||
        chain.header.base_header.padded_count < chain.header.base_header.record_count ||
        chain.header.base_header.grid_width == 0u ||
        chain.header.base_header.padded_count % chain.header.base_header.grid_width != 0u) {
        throw std::runtime_error("unsupported or invalid embedded KLB base layout");
    }
    if (!(chain.header.novelty_quantum > 0.0f) || !std::isfinite(chain.header.novelty_quantum)) {
        throw std::runtime_error("invalid seed-chain novelty quantum");
    }

    const std::uint64_t expected_nodes_offset = sizeof(SeedChainHeaderDisk);
    const std::uint64_t expected_novelty_offset =
        expected_nodes_offset + chain.nodes.size() * sizeof(SeedChainNodeDisk);
    const std::uint64_t expected_base_offset =
        expected_novelty_offset + chain.novelties.size() * sizeof(SeedNoveltyDisk);
    if (chain.header.nodes_offset != expected_nodes_offset ||
        chain.header.novelty_offset != expected_novelty_offset ||
        chain.header.base_words_offset != expected_base_offset) {
        throw std::runtime_error("seed-chain offsets do not match the canonical packed layout");
    }

    const std::uint64_t base_hash =
        fnv1a64(chain.base_words.data(), chain.base_words.size() * sizeof(std::uint32_t));
    if (base_hash != chain.header.base_header.payload_hash) {
        throw std::runtime_error("embedded KLB payload hash mismatch");
    }

    std::uint64_t expected_parent_hash = chain.header.base_header.payload_hash;
    for (std::size_t i = 0; i < chain.nodes.size(); ++i) {
        const SeedChainNodeDisk& node = chain.nodes[i];
        if (node.frame_index != i) {
            throw std::runtime_error("seed-chain frame indices must be sequential");
        }
        const std::uint32_t expected_parent =
            i == 0u ? kNoParentNode : static_cast<std::uint32_t>(i - 1u);
        if (node.parent_index != expected_parent) {
            throw std::runtime_error("seed-chain parent link mismatch at frame " + std::to_string(i));
        }
        const std::uint32_t expected_checkpoint =
            static_cast<std::uint32_t>(i) -
            (static_cast<std::uint32_t>(i) % chain.header.checkpoint_stride);
        const std::uint32_t expected_depth =
            static_cast<std::uint32_t>(i) % chain.header.checkpoint_stride;
        if (node.checkpoint_index != expected_checkpoint ||
            node.depth_from_checkpoint != expected_depth ||
            ((node.flags & kSeedNodeCheckpoint) != 0u) != (expected_depth == 0u)) {
            throw std::runtime_error("seed-chain checkpoint metadata mismatch");
        }
        if (node.parent_hash != expected_parent_hash) {
            throw std::runtime_error("seed-chain parent hash mismatch at frame " + std::to_string(i));
        }
        const std::uint64_t novelty_end =
            static_cast<std::uint64_t>(node.novelty_begin) + node.novelty_count;
        if (novelty_end > chain.novelties.size()) {
            throw std::runtime_error("seed-chain novelty range is out of bounds");
        }
        const bool checkpoint = (node.flags & kSeedNodeCheckpoint) != 0u;
        std::uint32_t previous_point = 0u;
        bool first = true;
        for (std::uint32_t j = 0u; j < node.novelty_count; ++j) {
            const SeedNoveltyDisk& patch = chain.novelties[node.novelty_begin + j];
            if (patch.point_index >= chain.header.base_header.record_count ||
                (!first && patch.point_index <= previous_point)) {
                throw std::runtime_error("invalid or unsorted seed novelty point index");
            }
            first = false;
            previous_point = patch.point_index;
            const std::uint16_t expected_flag =
                checkpoint ? kNoveltyFlagSnapshot : kNoveltyFlagDelta;
            if ((patch.flags & expected_flag) == 0u) {
                throw std::runtime_error("seed novelty snapshot/delta flag does not match its node");
            }
        }
        const bool novelty_flag = (node.flags & kSeedNodeHasNovelty) != 0u;
        if (novelty_flag != (node.novelty_count != 0u)) {
            throw std::runtime_error("seed-chain novelty flag/count mismatch");
        }
        if (verify_hashes && hash_node(node, chain.novelties) != node.self_hash) {
            throw std::runtime_error("seed-chain node hash mismatch at frame " + std::to_string(i));
        }
        expected_parent_hash = node.self_hash;
    }
    if (chain.header.chain_hash != chain.nodes.back().self_hash) {
        throw std::runtime_error("seed-chain terminal hash mismatch");
    }
}

void save_seedchain(const std::filesystem::path& path, const SeedChainData& chain) {
    validate_seedchain(chain, true);
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        throw std::runtime_error("failed to create seed-chain file: " + path.string());
    }
    output.write(reinterpret_cast<const char*>(&chain.header), sizeof(chain.header));
    output.write(reinterpret_cast<const char*>(chain.nodes.data()),
                 static_cast<std::streamsize>(chain.nodes.size() * sizeof(SeedChainNodeDisk)));
    output.write(reinterpret_cast<const char*>(chain.novelties.data()),
                 static_cast<std::streamsize>(chain.novelties.size() * sizeof(SeedNoveltyDisk)));
    output.write(reinterpret_cast<const char*>(chain.base_words.data()),
                 static_cast<std::streamsize>(chain.base_words.size() * sizeof(std::uint32_t)));
    if (!output) {
        throw std::runtime_error("failed while writing seed-chain file: " + path.string());
    }
}

SeedChainData load_seedchain(const std::filesystem::path& path) {
    require_little_endian();
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("failed to open seed-chain file: " + path.string());
    }

    SeedChainData chain{};
    input.read(reinterpret_cast<char*>(&chain.header), sizeof(chain.header));
    if (input.gcount() != static_cast<std::streamsize>(sizeof(chain.header)) ||
        std::memcmp(chain.header.magic, kSeedChainMagic.data(), kSeedChainMagic.size()) != 0) {
        throw std::runtime_error("not a complete KLSC37 seed-chain file: " + path.string());
    }
    if (chain.header.version != kSeedChainVersion ||
        chain.header.header_bytes != sizeof(SeedChainHeaderDisk) ||
        chain.header.node_bytes != sizeof(SeedChainNodeDisk) ||
        chain.header.novelty_bytes != sizeof(SeedNoveltyDisk)) {
        throw std::runtime_error("unsupported seed-chain file version or layout");
    }
    constexpr std::uint64_t kMaxNodes = 1u << 24u;
    constexpr std::uint64_t kMaxNovelty = 1ull << 32u;
    constexpr std::uint64_t kMaxWords = 1ull << 34u;
    if (chain.header.node_count == 0u || chain.header.node_count > kMaxNodes ||
        chain.header.novelty_count > kMaxNovelty ||
        chain.header.base_header.word_count < 2u ||
        chain.header.base_header.word_count > kMaxWords) {
        throw std::runtime_error("unreasonable seed-chain record counts");
    }

    chain.nodes.resize(static_cast<std::size_t>(chain.header.node_count));
    chain.novelties.resize(static_cast<std::size_t>(chain.header.novelty_count));
    chain.base_words.resize(static_cast<std::size_t>(chain.header.base_header.word_count));

    input.seekg(static_cast<std::streamoff>(chain.header.nodes_offset), std::ios::beg);
    input.read(reinterpret_cast<char*>(chain.nodes.data()),
               static_cast<std::streamsize>(chain.nodes.size() * sizeof(SeedChainNodeDisk)));
    if (!input) throw std::runtime_error("seed-chain node table is truncated");

    input.seekg(static_cast<std::streamoff>(chain.header.novelty_offset), std::ios::beg);
    input.read(reinterpret_cast<char*>(chain.novelties.data()),
               static_cast<std::streamsize>(chain.novelties.size() * sizeof(SeedNoveltyDisk)));
    if (!input) throw std::runtime_error("seed-chain novelty table is truncated");

    input.seekg(static_cast<std::streamoff>(chain.header.base_words_offset), std::ios::beg);
    input.read(reinterpret_cast<char*>(chain.base_words.data()),
               static_cast<std::streamsize>(chain.base_words.size() * sizeof(std::uint32_t)));
    if (!input) throw std::runtime_error("seed-chain embedded KLB stream is truncated");

    std::error_code error;
    const std::uint64_t actual_bytes = std::filesystem::file_size(path, error);
    if (!error && actual_bytes != canonical_file_size(chain)) {
        throw std::runtime_error("seed-chain file size does not match its canonical layout");
    }
    validate_seedchain(chain, true);
    return chain;
}

SeedChainStats inspect_seedchain(const SeedChainData& chain, std::uint64_t actual_file_bytes) {
    validate_seedchain(chain, false);
    SeedChainStats stats{};
    stats.points = chain.header.base_header.record_count;
    stats.frames = chain.nodes.size();
    stats.base_bytes = chain.base_words.size() * sizeof(std::uint32_t);
    stats.node_bytes = chain.nodes.size() * sizeof(SeedChainNodeDisk);
    stats.novelty_bytes = chain.novelties.size() * sizeof(SeedNoveltyDisk);
    stats.file_bytes = actual_file_bytes != 0u ? actual_file_bytes : canonical_file_size(chain);
    stats.dense_float3_sequence_bytes = stats.points * stats.frames * 3u * sizeof(float);
    stats.dense_float4_sequence_bytes = stats.points * stats.frames * 4u * sizeof(float);
    const long double point_frames =
        static_cast<long double>(stats.points) * static_cast<long double>(stats.frames);
    stats.bytes_per_point_frame = point_frames == 0.0L
        ? 0.0
        : static_cast<double>(static_cast<long double>(stats.file_bytes) / point_frames);
    stats.ratio_vs_float3_sequence = stats.file_bytes == 0u
        ? 0.0
        : static_cast<double>(stats.dense_float3_sequence_bytes) / static_cast<double>(stats.file_bytes);
    stats.ratio_vs_float4_sequence = stats.file_bytes == 0u
        ? 0.0
        : static_cast<double>(stats.dense_float4_sequence_bytes) / static_cast<double>(stats.file_bytes);
    stats.novelty_records_per_frame =
        static_cast<double>(chain.novelties.size()) / static_cast<double>(chain.nodes.size());
    stats.novelty_record_density = point_frames == 0.0L
        ? 0.0
        : static_cast<double>(static_cast<long double>(chain.novelties.size()) / point_frames);
    for (const SeedChainNodeDisk& node : chain.nodes) {
        stats.maximum_chain_depth = std::max(stats.maximum_chain_depth, node.depth_from_checkpoint);
    }
    return stats;
}

SeedChainView make_seedchain_view(const SeedChainData& chain) {
    validate_seedchain(chain, false);
    SeedChainView view{};
    view.base_words = chain.base_words.data();
    view.nodes = chain.nodes.data();
    view.novelties = chain.novelties.data();
    view.decode = decode_params_from_header(chain.header.base_header);
    view.record_count = chain.header.base_header.record_count;
    view.padded_count = chain.header.base_header.padded_count;
    view.grid_width = chain.header.base_header.grid_width;
    view.grid_height = static_cast<std::uint32_t>(
        chain.header.base_header.padded_count / chain.header.base_header.grid_width);
    view.checkpoint_stride = chain.header.checkpoint_stride;
    view.base_swizzled =
        (chain.header.base_header.flags & kFlagXorSwizzle) != 0u ? 1u : 0u;
    view.novelty_quantum = chain.header.novelty_quantum;
    return view;
}

SeedChainErrorStats compare_seedchain_sequence(
    const SeedChainData& chain,
    const std::vector<std::vector<Vec3>>& reference_frames) {
    validate_seedchain(chain, false);
    if (reference_frames.size() != chain.nodes.size()) {
        throw std::invalid_argument("reference frame count does not match seed-chain node count");
    }
    const std::size_t point_count = static_cast<std::size_t>(chain.header.base_header.record_count);
    for (std::size_t frame = 0u; frame < reference_frames.size(); ++frame) {
        if (reference_frames[frame].size() != point_count) {
            throw std::invalid_argument(
                "reference frame " + std::to_string(frame) +
                " does not match the seed-chain point count");
        }
    }

    SeedChainErrorStats stats{};
    stats.points = point_count;
    stats.frames = reference_frames.size();
    const SeedChainView view = make_seedchain_view(chain);
    long double squared_sum = 0.0L;
    const long double sample_count =
        static_cast<long double>(stats.points) * static_cast<long double>(stats.frames);

    for (std::uint32_t frame = 0u; frame < static_cast<std::uint32_t>(reference_frames.size()); ++frame) {
        for (std::uint32_t point = 0u; point < static_cast<std::uint32_t>(point_count); ++point) {
            const Vec3 reconstructed = reconstruct_seedchain_point(view, frame, point).position;
            const double error = static_cast<double>(length(reconstructed - reference_frames[frame][point]));
            squared_sum += static_cast<long double>(error) * static_cast<long double>(error);
            if (error > stats.maximum_error) {
                stats.maximum_error = error;
                stats.worst_frame = frame;
                stats.worst_point = point;
            }
        }
    }

    stats.rms_error = sample_count == 0.0L
        ? 0.0
        : std::sqrt(static_cast<double>(squared_sum / sample_count));
    const double radius = static_cast<double>(chain.header.base_header.radius_scale);
    if (radius > 0.0) {
        stats.rms_error_over_radius = stats.rms_error / radius;
        stats.maximum_error_over_radius = stats.maximum_error / radius;
    }
    return stats;
}

std::vector<Vec3> reconstruct_seedchain_frame(
    const SeedChainData& chain,
    std::uint32_t frame_index,
    bool include_padding) {
    validate_seedchain(chain, false);
    if (frame_index >= chain.nodes.size()) {
        throw std::out_of_range("seed-chain frame index is out of range");
    }
    const SeedChainView view = make_seedchain_view(chain);
    const std::uint64_t count = include_padding ? view.padded_count : view.record_count;
    std::vector<Vec3> points;
    points.reserve(static_cast<std::size_t>(count));
    for (std::uint64_t point = 0u; point < count; ++point) {
        points.push_back(reconstruct_seedchain_point(
            view, frame_index, static_cast<std::uint32_t>(point)).position);
    }
    return points;
}

} // namespace klb
