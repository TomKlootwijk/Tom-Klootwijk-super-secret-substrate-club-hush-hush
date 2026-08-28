#include "klb/format.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <string>
#include <utility>

namespace klb {
namespace {

constexpr std::array<char, 8> kMagic{'K', 'L', 'B', '3', '7', 'P', 'K', '1'};

void require_little_endian() {
    if constexpr (std::endian::native != std::endian::little) {
        throw std::runtime_error("KLB1 currently supports little-endian hosts only");
    }
}

std::uint32_t clamp_quantize(float value, std::uint32_t max_value) {
    const float clamped = std::clamp(value, 0.0f, 1.0f);
    return static_cast<std::uint32_t>(std::lround(clamped * static_cast<float>(max_value)));
}

std::uint32_t part1by2_10(std::uint32_t x) {
    x &= 0x000003ffu;
    x = (x | (x << 16u)) & 0x030000ffu;
    x = (x | (x << 8u)) & 0x0300f00fu;
    x = (x | (x << 4u)) & 0x030c30c3u;
    x = (x | (x << 2u)) & 0x09249249u;
    return x;
}

std::uint32_t morton3_10(std::uint32_t x, std::uint32_t y, std::uint32_t z) {
    return part1by2_10(x) | (part1by2_10(y) << 1u) | (part1by2_10(z) << 2u);
}

struct SortedPoint {
    Vec3 point;
    std::uint32_t morton;
    std::uint64_t original_index;
};

std::vector<SortedPoint> prepare_points(const std::vector<Vec3>& points, bool sort_points) {
    Vec3 minp{
        std::numeric_limits<float>::infinity(),
        std::numeric_limits<float>::infinity(),
        std::numeric_limits<float>::infinity(),
    };
    Vec3 maxp{
        -std::numeric_limits<float>::infinity(),
        -std::numeric_limits<float>::infinity(),
        -std::numeric_limits<float>::infinity(),
    };

    for (const Vec3& p : points) {
        minp.x = std::min(minp.x, p.x);
        minp.y = std::min(minp.y, p.y);
        minp.z = std::min(minp.z, p.z);
        maxp.x = std::max(maxp.x, p.x);
        maxp.y = std::max(maxp.y, p.y);
        maxp.z = std::max(maxp.z, p.z);
    }

    const Vec3 extent{
        std::max(maxp.x - minp.x, 1.0e-20f),
        std::max(maxp.y - minp.y, 1.0e-20f),
        std::max(maxp.z - minp.z, 1.0e-20f),
    };

    std::vector<SortedPoint> sorted;
    sorted.reserve(points.size());
    for (std::size_t i = 0; i < points.size(); ++i) {
        const Vec3& p = points[i];
        const auto qx = clamp_quantize((p.x - minp.x) / extent.x, 1023u);
        const auto qy = clamp_quantize((p.y - minp.y) / extent.y, 1023u);
        const auto qz = clamp_quantize((p.z - minp.z) / extent.z, 1023u);
        sorted.push_back({p, morton3_10(qx, qy, qz), static_cast<std::uint64_t>(i)});
    }

    if (sort_points) {
        std::stable_sort(sorted.begin(), sorted.end(), [](const SortedPoint& a, const SortedPoint& b) {
            if (a.morton != b.morton) {
                return a.morton < b.morton;
            }
            return a.original_index < b.original_index;
        });
    }
    return sorted;
}

std::uint64_t encode_point(
    const Vec3& p,
    const Vec3& center,
    float scale,
    float log_k,
    float log1p_k,
    std::uint32_t symbol) {
    constexpr float kPi = 3.14159265358979323846f;
    constexpr float kTwoPi = 6.28318530717958647692f;

    const Vec3 local = p - center;
    const float radius = length(local);
    const float radius_n = std::clamp(radius / scale, 0.0f, 1.0f);
    const float rho_n = std::log1p(log_k * radius_n) / log1p_k;

    float theta_n = 0.0f;
    float phi_n = 0.5f;
    if (radius > 1.0e-20f) {
        float theta = std::atan2(local.z, local.x);
        if (theta < 0.0f) {
            theta += kTwoPi;
        }
        theta_n = theta / kTwoPi;
        const float sin_phi = std::clamp(local.y / radius, -1.0f, 1.0f);
        phi_n = std::asin(sin_phi) / kPi + 0.5f;
    }

    const std::uint32_t q_rho = clamp_quantize(rho_n, static_cast<std::uint32_t>(kRhoMask));
    const std::uint32_t theta_levels = std::uint32_t{1} << kThetaBits;
    const std::int64_t theta_round = static_cast<std::int64_t>(std::llround(theta_n * static_cast<float>(theta_levels)));
    const std::uint32_t q_theta = static_cast<std::uint32_t>(theta_round) & (theta_levels - 1u);
    const std::uint32_t q_phi = clamp_quantize(phi_n, static_cast<std::uint32_t>(kPhiMask));
    return make_record_code(q_rho, q_theta, q_phi, symbol);
}

} // namespace

DecodeParams decode_params_from_header(const FileHeaderDisk& header) {
    DecodeParams params{};
    params.center_x = header.center[0];
    params.center_y = header.center[1];
    params.center_z = header.center[2];
    params.radius_scale = header.radius_scale;
    params.log_k = header.log_k;
    params.log1p_k = std::log1p(header.log_k);
    return params;
}

namespace {

PackedData pack_points_impl(
    const std::vector<Vec3>& points,
    std::uint64_t source_bytes,
    float log_k,
    bool sort_points,
    PackStats* stats) {
    require_little_endian();
    if (points.empty()) {
        throw std::invalid_argument("cannot pack an empty point set");
    }
    if (!std::isfinite(log_k) || log_k <= 0.0f) {
        throw std::invalid_argument("log_k must be finite and greater than zero");
    }

    const std::vector<SortedPoint> sorted = prepare_points(points, sort_points);

    Vec3 minp{
        std::numeric_limits<float>::infinity(),
        std::numeric_limits<float>::infinity(),
        std::numeric_limits<float>::infinity(),
    };
    Vec3 maxp{
        -std::numeric_limits<float>::infinity(),
        -std::numeric_limits<float>::infinity(),
        -std::numeric_limits<float>::infinity(),
    };
    for (const SortedPoint& item : sorted) {
        const Vec3& p = item.point;
        minp.x = std::min(minp.x, p.x);
        minp.y = std::min(minp.y, p.y);
        minp.z = std::min(minp.z, p.z);
        maxp.x = std::max(maxp.x, p.x);
        maxp.y = std::max(maxp.y, p.y);
        maxp.z = std::max(maxp.z, p.z);
    }

    const Vec3 center{
        0.5f * (minp.x + maxp.x),
        0.5f * (minp.y + maxp.y),
        0.5f * (minp.z + maxp.z),
    };
    float scale = 0.0f;
    for (const SortedPoint& item : sorted) {
        scale = std::max(scale, length(item.point - center));
    }
    if (!(scale > 0.0f) || !std::isfinite(scale)) {
        scale = 1.0f;
    }

    const float log1p_k = std::log1p(log_k);
    const std::uint64_t record_count = static_cast<std::uint64_t>(sorted.size());
    const std::uint64_t padded_count =
        ((record_count + kTileRecords - 1u) / kTileRecords) * kTileRecords;

    std::vector<std::uint64_t> logical_codes(static_cast<std::size_t>(padded_count));
    for (std::uint64_t i = 0; i < record_count; ++i) {
        const SortedPoint& item = sorted[static_cast<std::size_t>(i)];
        const std::uint32_t symbol =
            (item.morton ^ (item.morton >> 7u) ^ static_cast<std::uint32_t>(i * 0x9e3779b9ull)) &
            static_cast<std::uint32_t>(kSymbolMask);
        logical_codes[static_cast<std::size_t>(i)] =
            encode_point(item.point, center, scale, log_k, log1p_k, symbol);
    }
    for (std::uint64_t i = record_count; i < padded_count; ++i) {
        logical_codes[static_cast<std::size_t>(i)] = logical_codes[static_cast<std::size_t>(i % record_count)];
    }

    const std::uint64_t payload_bits = padded_count * static_cast<std::uint64_t>(kRecordBits);
    const std::uint64_t base_word_count = (payload_bits + 31u) / 32u;
    const std::uint64_t word_count = base_word_count + 2u; // two guard words for branch-free 3-word reads
    if (word_count > static_cast<std::uint64_t>(std::numeric_limits<std::size_t>::max())) {
        throw std::overflow_error("packed stream is too large for this host");
    }

    PackedData packed{};
    packed.words.assign(static_cast<std::size_t>(word_count), 0u);
    for (std::uint64_t logical = 0; logical < padded_count; ++logical) {
        const std::uint64_t physical = xor_swizzle_16x16(logical);
        write_bits37(packed.words.data(), physical, logical_codes[static_cast<std::size_t>(logical)]);
    }

    std::memcpy(packed.header.magic, kMagic.data(), kMagic.size());
    packed.header.version = kFormatVersion;
    packed.header.header_bytes = sizeof(FileHeaderDisk);
    packed.header.record_count = record_count;
    packed.header.padded_count = padded_count;
    packed.header.word_count = word_count;
    packed.header.source_bytes = source_bytes;
    packed.header.record_bits = kRecordBits;
    packed.header.tile_records = kTileRecords;
    packed.header.grid_width = kDefaultGridWidth;
    packed.header.flags = kFlagXorSwizzle | kFlagEvenParity | kFlagLogSpherical;
    if (sort_points) {
        packed.header.flags |= kFlagMortonSorted;
    }
    packed.header.center[0] = center.x;
    packed.header.center[1] = center.y;
    packed.header.center[2] = center.z;
    packed.header.radius_scale = scale;
    packed.header.log_k = log_k;

    const DecodeParams params = decode_params_from_header(packed.header);
    long double squared_error_sum = 0.0L;
    double max_error = 0.0;
    for (std::uint64_t i = 0; i < record_count; ++i) {
        const DecodedRecord decoded = decode_record(logical_codes[static_cast<std::size_t>(i)], params);
        const Vec3 delta = decoded.position - sorted[static_cast<std::size_t>(i)].point;
        const double error = static_cast<double>(length(delta));
        squared_error_sum += static_cast<long double>(error * error);
        max_error = std::max(max_error, error);
    }
    const double rms_error = std::sqrt(static_cast<double>(squared_error_sum / static_cast<long double>(record_count)));
    packed.header.rms_error = static_cast<float>(rms_error);
    packed.header.max_error = static_cast<float>(max_error);
    packed.header.payload_hash = fnv1a64(packed.words.data(), packed.words.size() * sizeof(std::uint32_t));

    if (stats != nullptr) {
        *stats = inspect_packed(packed);
    }
    return packed;
}

} // namespace

PackedData pack_points(
    const std::vector<Vec3>& points,
    std::uint64_t source_bytes,
    float log_k,
    PackStats* stats) {
    return pack_points_impl(points, source_bytes, log_k, true, stats);
}

PackedData pack_points_ordered(
    const std::vector<Vec3>& points,
    std::uint64_t source_bytes,
    float log_k,
    PackStats* stats) {
    return pack_points_impl(points, source_bytes, log_k, false, stats);
}

std::vector<std::uint64_t> unpack_logical_codes(const PackedData& packed) {
    if (packed.header.record_bits != kRecordBits || packed.header.tile_records != kTileRecords) {
        throw std::runtime_error("unsupported KLB record layout");
    }
    if (packed.words.size() != packed.header.word_count) {
        throw std::runtime_error("KLB word count does not match payload");
    }

    std::vector<std::uint64_t> codes(static_cast<std::size_t>(packed.header.padded_count));
    const bool swizzled = (packed.header.flags & kFlagXorSwizzle) != 0u;
    for (std::uint64_t logical = 0; logical < packed.header.padded_count; ++logical) {
        const std::uint64_t physical = swizzled ? xor_swizzle_16x16(logical) : logical;
        const std::uint64_t code = read_bits37(packed.words.data(), physical);
        if ((packed.header.flags & kFlagEvenParity) != 0u && !record_has_even_parity(code)) {
            throw std::runtime_error("KLB record parity check failed at logical index " + std::to_string(logical));
        }
        codes[static_cast<std::size_t>(logical)] = code;
    }
    return codes;
}

std::vector<Vec3> unpack_points(const PackedData& packed, bool include_padding) {
    const std::vector<std::uint64_t> codes = unpack_logical_codes(packed);
    const std::uint64_t count = include_padding ? packed.header.padded_count : packed.header.record_count;
    const DecodeParams params = decode_params_from_header(packed.header);
    std::vector<Vec3> points;
    points.reserve(static_cast<std::size_t>(count));
    for (std::uint64_t i = 0; i < count; ++i) {
        points.push_back(decode_record(codes[static_cast<std::size_t>(i)], params).position);
    }
    return points;
}

void save_packed(const std::filesystem::path& path, const PackedData& packed) {
    require_little_endian();
    if (packed.words.size() != packed.header.word_count) {
        throw std::runtime_error("cannot save KLB: word count mismatch");
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        throw std::runtime_error("failed to create KLB file: " + path.string());
    }
    output.write(reinterpret_cast<const char*>(&packed.header), sizeof(packed.header));
    output.write(
        reinterpret_cast<const char*>(packed.words.data()),
        static_cast<std::streamsize>(packed.words.size() * sizeof(std::uint32_t)));
    if (!output) {
        throw std::runtime_error("failed while writing KLB file: " + path.string());
    }
}

PackedData load_packed(const std::filesystem::path& path) {
    require_little_endian();
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("failed to open KLB file: " + path.string());
    }

