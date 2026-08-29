#ifndef UGTS_SEED_CORE_H
#define UGTS_SEED_CORE_H

#include <cstddef>
#include <cstdint>

namespace ugts_seed {

constexpr std::uint32_t kAbiVersion = 0x00040101u;

std::uint64_t schedule_value(
        std::uint64_t seed_high,
        std::uint64_t seed_low,
        std::uint64_t stream,
        std::uint64_t index) noexcept;

std::uint32_t schedule_bounded(
        std::uint64_t seed_high,
        std::uint64_t seed_low,
        std::uint64_t stream,
        std::uint64_t index,
        std::uint32_t bound) noexcept;

std::uint32_t crc32(const std::uint8_t* data, std::size_t length) noexcept;

bool self_test() noexcept;

}  // namespace ugts_seed

#endif
