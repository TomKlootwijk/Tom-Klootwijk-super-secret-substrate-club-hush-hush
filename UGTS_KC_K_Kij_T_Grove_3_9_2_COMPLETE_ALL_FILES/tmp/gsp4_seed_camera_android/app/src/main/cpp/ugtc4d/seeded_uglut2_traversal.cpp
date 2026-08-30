#include "seeded_uglut2_traversal.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <tuple>

namespace ugts::chrono {
namespace {

constexpr std::uint64_t Golden64 = 0x9e3779b97f4a7c15ull;
constexpr std::uint64_t Fnv64Offset = 0xcbf29ce484222325ull;
constexpr std::uint64_t Fnv64Prime = 0x100000001b3ull;

[[noreturn]] void fail(const char* message) {
    throw std::runtime_error(std::string("UGLUT2 seeded traversal: ") + message);
}

void require(bool condition, const char* message) {
    if (!condition) fail(message);
}

class Reader final {
public:
    explicit Reader(const std::vector<std::uint8_t>& bytes)
        : data_(bytes.data()), size_(bytes.size()) {}

    const std::uint8_t* raw(std::size_t count) {
        require(count <= size_ - offset_, "truncated UGLUT2");
        const auto* result = data_ + offset_;
        offset_ += count;
        return result;
    }
    std::uint16_t u16() {
        const auto* p = raw(2u);
        return static_cast<std::uint16_t>(p[0]) |
               static_cast<std::uint16_t>(static_cast<std::uint16_t>(p[1]) << 8u);
    }
    std::uint32_t u32() {
        const auto* p = raw(4u);
        return static_cast<std::uint32_t>(p[0]) |
               (static_cast<std::uint32_t>(p[1]) << 8u) |
               (static_cast<std::uint32_t>(p[2]) << 16u) |
               (static_cast<std::uint32_t>(p[3]) << 24u);
    }
    std::uint64_t u64() {
        const auto low = static_cast<std::uint64_t>(u32());
        return low | (static_cast<std::uint64_t>(u32()) << 32u);
    }
    double f64() {
        const auto bits = u64();
        double result = 0.0;
        static_assert(sizeof(result) == sizeof(bits), "IEEE binary64 is required");
        std::memcpy(&result, &bits, sizeof(result));
        return result;
    }
    std::size_t remaining() const noexcept { return size_ - offset_; }

private:
    const std::uint8_t* data_ = nullptr;
    std::size_t size_ = 0u;
    std::size_t offset_ = 0u;
};

std::uint64_t splitmix64(std::uint64_t value) {
    value += Golden64;
    value = (value ^ (value >> 30u)) * 0xbf58476d1ce4e5b9ull;
    value = (value ^ (value >> 27u)) * 0x94d049bb133111ebull;
    return value ^ (value >> 31u);
}

std::uint64_t combineSeed(std::uint64_t seed, std::uint64_t value) {
    return splitmix64(seed ^
        (splitmix64(value) + Golden64 + (seed << 6u) + (seed >> 2u)));
}

std::uint64_t hash64(const char* text) {
    auto value = Fnv64Offset;
    std::size_t length = 0u;
    while (text[length] != '\0') {
        value = (value ^ static_cast<std::uint8_t>(text[length])) * Fnv64Prime;
        ++length;
    }
    return splitmix64(value ^ static_cast<std::uint64_t>(length));
}

std::uint64_t stableId(
    std::uint64_t session,
    std::uint64_t nameSpace,
    std::uint64_t address
) {
    return combineSeed(combineSeed(session, nameSpace), address);
}

std::int64_t halfToFixed(std::uint16_t word, int fractionalBits) {
    const auto negative = (word & 0x8000u) != 0u;
    const auto exponent = static_cast<int>((word >> 10u) & 0x1fu);
    const auto fraction = static_cast<std::uint64_t>(word & 0x03ffu);
    require(exponent != 0x1f, "non-finite binary16 lane");
    const auto mantissa = exponent == 0 ? fraction : 1024u + fraction;
    const auto power = exponent == 0
        ? -24 + fractionalBits
        : exponent - 25 + fractionalBits;
    if (mantissa == 0u) return 0;
    std::uint64_t magnitude = 0u;
    if (power >= 0) {
        require(power < 63, "fixed conversion overflow");
        magnitude = mantissa << power;
    } else {
        const auto shift = static_cast<unsigned>(-power);
        require(shift < 63u, "fixed conversion shift overflow");
        const auto denominator = 1ull << shift;
        const auto quotient = mantissa / denominator;
        const auto remainder = mantissa % denominator;
        const auto halfway = denominator >> 1u;
        magnitude = quotient + static_cast<std::uint64_t>(
            remainder > halfway || (remainder == halfway && (quotient & 1u) != 0u));
    }
    require(magnitude <= static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()),
            "fixed conversion exceeds int64");
    const auto signedMagnitude = static_cast<std::int64_t>(magnitude);
    return negative ? -signedMagnitude : signedMagnitude;
}

void appendU32(std::vector<std::uint8_t>& bytes, std::uint32_t value) {
    bytes.push_back(static_cast<std::uint8_t>(value));
    bytes.push_back(static_cast<std::uint8_t>(value >> 8u));
    bytes.push_back(static_cast<std::uint8_t>(value >> 16u));
    bytes.push_back(static_cast<std::uint8_t>(value >> 24u));
}

} // namespace

