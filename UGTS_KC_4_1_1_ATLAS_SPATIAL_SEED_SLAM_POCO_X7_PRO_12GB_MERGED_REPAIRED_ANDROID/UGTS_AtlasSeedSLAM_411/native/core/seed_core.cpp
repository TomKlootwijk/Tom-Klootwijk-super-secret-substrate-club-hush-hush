#include "seed_core.h"

namespace ugts_seed {
namespace {

std::uint64_t rotl(std::uint64_t value, unsigned shift) noexcept {
    return (value << shift) | (value >> (64u - shift));
}

std::uint64_t mix(std::uint64_t value) noexcept {
    value += 0x9e3779b97f4a7c15ULL;
    value = (value ^ (value >> 30u)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27u)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31u);
}

}  // namespace

std::uint64_t schedule_value(
        std::uint64_t seed_high,
        std::uint64_t seed_low,
        std::uint64_t stream,
        std::uint64_t index) noexcept {
    const std::uint64_t state = seed_low
            ^ rotl(seed_high, 29u)
            ^ mix(stream * 0x9e3779b97f4a7c15ULL)
            ^ mix(index * 0xd1b54a32d192ed03ULL);
    return mix(state);
}

std::uint32_t schedule_bounded(
        std::uint64_t seed_high,
        std::uint64_t seed_low,
        std::uint64_t stream,
        std::uint64_t index,
        std::uint32_t bound) noexcept {
    if (bound == 0u) {
        return 0u;
    }
    return static_cast<std::uint32_t>(
            schedule_value(seed_high, seed_low, stream, index) % bound);
}

std::uint32_t crc32(const std::uint8_t* data, std::size_t length) noexcept {
    std::uint32_t value = 0xffffffffu;
    for (std::size_t index = 0; index < length; ++index) {
        value ^= data[index];
        for (int bit = 0; bit < 8; ++bit) {
            const std::uint32_t mask = static_cast<std::uint32_t>(
                    -static_cast<std::int32_t>(value & 1u));
            value = (value >> 1u) ^ (0xedb88320u & mask);
        }
    }
    return value ^ 0xffffffffu;
}

bool self_test() noexcept {
    static constexpr std::uint8_t fixture[] = {'1','2','3','4','5','6','7','8','9'};
    if (crc32(fixture, sizeof(fixture)) != 0xcbf43926u) {
        return false;
    }
    const std::uint64_t a = schedule_value(1u, 2u, 3u, 4u);
    const std::uint64_t b = schedule_value(1u, 2u, 3u, 4u);
    const std::uint64_t c = schedule_value(1u, 2u, 3u, 5u);
    return a == b && a != c && schedule_bounded(1u, 2u, 3u, 4u, 97u) < 97u;
}

}  // namespace ugts_seed