    PackedData packed{};
    input.read(reinterpret_cast<char*>(&packed.header), sizeof(packed.header));
    if (input.gcount() != static_cast<std::streamsize>(sizeof(packed.header))) {
        throw std::runtime_error("KLB file is shorter than its header: " + path.string());
    }
    if (std::memcmp(packed.header.magic, kMagic.data(), kMagic.size()) != 0) {
        throw std::runtime_error("not a KLB37 packed file: " + path.string());
    }
    if (packed.header.version != kFormatVersion || packed.header.header_bytes != sizeof(FileHeaderDisk)) {
        throw std::runtime_error("unsupported KLB file version");
    }
    if (packed.header.record_bits != kRecordBits || packed.header.tile_records != kTileRecords) {
        throw std::runtime_error("unsupported KLB record or tile layout");
    }
    if (packed.header.record_count == 0u || packed.header.padded_count < packed.header.record_count) {
        throw std::runtime_error("invalid KLB record counts");
    }
    if (packed.header.padded_count % kTileRecords != 0u) {
        throw std::runtime_error("invalid KLB padding: padded count is not tile-aligned");
    }
    if (packed.header.grid_width == 0u || packed.header.padded_count % packed.header.grid_width != 0u) {
        throw std::runtime_error("invalid KLB grid width");
    }
    constexpr std::uint64_t kMaxWords = (std::uint64_t{1} << 34u); // 64 GiB of uint32 words
    if (packed.header.word_count < 2u || packed.header.word_count > kMaxWords) {
        throw std::runtime_error("unreasonable KLB word count");
    }

