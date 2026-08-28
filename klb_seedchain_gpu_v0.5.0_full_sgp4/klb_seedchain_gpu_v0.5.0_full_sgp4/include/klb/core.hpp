#pragma once

#include <cstddef>
#include <cstdint>
#include <cmath>
#include <limits>

#if defined(__CUDACC__) || defined(__CUDA__)
#define KLB_HD __host__ __device__
#define KLB_INLINE __forceinline__
#else
#define KLB_HD
#define KLB_INLINE inline
#endif

namespace klb {

constexpr std::uint32_t kFormatVersion = 1;
constexpr std::uint32_t kRecordBits = 37;
constexpr std::uint32_t kRhoBits = 11;
constexpr std::uint32_t kThetaBits = 12;
constexpr std::uint32_t kPhiBits = 10;
constexpr std::uint32_t kSymbolBits = 3;
constexpr std::uint32_t kParityBits = 1;
constexpr std::uint32_t kTileSide = 16;
constexpr std::uint32_t kTileRecords = kTileSide * kTileSide;
constexpr std::uint32_t kDefaultGridWidth = 256;

static_assert(kRhoBits + kThetaBits + kPhiBits + kSymbolBits + kParityBits == kRecordBits);

constexpr std::uint64_t mask_bits(std::uint32_t bits) {
    return bits == 64 ? ~std::uint64_t{0} : ((std::uint64_t{1} << bits) - 1u);
}

constexpr std::uint64_t kRhoMask = mask_bits(kRhoBits);
constexpr std::uint64_t kThetaMask = mask_bits(kThetaBits);
constexpr std::uint64_t kPhiMask = mask_bits(kPhiBits);
constexpr std::uint64_t kSymbolMask = mask_bits(kSymbolBits);
constexpr std::uint64_t kRecordMask = mask_bits(kRecordBits);

constexpr std::uint32_t kThetaShift = kRhoBits;
constexpr std::uint32_t kPhiShift = kThetaShift + kThetaBits;
constexpr std::uint32_t kSymbolShift = kPhiShift + kPhiBits;
constexpr std::uint32_t kParityShift = kSymbolShift + kSymbolBits;

constexpr std::uint32_t kFlagXorSwizzle = 1u << 0;
constexpr std::uint32_t kFlagMortonSorted = 1u << 1;
constexpr std::uint32_t kFlagEvenParity = 1u << 2;
constexpr std::uint32_t kFlagLogSpherical = 1u << 3;

struct Vec3 {
    float x{};
    float y{};
    float z{};

