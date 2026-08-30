#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>

namespace kc {

using ChronoSha256Digest = std::array<std::uint8_t,32>;

class ChronoSha256 final {
public:
    ChronoSha256();
    void update(std::span<const std::uint8_t> bytes);
    ChronoSha256Digest finish();

private:
    void transform(const std::uint8_t* block);

    std::array<std::uint32_t,8> state_{};
    std::array<std::uint8_t,64> buffered_{};
    std::uint64_t byteCount_=0;
    std::size_t bufferedBytes_=0;
    bool finished_=false;
};

ChronoSha256Digest chronoCaptureSha256(std::span<const std::uint8_t> bytes);

} // namespace kc