    packed.words.resize(static_cast<std::size_t>(packed.header.word_count));
    input.read(
        reinterpret_cast<char*>(packed.words.data()),
        static_cast<std::streamsize>(packed.words.size() * sizeof(std::uint32_t)));
    if (!input) {
        throw std::runtime_error("KLB payload is truncated: " + path.string());
    }

    const std::uint64_t payload_hash = fnv1a64(packed.words.data(), packed.words.size() * sizeof(std::uint32_t));
    if (payload_hash != packed.header.payload_hash) {
        throw std::runtime_error("KLB payload hash mismatch: file is corrupt or incomplete");
    }
    return packed;
}

PackStats inspect_packed(const PackedData& packed, std::uint64_t actual_file_bytes) {
    PackStats stats{};
    stats.input_points = packed.header.record_count;
    stats.padded_points = packed.header.padded_count;
    stats.source_bytes = packed.header.source_bytes;
    stats.payload_bytes = (packed.header.padded_count * static_cast<std::uint64_t>(kRecordBits) + 7u) / 8u;
    stats.file_bytes = actual_file_bytes != 0u
        ? actual_file_bytes
        : static_cast<std::uint64_t>(sizeof(FileHeaderDisk) + packed.words.size() * sizeof(std::uint32_t));
    stats.bytes_per_point = static_cast<double>(stats.payload_bytes) / static_cast<double>(stats.input_points);
    stats.ratio_vs_float3 =
        static_cast<double>(stats.input_points * 3u * sizeof(float)) / static_cast<double>(stats.file_bytes);
    stats.ratio_vs_source_file = stats.source_bytes == 0u
        ? 0.0
        : static_cast<double>(stats.source_bytes) / static_cast<double>(stats.file_bytes);
    stats.rms_error = packed.header.rms_error;
    stats.max_error = packed.header.max_error;
    return stats;
}