SeededUglut2Traversal regenerateSeededUglut2Traversal(
    std::uint32_t width,
    std::uint32_t height,
    std::uint64_t rootSeed,
    std::uint64_t recipeSeed,
    const std::vector<std::uint8_t>& uglut2
) {
    require(width >= 1u && width <= 65535u && height >= 1u && height <= 65535u,
            "dimensions must fit uint16");
    const auto pixelCount64 = static_cast<std::uint64_t>(width) * height;
    require(pixelCount64 <= (1ull << 30u), "pixel count exceeds safety limit");
    const auto maximumRadius2 =
        static_cast<std::uint64_t>(width - 1u) * (width - 1u) +
        static_cast<std::uint64_t>(height - 1u) * (height - 1u);
    require(maximumRadius2 <=
                (static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()) >> 32u),
            "dimensions exceed exact Q32 radius domain");
    require(uglut2.size() >= 48u, "header is truncated");
    Reader reader(uglut2);
    require(std::memcmp(reader.raw(6u), "UGLUT2", 6u) == 0, "magic mismatch");
    const auto resolution = reader.u16();
    const auto r0 = reader.f64();
    const auto rhoMin = reader.f64();
    const auto rhoMax = reader.f64();
    const auto coreRadius = reader.f64();
    const auto radiusScale = reader.f64();
    require(resolution >= 16u && resolution <= 4096u &&
                (resolution & (resolution - 1u)) == 0u,
            "resolution is not an accepted power of two");
    require(std::isfinite(r0) && std::isfinite(rhoMin) && std::isfinite(rhoMax) &&
                std::isfinite(coreRadius) && r0 > 0.0 && rhoMin < rhoMax &&
                coreRadius > 0.0 && radiusScale == 1.0,
            "profile is invalid or non-unit-scaled");
    require(reader.remaining() == static_cast<std::size_t>(resolution) * 6u,
            "binary16 lane count mismatch");
    std::vector<std::uint16_t> sineWords(resolution), cosineWords(resolution), radiusWords(resolution);
    for (auto& word : sineWords) word = reader.u16();
    for (auto& word : cosineWords) word = reader.u16();
    for (auto& word : radiusWords) word = reader.u16();
    std::vector<std::int64_t> sine(resolution), cosine(resolution), radius(resolution);
    for (std::size_t index = 0u; index < resolution; ++index) {
        sine[index] = halfToFixed(sineWords[index], 30);
        cosine[index] = halfToFixed(cosineWords[index], 30);
        radius[index] = halfToFixed(radiusWords[index], 16);
        require(radius[index] > 0 && (index == 0u || radius[index] >= radius[index - 1u]),
                "radius lane is not positive monotone Q16");
        require(sine[index] != 0 || cosine[index] != 0, "direction lane has a zero vector");
    }
    require(radius[0] == static_cast<std::int64_t>(std::nearbyint(coreRadius * 65536.0)),
            "first radius is not explicit core radius");
    require(cosine[0] > 0 && sine[0] == 0, "ray zero is not canonical +X");
    for (std::size_t index = 0u; index + 1u < resolution; ++index) {
        require(cosine[index] * sine[index + 1u] -
                    sine[index] * cosine[index + 1u] > 0,
                "direction rays are not strictly counter-clockwise");
    }
    require(cosine.back() * sine.front() - sine.back() * cosine.front() > 0,
            "direction seam is not strictly counter-clockwise");

    std::vector<std::uint64_t> radialMidpoints;
    radialMidpoints.reserve(resolution - 1u);
    for (std::size_t index = 0u; index + 1u < resolution; ++index) {
        const auto sum = static_cast<std::uint64_t>(radius[index] + radius[index + 1u]);
        require(sum <= std::numeric_limits<std::uint32_t>::max(),
                "radius midpoint exceeds exact Q32 domain");
        radialMidpoints.push_back(sum * sum);
    }
    const auto coreQ32 = static_cast<std::uint64_t>(radius[0] * 2) *
                         static_cast<std::uint64_t>(radius[0] * 2);
    const auto session = combineSeed(rootSeed, recipeSeed);
    const auto nameSpace = hash64("ugtoms:chrono-seeded-log-polar-traversal:v1");
    const auto schedule = combineSeed(stableId(session, nameSpace, 0u), 0u);
    const auto origin = static_cast<std::uint32_t>(schedule) & (resolution - 1u);
    const auto reverse = ((schedule >> 63u) & 1u) != 0u;

    struct Key {
        std::uint8_t notCore;
        std::uint32_t rho20;
        std::uint32_t theta18;
        std::int64_t radius2;
        std::int64_t sectorCross;
        std::uint64_t lineage;
        std::uint32_t address;
    };
    const auto pixelCount = static_cast<std::size_t>(pixelCount64);
    std::vector<Key> keys;
    keys.reserve(pixelCount);
    for (std::size_t address = 0u; address < pixelCount; ++address) {
        const auto x = static_cast<std::int64_t>(address % width);
        const auto y = static_cast<std::int64_t>(address / width);
        const auto dx2 = x * 2 - (static_cast<std::int64_t>(width) - 1);
        const auto dy2 = (static_cast<std::int64_t>(height) - 1) - y * 2;
        const auto radius2 = dx2 * dx2 + dy2 * dy2;
        const auto targetQ32 = static_cast<std::uint64_t>(radius2) << 32u;
        auto ring = static_cast<std::uint32_t>(
            std::lower_bound(radialMidpoints.begin(), radialMidpoints.end(), targetQ32) -
            radialMidpoints.begin());
        const auto vectorHalf = dy2 < 0 || (dy2 == 0 && dx2 < 0);
        std::size_t low = 0u;
        std::size_t high = resolution;
        while (low < high) {
            const auto middle = (low + high) / 2u;
            const auto probe = std::min<std::size_t>(middle, resolution - 1u);
            const auto rayHalf = sine[probe] < 0 ||
                                 (sine[probe] == 0 && cosine[probe] < 0);
            const auto cross = cosine[probe] * dy2 - sine[probe] * dx2;
            const auto lessOrEqual = (!rayHalf && vectorHalf) ||
                                     (rayHalf == vectorHalf && cross >= 0);
            if (lessOrEqual) low = middle + 1u;
            else high = middle;
        }
        auto sector = static_cast<std::uint32_t>((low - 1u) & (resolution - 1u));
        const auto core = targetQ32 < coreQ32;
        if (core) {
            ring = 0u;
            sector = 0u;
        }
        const auto rho20 = static_cast<std::uint32_t>(
            (static_cast<std::uint64_t>(ring) * ((1u << 20u) - 1u) +
             (resolution - 1u) / 2u) / (resolution - 1u));
        const auto seededSector = reverse
            ? (origin - sector) & (resolution - 1u)
            : (sector - origin) & (resolution - 1u);
        auto theta18 = static_cast<std::uint32_t>(
            (static_cast<std::uint64_t>(seededSector) << 18u) / resolution);
        if (core) theta18 = 0u;
        keys.push_back(Key{
            static_cast<std::uint8_t>(!core), rho20, theta18, radius2,
            cosine[sector] * dy2 - sine[sector] * dx2,
            stableId(session, nameSpace, address),
            static_cast<std::uint32_t>(address),
        });
    }
    std::sort(keys.begin(), keys.end(), [](const Key& left, const Key& right) {
        return std::tie(left.notCore, left.rho20, left.theta18, left.radius2,
                        left.sectorCross, left.lineage, left.address) <
               std::tie(right.notCore, right.rho20, right.theta18, right.radius2,
                        right.sectorCross, right.lineage, right.address);
    });
    SeededUglut2Traversal result{};
    result.width = width;
    result.height = height;
    result.resolution = resolution;
    result.rootSeed = rootSeed;
    result.recipeSeed = recipeSeed;
    result.uglut2Sha256 = sha256(uglut2.data(), uglut2.size());
    result.polarOrdinalToCartesian.resize(pixelCount);
    std::vector<std::uint8_t> traversalBytes;
    traversalBytes.reserve(pixelCount * 4u);
    for (std::size_t index = 0u; index < pixelCount; ++index) {
        result.polarOrdinalToCartesian[index] = keys[index].address;
        appendU32(traversalBytes, keys[index].address);
    }
    result.traversalSha256 = sha256(traversalBytes.data(), traversalBytes.size());
    return result;
}

} // namespace ugts::chrono
