#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string>
#include <string_view>

namespace ugts::chess2 {

class Sha256 {
public:
    Sha256();
    void update(std::span<const std::byte> bytes);
    void update(std::string_view text);
    [[nodiscard]] std::array<std::uint8_t, 32> digest();
    [[nodiscard]] std::string hex_digest();

private:
    void transform(const std::uint8_t* chunk);
    std::array<std::uint32_t, 8> state_{};
    std::array<std::uint8_t, 64> buffer_{};
    std::uint64_t bit_length_ = 0;
    std::size_t buffer_length_ = 0;
    bool finalized_ = false;
};

[[nodiscard]] std::string sha256_hex(std::string_view text);

}  // namespace ugts::chess2