std::vector<Vec3> generate_lsystem_points(std::size_t count) {
    if (count == 0u) {
        throw std::invalid_argument("generated point count must be non-zero");
    }

    constexpr float kPi = 3.14159265358979323846f;
    std::vector<Vec3> points;
    points.reserve(count);

    for (std::uint64_t i = 0; i < static_cast<std::uint64_t>(count); ++i) {
        const std::uint64_t path = i + 1u;
        const int highest = 63 - std::countl_zero(path);
        Vec3 p{0.0f, -1.0f, 0.0f};
        float yaw = 0.0f;
        float elevation = 0.5f * kPi;
        float segment = 0.85f;
        float velocity = 0.025f;
        float acceleration = 0.0015f;
        std::uint64_t prefix = 1u;

        for (int bit_index = highest - 1, level = 0; bit_index >= 0; --bit_index, ++level) {
            const std::uint32_t branch = static_cast<std::uint32_t>((path >> bit_index) & 1u);
            const float sign = branch != 0u ? 1.0f : -1.0f;
            const float parity_twist = parity64(prefix) != 0u ? 0.09f : -0.09f;
            yaw += sign * (0.34f + 0.018f * static_cast<float>(level)) + parity_twist;
            elevation = 1.12f + sign * 0.11f + 0.16f * std::sinf(0.47f * static_cast<float>(level) + parity_twist);

            const float cos_e = std::cosf(elevation);
            const Vec3 direction{
                std::cosf(yaw) * cos_e,
                std::sinf(elevation),
                std::sinf(yaw) * cos_e,
            };
            p = p + direction * segment;

            // Delta and delta-delta perturb the branch length without storing another table.
            segment *= 0.72f + velocity;
            velocity += acceleration;
            acceleration *= -0.82f;
            prefix = (prefix << 1u) | branch;
        }

        const float spiral = std::log1pf(static_cast<float>(i + 1u)) * 0.006f;
        p.x += spiral * std::cosf(static_cast<float>(i) * 2.39996323f);
        p.z += spiral * std::sinf(static_cast<float>(i) * 2.39996323f);
        points.push_back(p);
    }
    return points;
}

} // namespace klb