    KLB_HD Vec3() = default;
    KLB_HD Vec3(float px, float py, float pz) : x(px), y(py), z(pz) {}
};

KLB_HD KLB_INLINE Vec3 operator+(const Vec3& a, const Vec3& b) {
    return {a.x + b.x, a.y + b.y, a.z + b.z};
}

KLB_HD KLB_INLINE Vec3 operator-(const Vec3& a, const Vec3& b) {
    return {a.x - b.x, a.y - b.y, a.z - b.z};
}

KLB_HD KLB_INLINE Vec3 operator*(const Vec3& a, float s) {
    return {a.x * s, a.y * s, a.z * s};
}

KLB_HD KLB_INLINE float dot(const Vec3& a, const Vec3& b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

KLB_HD KLB_INLINE float length(const Vec3& v) {
    return ::sqrtf(dot(v, v));
}

KLB_HD KLB_INLINE std::uint32_t mix32(std::uint32_t x) {
    x ^= x >> 16;
    x *= 0x7feb352du;
    x ^= x >> 15;
    x *= 0x846ca68bu;
    x ^= x >> 16;
    return x;
}

KLB_HD KLB_INLINE std::uint32_t parity32(std::uint32_t x) {
    x ^= x >> 16;
    x ^= x >> 8;
    x ^= x >> 4;
    return (0x6996u >> (x & 0x0fu)) & 1u;
}

KLB_HD KLB_INLINE std::uint32_t parity64(std::uint64_t x) {
    return parity32(static_cast<std::uint32_t>(x) ^ static_cast<std::uint32_t>(x >> 32));
}

KLB_HD KLB_INLINE std::uint64_t make_record_code(
    std::uint32_t rho,
    std::uint32_t theta,
    std::uint32_t phi,
    std::uint32_t symbol) {
    std::uint64_t lower =
        (static_cast<std::uint64_t>(rho) & kRhoMask) |
        ((static_cast<std::uint64_t>(theta) & kThetaMask) << kThetaShift) |
        ((static_cast<std::uint64_t>(phi) & kPhiMask) << kPhiShift) |
        ((static_cast<std::uint64_t>(symbol) & kSymbolMask) << kSymbolShift);
    const std::uint64_t parity = parity64(lower);
    return lower | (parity << kParityShift);
}

KLB_HD KLB_INLINE bool record_has_even_parity(std::uint64_t code) {
    return parity64(code & kRecordMask) == 0u;
}

KLB_HD KLB_INLINE std::uint32_t record_symbol(std::uint64_t code) {
    return static_cast<std::uint32_t>((code >> kSymbolShift) & kSymbolMask);
}

KLB_HD KLB_INLINE std::uint32_t record_stored_parity(std::uint64_t code) {
    return static_cast<std::uint32_t>((code >> kParityShift) & 1u);
}

KLB_HD KLB_INLINE std::uint32_t record_meta(std::uint64_t code) {
    const std::uint32_t lo = static_cast<std::uint32_t>(code);
    const std::uint32_t hi = static_cast<std::uint32_t>(code >> 32);
    const std::uint32_t fingerprint = mix32(lo ^ (hi * 0x9e3779b9u)) & 0x0fffffffu;
    return record_symbol(code) |
           (record_stored_parity(code) << 3u) |
           (fingerprint << 4u);
}

struct DecodeParams {
    float center_x{};
    float center_y{};
    float center_z{};
    float radius_scale{1.0f};
    float log_k{15.0f};
    float log1p_k{2.7725887f};
};

struct DecodedRecord {
    Vec3 position{};
    std::uint32_t meta{};
};

KLB_HD KLB_INLINE DecodedRecord decode_record(std::uint64_t code, const DecodeParams& params) {
    constexpr float kPi = 3.14159265358979323846f;
    constexpr float kTwoPi = 6.28318530717958647692f;

    const std::uint32_t q_rho = static_cast<std::uint32_t>(code & kRhoMask);
    const std::uint32_t q_theta = static_cast<std::uint32_t>((code >> kThetaShift) & kThetaMask);
    const std::uint32_t q_phi = static_cast<std::uint32_t>((code >> kPhiShift) & kPhiMask);

    const float rho_n = static_cast<float>(q_rho) / static_cast<float>(kRhoMask);
    const float theta = static_cast<float>(q_theta) * (kTwoPi / static_cast<float>(std::uint32_t{1} << kThetaBits));
    const float phi_n = static_cast<float>(q_phi) / static_cast<float>(kPhiMask);
    const float phi = (phi_n - 0.5f) * kPi;
    const float radius_n = ::expm1f(rho_n * params.log1p_k) / params.log_k;

    const float cos_phi = ::cosf(phi);
    const float radius = radius_n * params.radius_scale;
    Vec3 p{
        params.center_x + radius * cos_phi * ::cosf(theta),
        params.center_y + radius * ::sinf(phi),
        params.center_z + radius * cos_phi * ::sinf(theta),
    };
    return {p, record_meta(code)};
}

KLB_HD KLB_INLINE std::uint64_t xor_swizzle_16x16(std::uint64_t logical_index) {
    const std::uint64_t tile = logical_index / kTileRecords;
    const std::uint32_t local = static_cast<std::uint32_t>(logical_index % kTileRecords);
    const std::uint32_t row = local >> 4u;
    const std::uint32_t col = local & 15u;
    const std::uint32_t swizzled_col = col ^ row;
    return tile * kTileRecords + static_cast<std::uint64_t>((row << 4u) | swizzled_col);
}

KLB_HD KLB_INLINE std::int64_t floor_div(std::int64_t a, std::int64_t b) {
    std::int64_t q = a / b;
    const std::int64_t r = a % b;
    if (r < 0) {
        --q;
    }
    return q;
}

KLB_HD KLB_INLINE std::int64_t floor_mod(std::int64_t a, std::int64_t b) {
    const std::int64_t r = a % b;
    return r < 0 ? r + b : r;
}

struct KleinCoordinate {
    std::uint32_t x{};
    std::uint32_t y{};
    std::uint32_t reflected{};
};

// Discrete Klein-bottle quotient: x wraps normally; crossing the y seam reflects x.
KLB_HD KLB_INLINE KleinCoordinate klein_coordinate(
    std::int64_t x,
    std::int64_t y,
    std::uint32_t width,
    std::uint32_t height) {
    const std::int64_t h = static_cast<std::int64_t>(height);
    const std::int64_t w = static_cast<std::int64_t>(width);
    const std::int64_t y_wrap = floor_div(y, h);
    const std::int64_t yy = floor_mod(y, h);
    std::int64_t xx = x;
    const std::uint32_t reflected = (y_wrap & 1ll) != 0 ? 1u : 0u;
    if (reflected != 0u) {
        xx = (w - 1ll) - xx;
    }
    xx = floor_mod(xx, w);
    return {
        static_cast<std::uint32_t>(xx),
        static_cast<std::uint32_t>(yy),
        reflected,
    };
}

KLB_HD KLB_INLINE std::uint64_t klein_index(
    std::int64_t x,
    std::int64_t y,
    std::uint32_t width,
    std::uint32_t height) {
    const KleinCoordinate coordinate = klein_coordinate(x, y, width, height);
    return static_cast<std::uint64_t>(coordinate.y) * width + coordinate.x;
}

KLB_HD KLB_INLINE std::uint64_t read_bits37(const std::uint32_t* words, std::uint64_t record_index) {
    const std::uint64_t bit_offset = record_index * static_cast<std::uint64_t>(kRecordBits);
    const std::uint64_t word_index = bit_offset >> 5u;
    const std::uint32_t shift = static_cast<std::uint32_t>(bit_offset & 31u);

    const std::uint64_t pair =
        static_cast<std::uint64_t>(words[word_index]) |
        (static_cast<std::uint64_t>(words[word_index + 1u]) << 32u);
    std::uint64_t value = pair >> shift;
    if (shift + kRecordBits > 64u) {
        value |= static_cast<std::uint64_t>(words[word_index + 2u]) << (64u - shift);
    }
    return value & kRecordMask;
}

inline void write_bits37(std::uint32_t* words, std::uint64_t record_index, std::uint64_t value) {
    value &= kRecordMask;
    std::uint64_t bit_offset = record_index * static_cast<std::uint64_t>(kRecordBits);
    std::uint32_t remaining = kRecordBits;
    while (remaining != 0u) {
        const std::uint64_t word_index = bit_offset >> 5u;
        const std::uint32_t shift = static_cast<std::uint32_t>(bit_offset & 31u);
        const std::uint32_t room = 32u - shift;
        const std::uint32_t take = remaining < room ? remaining : room;
        const std::uint64_t chunk_mask = mask_bits(take);
        const std::uint32_t chunk = static_cast<std::uint32_t>(value & chunk_mask);
        words[word_index] |= chunk << shift;
        value >>= take;
        bit_offset += take;
        remaining -= take;
    }
}

inline std::uint64_t fnv1a64(const void* data, std::size_t size) {
    const auto* bytes = static_cast<const std::uint8_t*>(data);
    std::uint64_t hash = 1469598103934665603ull;
    for (std::size_t i = 0; i < size; ++i) {
        hash ^= bytes[i];
        hash *= 1099511628211ull;
    }
    return hash;
}

} // namespace klb

