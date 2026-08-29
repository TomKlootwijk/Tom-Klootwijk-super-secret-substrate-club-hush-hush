#pragma once

#include <bit>
#include <cstdint>
#include <stdexcept>

namespace ugts5 {

struct PackedNodeFields {
    std::uint8_t family{};
    std::uint8_t kappa{};
    std::int8_t delta_rho{};
    std::uint8_t delta_theta{};
    std::uint8_t grammar_path{};
    std::uint8_t local_flags{};
    bool active{};
};

struct PackedNode32 {
    static constexpr unsigned parity_shift = 31;
    static constexpr unsigned op_shift = 27;
    static constexpr unsigned rho_shift = 19;
    static constexpr unsigned theta_shift = 11;
    static constexpr unsigned path_shift = 3;
    static constexpr unsigned flags_shift = 1;
    static constexpr std::uint32_t payload_mask = 0x7fffffffu;

    static constexpr std::uint8_t operator_id(const PackedNodeFields& f) noexcept {
        return static_cast<std::uint8_t>((f.family << 1u) | f.kappa);
    }

    static constexpr std::uint32_t payload_parity(std::uint32_t payload) noexcept {
        return std::popcount(payload & payload_mask) & 1u;
    }

    static constexpr std::uint32_t pack(const PackedNodeFields& f) {
        if (f.family > 7 || f.kappa > 1 || f.local_flags > 3) {
            throw std::invalid_argument("PackedNodeFields range error");
        }
        std::uint32_t payload = 0;
        payload |= (static_cast<std::uint32_t>(operator_id(f)) & 0x0fu) << op_shift;
        payload |= (static_cast<std::uint32_t>(static_cast<std::uint8_t>(f.delta_rho))) << rho_shift;
        payload |= static_cast<std::uint32_t>(f.delta_theta) << theta_shift;
        payload |= static_cast<std::uint32_t>(f.grammar_path) << path_shift;
        payload |= (static_cast<std::uint32_t>(f.local_flags) & 0x03u) << flags_shift;
        payload |= f.active ? 1u : 0u;
        return payload | (payload_parity(payload) << parity_shift);
    }

    static constexpr bool verify(std::uint32_t word) noexcept {
        return payload_parity(word) == ((word >> parity_shift) & 1u);
    }

    static constexpr PackedNodeFields unpack(std::uint32_t word) {
        if (!verify(word)) {
            throw std::invalid_argument("PackedNode32 parity mismatch");
        }
        const auto op = static_cast<std::uint8_t>((word >> op_shift) & 0x0fu);
        return PackedNodeFields{
            static_cast<std::uint8_t>(op >> 1u),
            static_cast<std::uint8_t>(op & 1u),
            static_cast<std::int8_t>((word >> rho_shift) & 0xffu),
            static_cast<std::uint8_t>((word >> theta_shift) & 0xffu),
            static_cast<std::uint8_t>((word >> path_shift) & 0xffu),
            static_cast<std::uint8_t>((word >> flags_shift) & 0x03u),
            (word & 1u) != 0u,
        };
    }

    static constexpr std::uint32_t klein_flip(std::uint32_t word) {
        auto f = unpack(word);
        f.kappa ^= 1u;
        f.delta_theta = static_cast<std::uint8_t>(0u - f.delta_theta);
        return pack(f);
    }
};

}  // namespace ugts5
